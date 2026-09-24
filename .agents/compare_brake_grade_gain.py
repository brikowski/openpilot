#!/usr/bin/env python3
"""Fit an Odyssey brake grade gain from stable full-rate response samples.

This is an observational response projection, not closed-loop replay. It isolates settled,
road-speed brake-domain samples, measures the recorded ``aEgo-carControl`` error, and asks what
gain on ``g*sin(filtered_pitch)`` would have minimized that error if command-to-response gain were
locally one. It cannot prove how Honda will respond to the counterfactual command; only a drive on
the candidate can do that.
"""
import argparse
from collections import deque

import numpy as np

from extract import load
from tuning_metrics import causal_lpf

PITCH_FILTER_TAU = 0.5
RESPONSE_FILTER_TAU = 0.2
STABLE_REQUEST_SPAN = 0.08
STABLE_REQUEST_WINDOW_S = 0.5
ENTRY_SETTLE_S = 1.0
MIN_SPEED = 5.0
DEFAULT_STRIDE = 20  # 5 Hz from the 100 Hz control grid


def trailing_span(values, width):
  """Trailing max-minus-min in O(n), with incomplete leading windows rejected."""
  values = np.asarray(values, dtype=float)
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
      out[i] = values[maxima[0]] - values[minima[0]]
  return out


def brake_points(d, stride=DEFAULT_STRIDE):
  """Return settled samples: error, grade basis, request, speed, lead, wire error."""
  t = np.asarray(d["t"], dtype=float)
  if len(t) < 2:
    return np.empty((0, 6))
  dt = float(np.median(np.diff(t)))
  request = np.asarray(d["request"], dtype=float)
  brake = np.asarray(d["brake_request"], dtype=bool)
  entry_index = np.full(len(t), -1, dtype=int)
  last_entry = -1
  for i in range(1, len(t)):
    if brake[i] and not brake[i - 1]:
      last_entry = i
    entry_index[i] = last_entry
  age = np.where(entry_index >= 0, t - t[np.maximum(entry_index, 0)], -np.inf)
  width = max(1, int(round(STABLE_REQUEST_WINDOW_S / dt)))
  stable_request = trailing_span(request, width) <= STABLE_REQUEST_SPAN
  pitch = causal_lpf(np.asarray(d["pitch"], dtype=float), dt, PITCH_FILTER_TAU, initial=0.0)
  actual = causal_lpf(np.asarray(d["aego"], dtype=float), dt, RESPONSE_FILTER_TAU)
  wire = np.asarray(d["accel_command"], dtype=float)
  mask = (np.asarray(d["active"], dtype=bool) & np.asarray(d["pid"], dtype=bool) &
          ~np.asarray(d["gas_pressed"], dtype=bool) & ~np.asarray(d["brake_pressed"], dtype=bool) &
          brake & (np.asarray(d["vego"], dtype=float) >= MIN_SPEED) &
          (age >= ENTRY_SETTLE_S) & stable_request & np.isfinite(actual) & np.isfinite(pitch) &
          np.isfinite(request) & np.isfinite(wire))
  ix = np.flatnonzero(mask)[::stride]
  grade_basis = 9.81 * np.sin(pitch[ix])
  return np.column_stack((actual[ix] - request[ix], grade_basis, request[ix], d["vego"][ix],
                          np.asarray(d["has_lead"], dtype=float)[ix], wire[ix] - request[ix]))


def fitted_grade_gains(error, grade_basis, response_sensitivity=1.0, weights=None):
  """Return least-squares and minimum-MAE gains for a projected grade correction."""
  error = np.asarray(error, dtype=float)
  effect = np.asarray(grade_basis, dtype=float) * response_sensitivity
  weights = np.ones(len(error)) if weights is None else np.asarray(weights, dtype=float)
  denominator = float(np.dot(weights * effect, effect))
  least_squares = float(-np.dot(weights * error, effect) / denominator) if denominator else np.nan
  grid = np.linspace(-0.5, 1.5, 2001)
  mae = np.asarray([np.average(np.abs(error + gain * effect), weights=weights) for gain in grid])
  return least_squares, float(grid[np.argmin(mae)])


def summarize(label, points, weights=None):
  if not len(points):
    print(f"{label}: n=0")
    return
  error, grade_basis = points[:, 0], points[:, 1]
  least_squares, minimum_mae = fitted_grade_gains(error, grade_basis, weights=weights)
  projected = error + 0.3 * grade_basis
  print(f"{label}: n={len(points)}, gain least-squares/minimum-MAE={least_squares:.3f}/{minimum_mae:.3f}, "
        f"MAE raw/gain-0.3={np.average(np.abs(error), weights=weights):.3f}/"
        f"{np.average(np.abs(projected), weights=weights):.3f}, "
        f"wire-request RMS={np.sqrt(np.mean(points[:, 5] ** 2)):.4f}")


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("routes", nargs="+")
  args = parser.parse_args()
  blocks = []
  for route in args.routes:
    points = brake_points(load(route))
    blocks.append(points)
    summarize(route, points)
  nonempty = [block for block in blocks if len(block)]
  if not nonempty:
    return
  pooled = np.vstack(nonempty)
  summarize("all", pooled)
  route_weights = np.concatenate([np.full(len(block), 1.0 / len(block)) for block in nonempty])
  summarize("route-balanced", pooled, route_weights)
  summarize("no-lead", pooled[pooled[:, 4] == 0])
  summarize("lead", pooled[pooled[:, 4] == 1])


if __name__ == "__main__":
  main()
