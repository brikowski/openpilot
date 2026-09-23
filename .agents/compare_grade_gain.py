#!/usr/bin/env python3
"""Fit one Odyssey uphill gas gain from matched full-rate response samples.

This is an observational screen, not closed-loop replay. Candidate and baseline samples are
matched one-to-one by speed, request, pitch, gear, and lead state. The gain fit interpolates the
matched baseline-to-candidate response effect; it does not claim that response is perfectly linear.
"""
import argparse
from collections import deque

import numpy as np

from extract import load

MATCH_LIMITS = np.array([2.0, 0.10, 0.015])


def rolling_span(values, radius):
  """Centered rolling max-minus-min in O(n), with incomplete edge windows rejected."""
  values = np.asarray(values, dtype=float)
  width = 2 * radius + 1
  out = np.full(len(values), np.inf)
  maxima, minima = deque(), deque()
  for i, value in enumerate(values):
    while maxima and values[maxima[-1]] <= value:
      maxima.pop()
    while minima and values[minima[-1]] >= value:
      minima.pop()
    maxima.append(i)
    minima.append(i)
    left = i - width + 1
    while maxima[0] < left:
      maxima.popleft()
    while minima[0] < left:
      minima.popleft()
    if left >= 0:
      out[left + radius] = values[maxima[0]] - values[minima[0]]
  return out


def grade_points(d, stride=10):
  """Return steady gas samples: speed, request, pitch, gear, lead, error, added gas."""
  t = np.asarray(d["t"], dtype=float)
  request = np.asarray(d["request"], dtype=float)
  gear = np.asarray(d["gear"], dtype=float)
  base_gas = np.interp(request, [-0.2, 2.0], [0.0, 2000.0])
  stable_gear = np.ones(len(t), dtype=bool)
  for edge in np.flatnonzero(np.diff(gear, prepend=gear[0]) != 0):
    stable_gear[np.abs(t - t[edge]) < 1.5] = False
  mask = (d["active"] & d["pid"] & ~d["gas_pressed"] & ~d["brake_pressed"] &
          ~d["brake_request"] & (d["gas_command"] > 0) & (d["vego"] > 10.0) &
          (request >= 0.05) & (request <= 1.10) & (d["pitch"] >= 0.0) &
          (d["pitch"] <= 0.09) & stable_gear & (rolling_span(request, 50) <= 0.10) &
          (np.abs(d["accel_command"] - request) < 0.05))
  ix = np.flatnonzero(mask)[::stride]
  return np.column_stack((d["vego"][ix], request[ix], d["pitch"][ix], gear[ix],
                          d["has_lead"][ix].astype(float), d["aego"][ix] - request[ix],
                          d["gas_command"][ix] - base_gas[ix]))


def one_to_one_matches(candidate, baseline, limits=MATCH_LIMITS):
  """Greedily select the closest non-reused pairs within matching tolerances."""
  if not len(candidate) or not len(baseline):
    return np.empty(0, dtype=int), np.empty(0, dtype=int)
  delta = candidate[:, None, :3] - baseline[None, :, :3]
  within = (np.all(np.abs(delta) <= limits, axis=2) &
            (candidate[:, None, 3] == baseline[None, :, 3]) &
            (candidate[:, None, 4] == baseline[None, :, 4]))
  distance = np.sum((delta / limits) ** 2, axis=2)
  distance[~within] = np.inf
  used_candidate, used_baseline, pairs = set(), set(), []
  for flat in np.argsort(distance, axis=None):
    i, j = np.unravel_index(flat, distance.shape)
    if not np.isfinite(distance[i, j]):
      break
    if i not in used_candidate and j not in used_baseline:
      pairs.append((i, j))
      used_candidate.add(i)
      used_baseline.add(j)
  if not pairs:
    return np.empty(0, dtype=int), np.empty(0, dtype=int)
  return np.asarray([p[0] for p in pairs]), np.asarray([p[1] for p in pairs])


def fitted_gains(candidate_error, baseline_error):
  """Return least-squares and minimum-MAE gains along the observed response-effect line."""
  effect = np.asarray(candidate_error) - np.asarray(baseline_error)
  baseline_error = np.asarray(baseline_error)
  denominator = float(np.dot(effect, effect))
  least_squares = float(-np.dot(baseline_error, effect) / denominator) if denominator else np.nan
  grid = np.linspace(0.0, 1.5, 301)
  mae = np.asarray([np.mean(np.abs(baseline_error + gain * effect)) for gain in grid])
  return least_squares, float(grid[np.argmin(mae)])


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("baseline")
  parser.add_argument("candidates", nargs="+")
  args = parser.parse_args()
  baseline = grade_points(load(args.baseline))
  blocks = [grade_points(load(route)) for route in args.candidates]
  candidate = np.vstack([block for block in blocks if len(block)])
  ci, bi = one_to_one_matches(candidate, baseline)
  print(f"candidate points={len(candidate)}, baseline points={len(baseline)}, matched={len(ci)}")
  if not len(ci):
    return
  for label, selected in (("all", np.ones(len(ci), dtype=bool)),
                          ("no-lead", candidate[ci, 4] == 0),
                          ("lead", candidate[ci, 4] == 1)):
    candidate_error = candidate[ci[selected], 5]
    baseline_error = baseline[bi[selected], 5]
    least_squares, minimum_mae = fitted_gains(candidate_error, baseline_error)
    summary = f"{label}: n={selected.sum()}, error MAE candidate/baseline="
    summary += f"{np.mean(np.abs(candidate_error)):.3f}/{np.mean(np.abs(baseline_error)):.3f}, "
    summary += f"gain least-squares/minimum-MAE={least_squares:.2f}/{minimum_mae:.2f}"
    print(summary)


if __name__ == "__main__":
  main()
