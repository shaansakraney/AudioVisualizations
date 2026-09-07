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

2. **Scenes don't know how long the strip is.** A scene returns however many
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

MAGIC = b"AVZ"
VERSION = 1
HEADER = struct.Struct(">3sBBH")   # magic, version, seq, count
MAX_UDP_PIXELS = 488


# ---------------------------------------------------------------------------
# transports -- each is just send(bytes) / close()
# ---------------------------------------------------------------------------

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
    simply go nowhere and the visuals carry on."""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.name = f"udp://{host}:{port}"
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)

    def send(self, payload):
        try:
            self._sock.sendto(payload, (self.host, self.port))
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
    brightness -> gamma along the way."""

    # ---- tuning knobs (all safe to tweak) ----------------------------------
    LED_FPS = 60          # send rate, independent of the render frame rate
    ATTACK = 0.55         # smoothing: how fast a pixel brightens
    RELEASE = 0.20        # smoothing: how slowly it dims (the "musical" feel)
    BEAT_GAIN = 0.9       # beat: extra brightness at beat_strength 1.0
    BEAT_WHITE = 0.35     # beat: how far the color snaps toward white
    GAMMA = 2.2           # LEDs are linear, eyes are not -- without this
                          # everything above ~40% reads as full blast
    # ------------------------------------------------------------------------

    def __init__(self, transport, count=60, brightness=1.0):
        self.transport = transport
        self.count = max(1, int(count))
        self.brightness = float(np.clip(brightness, 0.0, 1.0))
        self.name = transport.name

        self._lock = threading.Lock()
        self._pending = None          # latest (pixels, beat_strength)
        self._thread = None
        self._running = False
        self._seq = 0
        self.sent = 0
        self.skipped = 0              # ticks where no new frame had arrived

        self._smoothed = np.zeros((self.count, 3), dtype=np.float32)
        # gamma as a 256-entry LUT: one indexing op per frame instead of a pow
        self._gamma_lut = np.round(
            255.0 * (np.arange(256) / 255.0) ** self.GAMMA
        ).astype(np.uint8)

    # -- render-thread side --------------------------------------------------

    def submit(self, pixels, f=None):
        """Called once per rendered frame. Cheap: normalizes to an (N,3)
        float array and drops it in the slot. Never touches the network."""
        if pixels is None:
            return
        px = np.asarray(pixels, dtype=np.float32).reshape(-1, 3)
        if px.size == 0:
            return
        with self._lock:
            self._pending = (px, float(f.beat_strength) if f is not None else 0.0)

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
                px, beat = pending
                self.transport.send(self._encode(self._process(px, beat)))
                self.sent += 1
                self._seq = (self._seq + 1) & 0xFF
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))

    def _process(self, px, beat):
        """resample -> smooth -> beat pulse -> brightness -> gamma.

        Order matters: smoothing runs *before* the beat pulse so the pulse
        stays sharp. Smoothing it too would be exactly the wrong thing -- the
        beat is the one moment the strip should snap rather than glide."""
        px = self._resample(px, self.count)

        coeff = np.where(px > self._smoothed, self.ATTACK, self.RELEASE)
        self._smoothed += coeff * (px - self._smoothed)
        out = self._smoothed.copy()

        if beat > 0.0:
            out *= 1.0 + self.BEAT_GAIN * beat
            out += (255.0 - out) * (self.BEAT_WHITE * beat)

        out *= self.brightness
        out = np.clip(out, 0, 255).astype(np.uint8)
        return self._gamma_lut[out]

    @staticmethod
    def _resample(px, n_out):
        """Stretch a scene's natural pixel count onto the physical strip, so
        a 16-bin spectrum lights a 300-LED strip (or a 1-pixel analog one)
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
        return f"{self.name} n={self.count} sent={self.sent}"


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

def build_sink(spec, count=60, brightness=1.0):
    """spec is 'none', 'udp://host:port', or 'serial:///dev/tty.usbmodemXXXX'."""
    if not spec or spec == "none":
        return LedSink(NullTransport(), count, brightness)

    if spec.startswith("udp://"):
        hostport = spec[len("udp://"):]
        host, _, port = hostport.partition(":")
        if count > MAX_UDP_PIXELS:
            raise SystemExit(
                f"--led-count {count} exceeds {MAX_UDP_PIXELS}, the most that "
                f"fits in one UDP datagram. Use serial:// for a longer strip.")
        return LedSink(UdpTransport(host, int(port or 4210)), count, brightness)

    if spec.startswith("serial://"):
        port = spec[len("serial://"):]
        try:
            return LedSink(SerialTransport(port), count, brightness)
        except ImportError:
            raise SystemExit("serial:// needs pyserial -- pip install pyserial")

    raise SystemExit(f"--leds {spec!r}: expected none, udp://host:port, "
                     f"or serial:///dev/tty...")
