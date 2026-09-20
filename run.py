"""
run.py
------
Entry point. Examples:

    python run.py                          # resting/idle mode (no audio hardware needed)
    python run.py --source mic             # default input device
    python run.py --source line --device 2 # a specific input (see --list-devices)
    python run.py --source wav --wav song.wav  # looked up in AudioFiles/ if not found as-is
    python run.py --source loopback --spotify  # react to Spotify + show its album art
    python run.py --list-devices
    python run.py --fullscreen                 # fill the screen (f toggles, esc leaves)
    python run.py --fullscreen --display 1     # ...on a second monitor / TV

    # drive an LED strip alongside the screen (see README: LED strip output)
    python run.py --source mic --leds udp://audioviz.local:4210 --led-count 60
    python run.py --leds udp://127.0.0.1:4210 --led-count 16   # + led_monitor.py
"""

import argparse
import sys

from app import App
from scenes import (PulseScene, SpectrumScene, CymaticsScene,
                    ConstellationScene, ChasmScene, VortexScene,
                    ResonanceScene, CartographScene, LatticeScene)

def build_source(args):
    if args.source == "resting":
        from audio import RestingSource
        return RestingSource()
    if args.source == "wav":
        if not args.wav:
            sys.exit("--source wav requires --wav PATH")
        from audio import WavSource, resolve_wav
        return WavSource(resolve_wav(args.wav))
    if args.source == "loopback":
        from audio import LiveAudioSource, find_loopback_device
        idx = args.device if args.device is not None else find_loopback_device()
        if idx is None:
            print("No loopback device found -- falling back to the microphone.")
            print("For a clean signal: brew install blackhole-2ch, then make a")
            print("Multi-Output Device (speakers + BlackHole) in Audio MIDI Setup.")
        return LiveAudioSource(device=idx)
    # "mic" and "line" are the same code path; the device index picks the input
    from audio import LiveAudioSource
    return LiveAudioSource(device=args.device)


def build_now_playing(args):
    """The Spotify metadata/art provider, or None when --spotify is off or
    no backend is usable on this machine."""
    if not args.spotify:
        return None
    from nowplaying import build_provider
    provider = build_provider(args.spotify_source)
    if provider is None:
        print("Spotify integration unavailable: no Spotify.app found, and no")
        print("SPOTIFY_CLIENT_ID set for the Web API backend. Continuing without it.")
        return None
    print(f"Spotify: using the {provider.backend.name} backend.")
    return provider


def parse_canvas(spec):
    """'1920x1080' -> (1920, 1080); None -> None (match the window)."""
    if not spec:
        return None
    try:
        w, h = spec.lower().split("x")
        return (int(w), int(h))
    except ValueError:
        sys.exit(f"--canvas {spec!r}: expected WxH, e.g. 1920x1080")


def build_led_sink(args):
    """The LED strip output, or a no-op sink when --leds is off (the sink is
    always constructed so the render loop has no special cases).

    The profile comes off disk if it's there, so a strip you tuned in a
    previous session comes back tuned. --led-brightness still wins when it is
    given explicitly, since a flag you typed should beat a saved file."""
    from led import build_sink
    from ledprofile import LedProfile
    profile = LedProfile.load(args.led_profile)
    if args.led_brightness is not None:
        profile.brightness = max(0.0, min(1.0, args.led_brightness))
    sink = build_sink(args.leds, args.led_count, profile)
    if args.leds and args.leds != "none":
        print(f"LEDs: {sink.stats()}")
        print(f"      profile {profile.path} -- press l in the window to tune")
    return sink


def build_output_switcher(args):
    """The system-output borrow, or None when it is off.

    On by default for --source loopback (which is unusable without a
    Multi-Output device selected) and off for every other source, since a mic
    or wav run has no reason to touch what you are listening through."""
    want = args.switch_output
    if want is None:
        want = args.source == "loopback"
    if want is False or want == "none":
        return None
    from outputswitch import OutputSwitcher, DEFAULT_TARGET
    target = DEFAULT_TARGET if want is True else want
    switcher = OutputSwitcher(target)
    switcher.switch()
    return switcher


def main():
    p = argparse.ArgumentParser(description="audio-reactive visuals starter")
    p.add_argument("--source", default="resting",
                   choices=["resting", "mic", "line", "wav", "loopback"])
    p.add_argument("--wav", help="path to a .wav file (for --source wav)")
    p.add_argument("--device", type=int, default=None,
                   help="input device index (see --list-devices)")
    p.add_argument("--list-devices", action="store_true",
                   help="print available audio devices and exit")
    p.add_argument("--switch-output", nargs="?", const=True, default=None,
                   metavar="DEVICE",
                   help="borrow a system output device for this run and put "
                        "the old one back on exit (macOS, needs "
                        "switchaudio-osx). Bare flag = 'Multi-Output Device'; "
                        "the default with --source loopback. "
                        "--switch-output=none opts out.")
    p.add_argument("--spotify", action="store_true",
                   help="pull the current track's album art + palette from Spotify")
    p.add_argument("--spotify-source", default="applescript",
                   choices=["applescript", "web"],
                   help="applescript = local Spotify app (no setup); "
                        "web = Web API (needs SPOTIFY_CLIENT_ID)")
    p.add_argument("--fullscreen", action="store_true",
                   help="start fullscreen on the chosen display (f toggles it "
                        "at runtime, esc leaves it)")
    p.add_argument("--scale", type=float, default=0.5,
                   help="initial window size as a fraction of the 1920x1080 "
                        "canvas (0.5 = 960x540); the window is resizable")
    p.add_argument("--display", type=int, default=0,
                   help="which monitor to open on (0 = primary) -- point this "
                        "at the TV")
    p.add_argument("--supersample", type=int, default=2, metavar="N",
                   help="render at NxN the output pixels and average down; "
                        "this is the anti-aliasing dial (1 = off, 2 = default, "
                        "3 = maximum quality)")
    p.add_argument("--canvas", default=None, metavar="WxH",
                   help="pin a fixed logical render size (e.g. 1920x1080) "
                        "instead of matching the window; effects then behave "
                        "identically at any window size, but get resampled")
    p.add_argument("--leds", default="none",
                   help="LED strip output: none, udp://HOST:PORT (ESP32 over "
                        "WiFi -- HOST can be the board's mDNS name, "
                        "audioviz.local, which survives a DHCP address "
                        "change), or serial:///dev/tty... (USB)")
    p.add_argument("--led-count", type=int, default=60,
                   help="number of LEDs on the strip (use 1 for an analog "
                        "RGB strip, which is one color end to end)")
    p.add_argument("--led-brightness", type=float, default=None,
                   help="global LED brightness, 0..1 (overrides the saved "
                        "profile for this run)")
    p.add_argument("--led-profile", default=None, metavar="PATH",
                   help="where the LED profile -- color scheme, reactivity, "
                        "brightness, strip mapping -- is loaded from and "
                        "saved to (default: led_profile.json next to run.py). "
                        "Tune it live with l in the window.")
    args = p.parse_args()

    if args.list_devices:
        from audio import list_devices
        list_devices()
        return

    # --source loopback only works with a Multi-Output-style device selected,
    # so it opts in by default; any other source leaves the output alone.
    switcher = build_output_switcher(args)

    # Register scenes here. Order = the number keys 1..9 in the window, and
    # nine is all the keys there are -- so BarsScene, NebulaScene and
    # LightningScene were retired from this list when the 3D family arrived.
    # They are still defined in scenes.py: to put one back, import it above
    # and swap it in for whichever of these you want the key for instead.
    scenes = [PulseScene(), SpectrumScene(), CymaticsScene(),
              ConstellationScene(), ChasmScene(), VortexScene(),
              ResonanceScene(), CartographScene(), LatticeScene()]
    try:
        App(build_source(args), scenes, now_playing=build_now_playing(args),
            led_sink=build_led_sink(args), scale=args.scale,
            fullscreen=args.fullscreen, display=args.display,
            canvas=parse_canvas(args.canvas),
            supersample=args.supersample).run()
    finally:
        if switcher is not None:
            switcher.restore()


if __name__ == "__main__":
    main()
