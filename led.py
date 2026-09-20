"""
led.py
------
The second output. Where `Scene.draw()` paints pixels onto the screen,
`Scene.led()` paints them onto a physical LED strip, driven by the exact same
`Features`. Both branches hang off the same frame:

    Features -+-> Scene.draw()  -> canvas -> window
              +-> Scene.led(f)  -> LedSink -> transport -> ESP32 -> strip

Two rules make this safe and portable:

1. **The render thread never blocks on I/O.** `submit()` drops a frame into a
   lock-guarded slot and returns; a daemon thread does the actual sending.
   This is the same split `FeatureExtractor` (push/read) and
   `NowPlayingProvider` use, for the same real-time reason. A dropped LED
   frame is invisible; a stalled render loop is not.

2. **How the strip *looks* is tunable apart from the scenes.** Everything
   between the scene's frame and the wire -- brightness, floor, gain,
   contrast, smoothing, beat pulse, palette, saturation, and which way round
   the strip runs -- comes from a `LedProfile` (see ledprofile.py), edited
   live from the `l` panel and saved to disk. A scene decides what the strip
   *shows*; the profile decides how that lands in the room.

3. **Scenes don't know how long the strip is.** A scene returns however many
   pixels are natural for it -- 1 for a solid glow, len(f.bands) for a
   spectrum -- and `LedSink` resamples to the physical count. That is what
   keeps an analog 12V RGB strip (which is just N=1) and a 300-LED WS2812
   strip the same code path.

Wire protocol (one frame; also implemented in firmware/av_proto.h):

    offset  size  field
    0       3     magic b"AVZ"
    3       1     version (1)
    4       1     sequence number, wraps at 256 -- lets the MCU spot drops
    5       2     pixel count, big-endian
    7       3*N   RGB bytes, no padding

The magic doubles as a resync marker on serial, where there are no packet
boundaries. Over UDP each frame is exactly one datagram, so the 7-byte header
keeps N <= 488 inside a standard 1472-byte MTU.
"""

import socket
import struct
import threading
import time

import numpy as np

from fx import hsv
from ledprofile import LedProfile, apply_level, recolor, spatial_map

MAGIC = b"AVZ"
VERSION = 1
HEADER = struct.Struct(">3sBBH")   # magic, version, seq, count
MAX_UDP_PIXELS = 488


# ---------------------------------------------------------------------------
# transports -- each is just send(bytes) / close()
# ---------------------------------------------------------------------------

def _is_ipv4_literal(host):
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        return False


class NullTransport:
    """Used when --leds is off, so App never needs a conditional branch."""
    name = "none"

    def send(self, payload):
        pass

    def close(self):
        pass


class UdpTransport:
    """Fire-and-forget datagrams. No new dependency (stdlib socket), and no
    connection to lose -- if the ESP32 is asleep or off the network the sends
    simply go nowhere and the visuals carry on.

    The host may be a name rather than an address -- `audioviz.local`, which
    is what the firmware advertises over mDNS. That is the whole point of the
    naming scheme: the board keeps taking a DHCP address, so its IP is free to
    change every time it is unplugged from the wall, and only the name stays
    put. Two consequences are handled here:

    * The name is resolved to an address *once* and cached. Handing a hostname
      straight to `sendto` would make every one of 60 frames a second a fresh
      blocking mDNS lookup.
    * The cache is refreshed every `REFRESH_S` anyway, because a new lease
      means a new address behind the same name. A lookup that fails keeps the
      previous address rather than going dark -- a failure means the board (or
      the responder) is unreachable this instant, not that it moved.

    The lookup itself runs on its own short-lived thread, never inline in
    `send()`: a *failing* mDNS lookup on macOS takes a full 5 seconds to come
    back, which is measured, not hypothetical, and that is exactly the case
    that happens all the time -- run.py started before the board finished
    joining the network. So the sender thread keeps its cadence, sends go
    nowhere until an address exists, and the strip picks up within `RETRY_S`
    of the board appearing.
    """

    RETRY_S = 5.0      # while we have no address at all
    REFRESH_S = 30.0   # re-check a working name, in case the lease changed

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.name = f"udp://{host}:{port}"
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        # A literal address is its own answer; resolving it would be pointless
        # work on a timer forever.
        self._literal = _is_ipv4_literal(host)
        self._addr = (host, port) if self._literal else None
        self._next_lookup = 0.0
        self._looking_up = False

    def _lookup(self):
        """Refresh the cached address, on a thread of its own. Never raises;
        leaves the previous address in place if the lookup fails, since a
        failure means unreachable-right-now, not moved."""
        try:
            info = socket.getaddrinfo(self.host, self.port, socket.AF_INET,
                                      socket.SOCK_DGRAM)
            self._addr = info[0][4]
        except OSError:
            pass
        # Back off less while we've never resolved, so a board that joins the
        # network after run.py started is picked up within a few seconds.
        self._next_lookup = time.monotonic() + (
            self.REFRESH_S if self._addr else self.RETRY_S)
        self._looking_up = False

    def send(self, payload):
        if (not self._literal and not self._looking_up
                and time.monotonic() >= self._next_lookup):
            self._looking_up = True
            threading.Thread(target=self._lookup, daemon=True).start()
        if self._addr is None:
            return  # name doesn't resolve yet -- board is off or still joining
        try:
            self._sock.sendto(payload, self._addr)
        except (BlockingIOError, OSError):
            pass  # buffer full or no route -- skip this frame, never stall

    def close(self):
        self._sock.close()


class SerialTransport:
    """USB-tethered fallback (a plain Arduino, or an ESP32 you'd rather not
    put on WiFi). pyserial is imported here rather than at module scope so it
    stays an optional install -- the same guard audio.py uses for sounddevice."""

    def __init__(self, port, baud=500000):
        import serial  # optional dependency: pip install pyserial
        self.name = f"serial://{port}"
        self._ser = serial.Serial(port, baud, timeout=0, write_timeout=0)
        time.sleep(2.0)  # classic Arduino auto-reset on port open

    def send(self, payload):
        try:
            self._ser.write(payload)
        except Exception:
            pass

    def close(self):
        try:
            self._ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# the sink
# ---------------------------------------------------------------------------

class LedSink:
    """Takes a frame of RGB pixels per render frame and streams it to the
    strip on its own thread, applying resample -> smooth -> beat pulse ->
    floor -> brightness -> gamma along the way."""

    LED_FPS = 60          # send rate, independent of the render frame rate

    def __init__(self, transport, count=60, profile=None):
        self.transport = transport
        self.count = max(1, int(count))
        self.profile = profile if profile is not None else LedProfile()
        self.name = transport.name

        self._lock = threading.Lock()
        self._pending = None          # latest (pixels, Features, NowPlaying)
        self._thread = None
        self._running = False
        self._seq = 0
        self.sent = 0
        self.skipped = 0              # ticks where no new frame had arrived

        self._smoothed = np.zeros((self.count, 3), dtype=np.float32)
        self._gamma_lut = None        # built by _refresh_derived()
        self._floor_pre = 0.0
        self._derived_from = None     # (gamma, floor) the caches were built at
        self._refresh_derived()

    def _refresh_derived(self):
        """Rebuild the two caches that depend on profile values. Called from
        the sender thread at the top of every frame; a plain tuple compare is
        far cheaper than the pow it guards, and it means the panel can move
        gamma and floor live without any callback into here."""
        p = self.profile
        key = (p.gamma, p.floor)
        if key == self._derived_from:
            return
        # gamma as a 256-entry LUT: one indexing op per frame instead of a pow
        self._gamma_lut = np.round(
            255.0 * (np.arange(256) / 255.0) ** max(p.gamma, 0.01)
        ).astype(np.uint8)
        # floor is stated in terms of what the eye gets, i.e. post-gamma, so
        # the pre-gamma target it corresponds to is its gamma inverse.
        self._floor_pre = 255.0 * (p.floor ** (1.0 / max(p.gamma, 0.01)))
        self._derived_from = key

    # -- render-thread side --------------------------------------------------

    def submit(self, pixels, f=None, np_=None):
        """Called once per rendered frame. Cheap: normalizes to an (N,3)
        float array and drops it in the slot. Never touches the network.

        `f` and `np_` ride along because the profile's color schemes are the
        same `(i, n, val, f, np_)` functions the scenes use -- a scheme that
        drifts with f.t or tints toward the album accent needs them."""
        if pixels is None:
            return
        px = np.asarray(pixels, dtype=np.float32).reshape(-1, 3)
        if px.size == 0:
            return
        with self._lock:
            self._pending = (px, f, np_)

    # -- sender thread side --------------------------------------------------

    def start(self):
        if self._running or isinstance(self.transport, NullTransport):
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        period = 1.0 / self.LED_FPS
        next_t = time.monotonic()
        while self._running:
            with self._lock:
                pending = self._pending
            if pending is None:
                self.skipped += 1
            else:
                px, f, np_ = pending
                self.transport.send(self._encode(self._process(px, f, np_)))
                self.sent += 1
                self._seq = (self._seq + 1) & 0xFF
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))

    def _process(self, px, f, np_):
        """map -> level -> recolor -> smooth -> beat pulse -> floor ->
        brightness -> gamma. Every stage reads the LedProfile, which is the
        one place the strip's look can be tuned independently of the screen.

        Order matters three times. Gain and contrast come first, on the level
        rather than the channels, so the smoothing that follows sees the
        levels you actually asked for. Smoothing runs *before* the beat pulse
        so the pulse stays sharp -- smoothing it too would be exactly the
        wrong thing, since the beat is the one moment the strip should snap
        rather than glide. And the floor runs *after* the pulse but *before*
        brightness, so a beat still pulses up from the resting glow and the
        master brightness still dims the whole strip, floor included."""
        self._refresh_derived()
        p = self.profile
        beat = float(f.beat_strength) if f is not None else 0.0

        out = spatial_map(px, self.count, p, self._resample)
        out, level = apply_level(out, p)
        out = recolor(out, level, p, f, np_)

        coeff = np.where(out > self._smoothed, p.attack, p.release)
        self._smoothed += coeff * (out - self._smoothed)
        out = self._smoothed.copy()

        if beat > 0.0:
            out *= 1.0 + p.beat_gain * beat
            out += (255.0 - out) * (p.beat_white * beat)

        out = self._lift(out)
        out *= p.brightness
        out = np.clip(out, 0, 255).astype(np.uint8)
        return self._gamma_lut[out]

    def _lift(self, out):
        """Raise every pixel to at least the profile's floor of full output *without*
        changing its color: each pixel is scaled by a single factor, so its
        channel ratios -- its hue -- survive exactly. A quiet moment then
        rests on the scene's own color instead of switching the strip off,
        which is what keeps an analog strip looking alive between beats
        rather than blinking on and off out of black.

        It has to happen here rather than in each scene's led(), for two
        reasons: it is the one rule every scene should share, and gamma is
        what actually decides how dark a value looks -- a scene-side floor of
        0.15 lands at 0.15**2.2 = 1.4% of output, i.e. black. Hence
        _floor_pre, the gamma inverse of the profile's floor.

        A pixel that is exactly (0,0,0) carries no color to preserve and is
        left alone; scenes that want a resting glow should return their
        palette color dimmed, not black (see ConstellationScene.led, whose
        quiet bins stay the scheme's light blue).
        """
        if self.profile.floor <= 0.0:
            return out
        peak = out.max(axis=1, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            scale = np.where(peak > 0.0,
                             np.maximum(1.0, self._floor_pre / np.maximum(peak, 1e-6)),
                             1.0).astype(np.float32)
        return out * scale

    @staticmethod
    def _resample(px, n_out):
        """Stretch a scene's natural pixel count onto the physical strip, so
        a 24-bin spectrum lights a 300-LED strip (or a 1-pixel analog one)
        with no scene-side changes."""
        n_in = px.shape[0]
        if n_in == n_out:
            return px
        if n_out == 1:
            return px.mean(axis=0, keepdims=True)
        src = np.linspace(0.0, 1.0, n_in)
        dst = np.linspace(0.0, 1.0, n_out)
        return np.stack([np.interp(dst, src, px[:, c]) for c in range(3)], axis=1)

    def _encode(self, px):
        return HEADER.pack(MAGIC, VERSION, self._seq, px.shape[0]) + px.tobytes()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.transport.close()

    def stats(self):
        p = self.profile
        return (f"{self.name} n={self.count} sent={self.sent}  "
                f"bright {p.brightness:.2f} gain {p.gain:.2f} "
                f"scheme {p.scheme}")


# ---------------------------------------------------------------------------
# the default look -- what a scene gets for free
# ---------------------------------------------------------------------------

def default_led(f, np_=None):
    """The frame used for any scene that doesn't define led(). Hue from
    spectral brightness, value from loudness, tinted toward the album accent
    when a track is playing. LedSink adds the beat pulse on top, so every
    scene in the registry lights up -- and throbs -- with no edits at all."""
    if f is None:
        return np.zeros((1, 3), dtype=np.float32)
    val = 0.25 + 0.75 * max(f.rms, f.bass)
    col = np.array(hsv(f.centroid, 0.85, val), dtype=np.float32)
    if np_ is not None and np_.accent:
        col = 0.4 * col + 0.6 * np.array(np_.accent, dtype=np.float32) * val
    return col.reshape(1, 3)


# ---------------------------------------------------------------------------
# construction from a --leds command-line spec
# ---------------------------------------------------------------------------

def build_sink(spec, count=60, profile=None):
    """spec is 'none', 'udp://host:port', or 'serial:///dev/tty.usbmodemXXXX'."""
    if not spec or spec == "none":
        return LedSink(NullTransport(), count, profile)

    if spec.startswith("udp://"):
        hostport = spec[len("udp://"):]
        host, _, port = hostport.partition(":")
        if count > MAX_UDP_PIXELS:
            raise SystemExit(
                f"--led-count {count} exceeds {MAX_UDP_PIXELS}, the most that "
                f"fits in one UDP datagram. Use serial:// for a longer strip.")
        return LedSink(UdpTransport(host, int(port or 4210)), count, profile)

    if spec.startswith("serial://"):
        port = spec[len("serial://"):]
        try:
            return LedSink(SerialTransport(port), count, profile)
        except ImportError:
            raise SystemExit("serial:// needs pyserial -- pip install pyserial")

    raise SystemExit(f"--leds {spec!r}: expected none, udp://host:port, "
                     f"or serial:///dev/tty...")
