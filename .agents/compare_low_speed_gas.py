#!/usr/bin/env python3
"""Compare the bounded Odyssey gas trial with its exact-source baseline.

This is a conditioned observational road comparison, not frozen-input replay or a
causal calibration fit. It reports exposure and actual wire-gas separation before
tracking error; no overlap or no gas separation means the trial is unresolved.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from compare_grade_gain import rolling_span
from extract import load


BASELINE_SHA = "6915be202bb7"
TRIAL_SHA = "47196b9a4"
LEDGER = Path(__file__).with_name("log-validation-ledger.jsonl")
# speed m/s, requested acceleration m/s2, pitch rad, engine rpm
MATCH_LIMITS = np.array([1.5, 0.10, 0.01, 300.0])


def source_for_route(route, ledger=LEDGER):
  """Reject unknown, mixed, or decimated route provenance."""
  rows = [json.loads(line) for line in ledger.read_text().splitlines() if line]
  matching = [row for row in rows if row.get("route") == route]
  sources = {row.get("opendbc_commit", "") for row in matching}
  if len(sources) != 1 or not sources.pop() or any(row.get("qlog_fallback") for row in matching):
    raise ValueError(f"{route}: missing, mixed, or decimated source provenance")
  return matching[-1]["opendbc_commit"]


def trim_weight(speed, request):
  """Source-frozen shape of the trial, without assuming its physical gain."""
  def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)

  return (smoothstep((speed - 8.0) / 4.0) * smoothstep((24.0 - speed) / 4.0) *
          smoothstep((request - 0.4) / 0.4) * smoothstep((2.0 - request) / 0.4))


def trial_points(d, *, stride=20):
  """Return stable gas samples: speed/request/pitch/rpm, gear/lead/source, gas/error/weight."""
  t = np.asarray(d["t"], dtype=float)
  if len(t) < 3:
    return np.empty((0, 10))
  dt = float(np.median(np.diff(t)))
  lag = round(0.6 / dt)
  radius = round(0.5 / dt)
  request = np.asarray(d["request"], dtype=float)
  gear = np.asarray(d["gear"], dtype=float)
  speed = np.asarray(d["vego"], dtype=float)
  weight = trim_weight(speed, request)
  mask = (d["active"] & d["pid"] & ~d["gas_pressed"] & ~d["brake_pressed"] &
          ~d["brake_request"] & (d["gas_command"] > 0) &
          (speed >= 8.0) & (speed < 24.0) & (request > 0.4) & (request < 2.0) &
          (weight > 0.05) & (np.abs(d["pitch"]) < 0.03) &
          (np.abs(d["accel_command"] - request) < 0.05) &
          (rolling_span(request, radius) <= 0.10) &
          np.isfinite(gear) & np.isfinite(d["rpm"]) & np.isfinite(d["aego"]))
  for edge in np.flatnonzero(np.diff(gear, prepend=gear[0]) != 0):
    mask[np.abs(t - t[edge]) < 1.5] = False
  mask[-lag:] = False
  ix = np.flatnonzero(mask & (np.arange(len(t)) % stride == 0))
  ix = ix[(t[ix + lag] - t[ix] <= 0.65) &
          np.isfinite(d["aego"][ix + lag]) &
          (gear[ix] == gear[ix + lag]) &
          (np.abs(request[ix + lag] - request[ix]) <= 0.10) &
          d["active"][ix + lag] & ~d["gas_pressed"][ix + lag] &
          ~d["brake_pressed"][ix + lag]]
  return np.column_stack((speed[ix], request[ix], d["pitch"][ix], d["rpm"][ix],
                          gear[ix], d["has_lead"][ix].astype(float), d["plan_source"][ix],
                          d["gas_command"][ix], d["aego"][ix + lag] - request[ix], weight[ix]))


def one_to_one_matches(trial, baseline, limits=MATCH_LIMITS):
  """Match without reusing a baseline frame; preserve exact gear and lead state."""
  if not len(trial) or not len(baseline):
    return np.empty(0, dtype=int), np.empty(0, dtype=int)
  delta = trial[:, None, :4] - baseline[None, :, :4]
  within = (np.all(np.abs(delta) <= limits, axis=2) &
            (trial[:, None, 4] == baseline[None, :, 4]) &
            (trial[:, None, 5] == baseline[None, :, 5]) &
            (trial[:, None, 6] == baseline[None, :, 6]))
  distance = np.sum((delta / limits) ** 2, axis=2)
  distance[~within] = np.inf
  used_trial, used_baseline, pairs = set(), set(), []
  for flat in np.argsort(distance, axis=None):
    i, j = np.unravel_index(flat, distance.shape)
    if not np.isfinite(distance[i, j]):
      break
    if i not in used_trial and j not in used_baseline:
      pairs.append((i, j))
      used_trial.add(i)
      used_baseline.add(j)
  return (np.asarray([i for i, _ in pairs], dtype=int),
          np.asarray([j for _, j in pairs], dtype=int))


def summarize(trial, baseline, limits=MATCH_LIMITS):
  ci, bi = one_to_one_matches(trial, baseline, limits)
  result = {"trial_samples": len(trial), "baseline_samples": len(baseline), "matched": len(ci)}
  if not len(ci):
    return result
  c, b = trial[ci], baseline[bi]
  return {**result, "trial_error_mae": float(np.mean(np.abs(c[:, 8]))),
          "baseline_error_mae": float(np.mean(np.abs(b[:, 8]))),
          "paired_error_delta": float(np.median(c[:, 8] - b[:, 8])),
          "wire_gas_delta": float(np.median(c[:, 7] - b[:, 7])),
          "median_weight": float(np.median(c[:, 9])),
          "expected_trim": float(-200.0 * np.median(c[:, 9])),
          "max_feature_delta": np.max(np.abs(c[:, :4] - b[:, :4]), axis=0).tolist()}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--baseline", nargs="+", required=True,
                      help=f"full-rate route(s) on nested {BASELINE_SHA}")
  parser.add_argument("--trial", nargs="+", required=True,
                      help=f"full-rate route(s) on nested {TRIAL_SHA}")
  args = parser.parse_args()
  for routes, expected in ((args.baseline, BASELINE_SHA), (args.trial, TRIAL_SHA)):
    for route in routes:
      actual = source_for_route(route)
      if not actual.startswith(expected):
        parser.error(f"{route}: nested {actual}, expected {expected}")
  baseline = np.vstack([trial_points(load(route)) for route in args.baseline])
  trial = np.vstack([trial_points(load(route)) for route in args.trial])
  for name, limits in (("strict", MATCH_LIMITS / 2), ("nominal", MATCH_LIMITS),
                       ("broad", MATCH_LIMITS * 1.5)):
    for lead_name, lead in (("all", None), ("no-lead", 0.0), ("lead", 1.0)):
      c = trial if lead is None else trial[trial[:, 5] == lead]
      b = baseline if lead is None else baseline[baseline[:, 5] == lead]
      result = summarize(c, b, limits)
      print(f"{name} {lead_name}: {result}")
      if result["matched"] and abs(result["wire_gas_delta"]) < 20:
        print("  no material matched wire-gas separation: response effect is not identifiable")


if __name__ == "__main__":
  main()
