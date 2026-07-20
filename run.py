"""
run.py
------
Entry point. Examples:

    python run.py                          # resting/idle mode (no audio hardware needed)
    python run.py --source mic             # default input device
    python run.py --source line --device 2 # a specific input (see --list-devices)
    python run.py --source wav --wav song.wav
    python run.py --list-devices
"""

import argparse
import sys

from app import App
from scenes import PulseScene, BarsScene, LightningScene, NebulaScene, CymaticsScene


def build_source(args):
    if args.source == "resting":
        from audio import RestingSource
        return RestingSource()
    if args.source == "wav":
        if not args.wav:
            sys.exit("--source wav requires --wav PATH")
        from audio import WavSource
        return WavSource(args.wav)
    # "mic" and "line" are the same code path; the device index picks the input
    from audio import LiveAudioSource
    return LiveAudioSource(device=args.device)


def main():
    p = argparse.ArgumentParser(description="audio-reactive visuals starter")
    p.add_argument("--source", default="resting",
                   choices=["resting", "mic", "line", "wav"])
    p.add_argument("--wav", help="path to a .wav file (for --source wav)")
    p.add_argument("--device", type=int, default=None,
                   help="input device index (see --list-devices)")
    p.add_argument("--list-devices", action="store_true",
                   help="print available audio devices and exit")
    args = p.parse_args()

    if args.list_devices:
        from audio import list_devices
        list_devices()
        return

    # Register scenes here. Order = the number keys 1..9 in the window.
    scenes = [PulseScene(), BarsScene(), LightningScene(), CymaticsScene()]
    #scenes = [NebulaScene()]
    App(build_source(args), scenes).run()


if __name__ == "__main__":
    main()
