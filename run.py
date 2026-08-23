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
"""

import argparse
import os
import sys

from app import App
from scenes import (PulseScene, BarsScene, LightningScene, NebulaScene,
                     CymaticsScene, SpectrumScene)

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AudioFiles")


def resolve_wav(path):
    """Accept a bare filename (looked up in AudioFiles/) or a full/relative
    path as-is, so `--wav song.wav` just works if it's dropped in AudioFiles/
    without needing the full path spelled out every time."""
    if os.path.isfile(path):
        return path
    candidate = os.path.join(AUDIO_DIR, path)
    if os.path.isfile(candidate):
        return candidate
    sys.exit(f"--wav {path!r} not found (looked in cwd and {AUDIO_DIR})")


def build_source(args):
    if args.source == "resting":
        from audio import RestingSource
        return RestingSource()
    if args.source == "wav":
        if not args.wav:
            sys.exit("--source wav requires --wav PATH")
        from audio import WavSource
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


def main():
    p = argparse.ArgumentParser(description="audio-reactive visuals starter")
    p.add_argument("--source", default="resting",
                   choices=["resting", "mic", "line", "wav", "loopback"])
    p.add_argument("--wav", help="path to a .wav file (for --source wav)")
    p.add_argument("--device", type=int, default=None,
                   help="input device index (see --list-devices)")
    p.add_argument("--list-devices", action="store_true",
                   help="print available audio devices and exit")
    p.add_argument("--spotify", action="store_true",
                   help="pull the current track's album art + palette from Spotify")
    p.add_argument("--spotify-source", default="applescript",
                   choices=["applescript", "web"],
                   help="applescript = local Spotify app (no setup); "
                        "web = Web API (needs SPOTIFY_CLIENT_ID)")
    args = p.parse_args()

    if args.list_devices:
        from audio import list_devices
        list_devices()
        return

    # Register scenes here. Order = the number keys 1..9 in the window.
    scenes = [PulseScene(), BarsScene(), LightningScene(), CymaticsScene(),
              SpectrumScene(), NebulaScene()]
    App(build_source(args), scenes, now_playing=build_now_playing(args)).run()


if __name__ == "__main__":
    main()
