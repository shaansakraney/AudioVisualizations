"""
outputswitch.py
---------------
The third small piece of macOS plumbing, alongside the loopback input and the
Spotify metadata poll: it flips the *system output device* for the lifetime of
a run and puts it back afterwards.

Why this exists: capturing system audio means making a Multi-Output Device
(speakers + BlackHole) the default output, and a Multi-Output Device exposes
no master volume at all -- the keyboard volume keys and the menu-bar slider go
dead while it is selected, which reads as "my speakers are muted" even though
BlackHole is receiving full-scale audio the whole time. Living on Multi-Output
permanently makes every non-visualizer moment worse, so instead we borrow it:
switch on start, restore on exit, and the volume keys work again the moment
the window closes.

This is macOS-only and needs switchaudio-osx:

    brew install switchaudio-osx

Without it (or off macOS) every method is a no-op that prints a hint once, so
`run.py` needs no branch and nothing here can stop the visuals from starting.
"""

import atexit
import shutil
import subprocess

# The Audio MIDI Setup device that feeds both the speakers and BlackHole.
DEFAULT_TARGET = "Multi-Output Device"

_BIN = "SwitchAudioSource"


def available():
    """True when switchaudio-osx is installed and on PATH."""
    return shutil.which(_BIN) is not None


def _run(args):
    """SwitchAudioSource, or None if it is missing or fails. Errors are
    swallowed for the same reason nowplaying.py swallows its own: an audio
    device is not worth taking the render loop down over."""
    if not available():
        return None
    try:
        out = subprocess.run([_BIN] + args, capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def current_output():
    """The name of the current default output device, or None."""
    return _run(["-c", "-t", "output"])


def list_outputs():
    """Every output device name CoreAudio knows about."""
    out = _run(["-a", "-t", "output"])
    return [line.strip() for line in out.splitlines()] if out else []


class OutputSwitcher:
    """Switch the default output to `target` for the duration of a run.

    `restore()` is idempotent and also wired to atexit, so the device comes
    back even on a crash or a Ctrl-C that skips the normal shutdown path.
    """

    def __init__(self, target=DEFAULT_TARGET):
        self.target = target
        self.previous = None

    def switch(self):
        """Returns True if the output actually moved."""
        if not available():
            print("Output switching needs switchaudio-osx:")
            print("  brew install switchaudio-osx")
            print("Continuing without it -- select the output yourself in the "
                  "menu bar.")
            return False
        names = list_outputs()
        if self.target not in names:
            print(f"Output device {self.target!r} not found. Available: "
                  + ", ".join(names))
            return False
        now = current_output()
        if now == self.target:
            return False        # already there; nothing to restore to
        if _run(["-t", "output", "-s", self.target]) is None:
            print(f"Could not switch output to {self.target!r}.")
            return False
        self.previous = now
        atexit.register(self.restore)
        print(f"Output: {now} -> {self.target} (restored on exit)")
        return True

    def restore(self):
        if self.previous is None:
            return
        prev, self.previous = self.previous, None
        _run(["-t", "output", "-s", prev])
        print(f"Output: restored to {prev}")

    # so a caller can write `with OutputSwitcher() as _:`
    def __enter__(self):
        self.switch()
        return self

    def __exit__(self, *exc):
        self.restore()
        return False
