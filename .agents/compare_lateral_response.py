#!/usr/bin/env python3
"""Screen high-authority Odyssey lateral response against source-compatible stock routes.

This matches observed drives; it does not predict what either controller would have done on the
other road. Require overlap before comparing actual versus desired lateral acceleration.
"""
import argparse

import numpy as np

from extract import load

MATCH_LIMITS = np.array([1.5, 0.20, 0.01, 0.25])  # speed, signed desired accel, pitch, desired slope


def lateral_points(d, *, stride=10):
  t = np.asarray(d["t"], dtype=float)
  if len(t) < 3:
    return np.empty((0, 5))
  desired = np.asarray(d["desired_lat_accel"], dtype=float)
  actual = np.asarray(d["actual_lat_accel"], dtype=float)
  slope = (desired - np.interp(t - 0.2, t, desired)) / 0.2
  mask = (d["lat_active"] & d["lat_state_active"] & ~d["steering_pressed"] &
          ~d["steer_fault_temp"] & ~d["steer_fault_perm"] &
          np.isfinite(actual) & np.isfinite(desired) &
          (d["vego"] >= 20.0) & (d["vego"] <= 24.0) &
          (np.abs(desired) >= 0.5) & (np.abs(desired) <= 2.0) &
          (d["pitch"] >= 0.015) & (d["pitch"] <= 0.055) &
          (np.abs(slope) < 0.5) & (np.abs(d["lat_output_torque_can"]) >= 2559.0))
  indices = np.flatnonzero(mask)[::stride]
  under = np.sign(desired[indices]) * (desired[indices] - actual[indices])
  return np.column_stack((d["vego"][indices], desired[indices], d["pitch"][indices],
                          slope[indices], under))


def matched_lateral(candidate, baseline, *, limits=MATCH_LIMITS):
  """Nearest observed stock point within every tolerance; baseline reuse stays visible."""
  empty = {"candidate_samples": len(candidate), "baseline_samples": len(baseline),
           "matched": 0, "unique_baseline": 0, "candidate_mae": None, "baseline_mae": None,
           "candidate_rms": None, "baseline_rms": None,
           "candidate_under_median": None, "baseline_under_median": None,
           "candidate_features": None, "baseline_features": None}
  if not len(candidate) or not len(baseline):
    return empty
  delta = candidate[:, None, :4] - baseline[None, :, :4]
  eligible = np.all(np.abs(delta) <= limits, axis=2)
  distance = np.sum((delta / limits) ** 2, axis=2)
  distance[~eligible] = np.inf
  best = np.argmin(distance, axis=1)
  matched = np.isfinite(distance[np.arange(len(candidate)), best])
  if not matched.any():
    return empty
  c = candidate[matched]
  b = baseline[best[matched]]
  return {**empty, "matched": len(c), "unique_baseline": len(np.unique(best[matched])),
          "candidate_mae": float(np.mean(np.abs(c[:, 4]))),
          "baseline_mae": float(np.mean(np.abs(b[:, 4]))),
          "candidate_rms": float(np.sqrt(np.mean(c[:, 4] ** 2))),
          "baseline_rms": float(np.sqrt(np.mean(b[:, 4] ** 2))),
          "candidate_under_median": float(np.median(c[:, 4])),
          "baseline_under_median": float(np.median(b[:, 4])),
          "candidate_features": np.median(c[:, :4], axis=0).tolist(),
          "baseline_features": np.median(b[:, :4], axis=0).tolist()}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("candidate")
  parser.add_argument("baselines", nargs="+")
  args = parser.parse_args()
  candidate = lateral_points(load(args.candidate))
  baseline = np.concatenate([lateral_points(load(route)) for route in args.baselines])
  result = matched_lateral(candidate, baseline)
  print(f"matched {result['matched']}/{result['candidate_samples']} candidate samples to "
        f"{result['unique_baseline']} distinct baseline samples")
  if result["matched"]:
    print(f"candidate/baseline under-response median "
          f"{result['candidate_under_median']:+.3f}/{result['baseline_under_median']:+.3f} m/s2")
    print(f"candidate/baseline MAE {result['candidate_mae']:.3f}/{result['baseline_mae']:.3f}, "
          f"RMS {result['candidate_rms']:.3f}/{result['baseline_rms']:.3f} m/s2")
    print(f"matched median speed/desired/pitch/slope "
          f"{np.round(result['candidate_features'], 3)}/{np.round(result['baseline_features'], 3)}")


if __name__ == "__main__":
  main()
