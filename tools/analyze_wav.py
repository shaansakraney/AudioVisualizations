"""
tools/analyze_wav.py
--------------------
Offline measurement harness for the loudness pipeline. Not part of the live
path and not something you run per song -- it exists so the auto-gain
constants in features.py get picked from numbers instead of by eye.

It reads an audio file directly (no audio device, no playback), feeds it to a
FeatureExtractor at the same block cadence audio.py's callbacks would, and
steps read() once per simulated frame. A 4-minute track runs in a couple of
seconds.

    python tools/analyze_wav.py song.wav              # summary + CSV
    python tools/analyze_wav.py song.wav --compare    # legacy vs current AGC

The number to watch is **drop**: p95 minus p50 of the 4s-smoothed envelope,
i.e. how far a drop lifts the visuals above the loud section before it. Per-
frame statistics mislead here -- `beat` (top 5% vs median) stayed healthy
through the exact failure where buildups and drops had become
indistinguishable. Tune on `drop`; watch `beat` and `floor` only for
regressions.
"""

import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio import BLOCK, resolve_wav                      # noqa: E402
from features import FeatureExtractor                     # noqa: E402

KEYS = ("rms", "bass", "mid", "treble")


class LegacyFeatureExtractor(FeatureExtractor):
    """The pre-dB-window auto-gain, kept here (rather than as dead weight in
    features.py) purely so --compare can measure what changed."""

    LEGACY_PEAK_DECAY = 0.9999   # per frame, as the old code applied it

    def _autogain(self, raw, ref, dt):
        ref = np.maximum(raw, np.maximum(ref * self.LEGACY_PEAK_DECAY, 1e-5))
        return ref, np.clip(raw / (ref + 1e-9), 0.0, 1.0)


def run(path, extractor_cls, fps=60.0):
    """Push `path` through a fresh extractor at `fps`. Returns a list of
    per-frame dicts flattening extractor.last_debug plus beat state."""
    import soundfile as sf

    snd = sf.SoundFile(path)
    sr = snd.samplerate
    fx = extractor_cls(sr)
    dt = 1.0 / fps

    rows = []
    pushed = 0          # samples handed to the extractor so far
    t = 0.0
    eof = False
    while not eof:
        t += dt
        # Emulate the real callback cadence: whole BLOCKs arrive as the
        # stream consumes them, not a fresh slice every frame.
        while pushed < t * sr:
            data = snd.read(BLOCK, dtype="float32", always_2d=True)
            if len(data) == 0:
                eof = True
                break
            fx.push(data.mean(axis=1))
            pushed += len(data)
        if eof:
            break

        f = fx.read(dt)
        d = fx.last_debug
        row = {"t": t, "beat": int(f.beat)}
        for k in KEYS:
            row[f"raw_{k}"] = d["raw"][k]
            row[f"ref_{k}"] = d["ref"][k]
            row[f"norm_{k}"] = d["norm"][k]
            row[f"env_{k}"] = d["env"][k]
        rows.append(row)
    snd.close()
    return rows, sr


def spread(values, loud_pct=95.0):
    """(gap, ratio) between the loudest `100-loud_pct`% of frames and the
    40th-60th percentile band.

    `gap` -- the absolute difference -- is the one that matters, because scenes
    map 0..1 onto radius/brightness linearly, so it *is* how much bigger a drop
    looks than the passage before it. The ratio is reported alongside but does
    not compare across mappings: a linear mapping and a dB mapping put the same
    musical difference at wildly different ratios."""
    v = np.asarray(values, dtype=np.float64)
    if len(v) < 100:
        return float("nan"), float("nan")
    loud = v[v >= np.percentile(v, loud_pct)].mean()
    lo, hi = np.percentile(v, 40), np.percentile(v, 60)
    mid = v[(v >= lo) & (v <= hi)].mean()
    return float(loud - mid), (float(loud / mid) if mid > 0 else float("nan"))


def drop_lift(values, fps=60.0, seconds=4.0):
    """How much a drop lifts the output above the loud section before it:
    p95 minus p50 of the `seconds`-smoothed envelope.

    This is the metric that matches the complaint. Per-frame statistics are
    dominated by individual beats and stayed healthy even when section-to-
    section contrast had collapsed -- which is exactly the failure that made
    buildups and drops look the same."""
    v = np.asarray(values, dtype=np.float64)
    w = int(seconds * fps)
    if len(v) < w * 4:
        return float("nan")
    sm = np.convolve(v, np.ones(w) / w, mode="valid")
    return float(np.percentile(sm, 95) - np.percentile(sm, 50))


def fidelity(env, raw_rms):
    """Correlation between what the visuals do and true loudness in dB. A high
    gap with a low correlation means the visuals are dramatic but not *about*
    the music."""
    v = np.asarray(raw_rms, dtype=np.float64)
    ok = v > 1e-9
    if ok.sum() < 100:
        return float("nan")
    return float(np.corrcoef(np.asarray(env)[ok], 20 * np.log10(v[ok]))[0, 1])


def db_stats(raw_rms):
    """Where the per-frame signal level actually sits, in dB below its own
    loud reference -- this is what RANGE_DB has to cover."""
    v = np.asarray(raw_rms, dtype=np.float64)
    v = v[v > 1e-9]
    db = 20 * np.log10(v)
    top = np.percentile(db, 95)
    return {p: float(np.percentile(db, p) - top) for p in (1, 5, 10, 25, 50, 75, 95)}


def summarize(name, rows, sr, fps=60.0):
    print(f"\n=== {name} ===")
    dur = rows[-1]["t"]
    beats = sum(r["beat"] for r in rows)
    print(f"{len(rows)} frames, {dur:.1f}s, {sr} Hz, "
          f"{beats} beats ({beats / dur * 60:.0f}/min)")

    raw_rms = [r["raw_rms"] for r in rows]
    print("\n  on the env the scenes actually see:")
    print("    drop   = p95-p50 of the 4s-smoothed envelope  <- the one to watch")
    print("    beat   = top 5% vs median band, per frame")
    print("    floor  = 10th percentile (how dark a quiet passage goes)")
    print(f"\n    {'':<8}{'drop':>7}{'beat':>7}{'floor':>7}{'corr':>7}")
    for k in KEYS:
        env = [r[f"env_{k}"] for r in rows]
        print(f"    {k:<8}{drop_lift(env, fps):7.2f}{spread(env)[0]:7.2f}"
              f"{np.percentile(env, 10):7.2f}{fidelity(env, raw_rms):7.2f}")

    print("\n  per-frame level distribution, dB relative to the 95th pct")
    for p, d in db_stats(raw_rms).items():
        print(f"    p{p:<3} {d:7.1f} dB")

    print("\n  output deciles (env)")
    hdr = "        " + "".join(f"{p:>7}" for p in range(10, 100, 10))
    print(hdr)
    for k in KEYS:
        v = np.asarray([r[f"env_{k}"] for r in rows])
        cells = "".join(f"{np.percentile(v, p):7.2f}" for p in range(10, 100, 10))
        print(f"    {k:<4}{cells}")


def write_csv(rows, out):
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", help="audio file; a bare name is looked up in AudioFiles/")
    ap.add_argument("--compare", action="store_true",
                    help="also run the legacy auto-gain for side-by-side numbers")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--csv", help="where to write the per-frame CSV (default: none)")
    args = ap.parse_args()

    path = resolve_wav(args.wav)
    rows, sr = run(path, FeatureExtractor, args.fps)
    if not rows:
        sys.exit(f"{path}: no frames analyzed (file too short?)")

    if args.compare:
        legacy, _ = run(path, LegacyFeatureExtractor, args.fps)
        summarize("legacy auto-gain (current bands; isolates the AGC)", legacy, sr, args.fps)
    summarize("current auto-gain", rows, sr, args.fps)

    if args.csv:
        write_csv(rows, args.csv)


if __name__ == "__main__":
    main()
