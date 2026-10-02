#!/usr/bin/env python3
"""Match Odyssey uphill carControl response across full-rate routes.

This is an observational screen, not a closed-loop replay. It reports exposure before response
statistics, so an unmatched bin cannot be mistaken for a treatment effect. Input arrays come from
extract.py: carControl is native-rate, CAN is zero-order-held, and grade/gear are route observations.
"""
import argparse

import numpy as np

from extract import load

BANDS = {"moderate": (0.10, 0.40), "high": (0.80, 1.05)}
MATCH_LIMITS = np.array([2.0, 0.10, 0.015])  # speed m/s, request m/s2, pitch rad


def uphill_points(d, band, *, min_episode_s=2.0, settle_s=0.5, gear_guard_s=1.5, stride=10):
  """Return settled, gear-stable gas samples: speed, request, pitch, gear, response error."""
  t = np.asarray(d["t"], dtype=float)
  if len(t) < 3:
    return np.empty((0, 5)), 0
  dt = float(np.median(np.diff(t)))
  req = np.asarray(d["request"], dtype=float)
  lo, hi = BANDS[band]
  gear = np.asarray(d["gear"], dtype=float)
  mask = (d["active"] & d["pid"] & d["allow_throttle"] & ~d["has_lead"] &
          (d["plan_source"] == 0) & ~d["gas_pressed"] & ~d["brake_pressed"] &
          ~d["brake_request"] & (d["gas_command"] > 0) & (d["vego"] > 10) &
          (d["pitch"] >= 0.04) & (d["pitch"] <= 0.09) &
          (req >= lo) & (req < hi) & (np.abs(d["accel_command"] - req) < 0.05) &
          np.isfinite(gear) & np.isfinite(d["aego"]))
  for edge in np.flatnonzero(np.diff(gear, prepend=gear[0]) != 0):
    mask[np.abs(t - t[edge]) <= gear_guard_s] = False
  indices = np.flatnonzero(mask)
  if not len(indices):
    return np.empty((0, 5)), 0
  gaps = np.diff(t) > 2.5 * dt
  splits = np.flatnonzero((np.diff(indices) > 1) | gaps[indices[:-1]])
  starts = indices[np.r_[0, splits + 1]]
  ends = indices[np.r_[splits, len(indices) - 1]] + 1
  keep = []
  episodes = 0
  for start, end in zip(starts, ends, strict=True):
    if end - start < round(min_episode_s / dt):
      continue
    episodes += 1
    keep.extend(range(start + round(settle_s / dt), end, stride))
  ix = np.asarray(keep, dtype=int)
  return np.column_stack((d["vego"][ix], req[ix], d["pitch"][ix], gear[ix],
                          d["aego"][ix] - req[ix])), episodes


def matched_response(candidate, baseline, *, limits=MATCH_LIMITS):
  """Nearest baseline for each candidate sample, only within all tolerances and exact gear."""
  empty = {"matched": 0, "candidate_samples": len(candidate), "baseline_samples": len(baseline),
           "unique_baseline": 0, "candidate_median": None, "baseline_median": None,
           "candidate_mae": None, "baseline_mae": None, "paired_median_delta": None,
           "candidate_features": None, "baseline_features": None,
           "candidate_gears": np.unique(candidate[:, 3]).tolist() if len(candidate) else [],
           "baseline_gears": np.unique(baseline[:, 3]).tolist() if len(baseline) else []}
  if not len(candidate) or not len(baseline):
    return empty
  delta = candidate[:, None, :3] - baseline[None, :, :3]
  within = np.all(np.abs(delta) <= limits, axis=2) & (candidate[:, None, 3] == baseline[None, :, 3])
  distance = np.sum((delta / limits) ** 2, axis=2)
  distance[~within] = np.inf
  best = np.argmin(distance, axis=1)
  good = np.isfinite(distance[np.arange(len(candidate)), best])
  if not good.any():
    return empty
  c = candidate[good]
  b = baseline[best[good]]
  return {**empty, "matched": len(c), "unique_baseline": len(np.unique(best[good])),
          "candidate_median": float(np.median(c[:, 4])),
          "baseline_median": float(np.median(b[:, 4])),
          "candidate_mae": float(np.mean(np.abs(c[:, 4]))),
          "baseline_mae": float(np.mean(np.abs(b[:, 4]))),
          "paired_median_delta": float(np.median(c[:, 4] - b[:, 4])),
          "candidate_features": np.median(c[:, :3], axis=0).tolist(),
          "baseline_features": np.median(b[:, :3], axis=0).tolist()}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("candidate")
  parser.add_argument("baseline")
  args = parser.parse_args()
  candidate = load(args.candidate)
  baseline = load(args.baseline)
  for band in BANDS:
    c, ce = uphill_points(candidate, band)
    b, be = uphill_points(baseline, band)
    result = matched_response(c, b)
    print(f"{band}: candidate episodes={ce}, baseline episodes={be}, "
          f"matched={result['matched']}/{result['candidate_samples']}, "
          f"baseline unique={result['unique_baseline']}, "
          f"gears={result['candidate_gears']}/{result['baseline_gears']}")
    if result["matched"]:
      print(f"  aEgo-carControl median={result['candidate_median']:+.3f}/"
            f"{result['baseline_median']:+.3f}, MAE={result['candidate_mae']:.3f}/"
            f"{result['baseline_mae']:.3f}, paired median delta="
            f"{result['paired_median_delta']:+.3f} m/s2")
      print(f"  matched speed/request/pitch medians={np.round(result['candidate_features'], 3)}/"
            f"{np.round(result['baseline_features'], 3)}")


if __name__ == "__main__":
  main()
