"""Pure metrics for reverse-engineering Honda stock-radar ACC_CONTROL.

The log reader lives in ``analyze_radar_commands.py``.  Keeping the feature construction,
domain classification, regression, binning, and transition metrics here makes the analysis
mutation-testable without private rlogs.

This module deliberately treats ``GAS_COMMAND`` as an opaque, signed CAN value.  It does not
pretend that the value is torque or acceleration, and it never turns a fitted value into a live
vehicle command.
"""

from __future__ import annotations

import numpy as np


GAS_INACTIVE = -30000.0
FEATURE_NAMES = ("bias", "speed", "speed_sq", "accel", "accel_speed", "pitch", "accel_pitch")


def command_domain(acc_enabled, brake_request, gas_command, *, gas_inactive=GAS_INACTIVE, control_on=None):
  """Classify each ACC_CONTROL sample as inactive, coast, gas, or brake.

  ``GAS_COMMAND`` is live whenever it is above Honda's inactive sentinel.  Brake wins when both
  bits appear together so a malformed mixed tuple is never mistaken for a gas sample.
  """
  enabled = np.asarray(acc_enabled, dtype=float) > 0.5
  if control_on is not None:
    enabled |= np.asarray(control_on, dtype=float) > 0.5
  brake = np.asarray(brake_request, dtype=float) > 0.5
  gas = np.asarray(gas_command, dtype=float)
  out = np.full(gas.shape, "inactive", dtype="U8")
  active = enabled & np.isfinite(gas)
  out[active & (gas <= gas_inactive) & ~brake] = "coast"
  out[active & (gas > gas_inactive) & ~brake] = "gas"
  out[active & brake] = "brake"
  return out


def feature_matrix(speed, accel, pitch):
  """Build the first bounded radar-gas feature set from aligned arrays."""
  speed = np.asarray(speed, dtype=float)
  accel = np.asarray(accel, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  return np.column_stack((
    np.ones(len(speed)),
    speed,
    speed * speed,
    accel,
    accel * speed,
    pitch,
    accel * pitch,
  ))


def finite_training_rows(features, target):
  """Return a finite-row mask for a regression matrix and target."""
  x = np.asarray(features, dtype=float)
  y = np.asarray(target, dtype=float)
  return np.isfinite(x).all(axis=1) & np.isfinite(y)


def fit_linear_model(features, target):
  """Fit an ordinary least-squares model and return coefficients plus fit diagnostics."""
  x = np.asarray(features, dtype=float)
  y = np.asarray(target, dtype=float)
  mask = finite_training_rows(x, y)
  if int(mask.sum()) < x.shape[1]:
    return {"coefficients": None, "n": int(mask.sum()), "rank": 0}
  coef, _, rank, _ = np.linalg.lstsq(x[mask], y[mask], rcond=None)
  return {"coefficients": coef, "n": int(mask.sum()), "rank": int(rank)}


def regression_metrics(actual, predicted):
  """Return route-held-out error metrics, including a low-command error slice."""
  y = np.asarray(actual, dtype=float)
  p = np.asarray(predicted, dtype=float)
  mask = np.isfinite(y) & np.isfinite(p)
  if not mask.any():
    return {"n": 0, "mae": None, "rmse": None, "r2": None, "p90_abs_error": None,
            "low_command_mae": None, "low_command_n": 0}
  y, p = y[mask], p[mask]
  error = p - y
  centered = y - np.mean(y)
  low = np.abs(y) <= 300.0
  return {
    "n": int(len(y)),
    "mae": float(np.mean(np.abs(error))),
    "rmse": float(np.sqrt(np.mean(error * error))),
    "r2": float(1.0 - np.sum(error * error) / np.sum(centered * centered)) if np.any(centered) else 0.0,
    "p90_abs_error": float(np.percentile(np.abs(error), 90)),
    "low_command_mae": float(np.mean(np.abs(error[low]))) if low.any() else None,
    "low_command_n": int(low.sum()),
  }


def cross_route_regression(routes):
  """Fit on all but one route, then score the held-out route.

  Each route is a mapping with ``name``, ``features`` and ``target`` keys.  Keeping route identity
  outside the feature matrix prevents a route-specific offset from masquerading as a radar law.
  """
  reports = []
  for i, test in enumerate(routes):
    train = [r for j, r in enumerate(routes) if j != i]
    if not train:
      continue
    train_x = np.concatenate([r["features"] for r in train])
    train_y = np.concatenate([r["target"] for r in train])
    fit = fit_linear_model(train_x, train_y)
    if fit["coefficients"] is None:
      continue
    pred = test["features"] @ fit["coefficients"]
    reports.append({"train_routes": [r["name"] for r in train],
                    "test_route": test["name"],
                    "fit": {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in fit.items()},
                    "metrics": regression_metrics(test["target"], pred)})
  return reports


def pooled_regression(routes):
  """Fit one radar model over all supplied routes for scoring custom routes."""
  if not routes:
    return {"coefficients": None, "n": 0, "rank": 0}
  x = np.concatenate([r["features"] for r in routes])
  y = np.concatenate([r["target"] for r in routes])
  return fit_linear_model(x, y)


def binned_summary(speed, accel, gas, speed_edges, accel_edges, *, min_count=20):
  """Summarize radar gas values by speed and wire-acceleration cells."""
  speed = np.asarray(speed, dtype=float)
  accel = np.asarray(accel, dtype=float)
  gas = np.asarray(gas, dtype=float)
  finite = np.isfinite(speed) & np.isfinite(accel) & np.isfinite(gas)
  rows = []
  for vlo, vhi in zip(speed_edges[:-1], speed_edges[1:], strict=True):
    for alo, ahi in zip(accel_edges[:-1], accel_edges[1:], strict=True):
      mask = finite & (speed >= vlo) & (speed < vhi) & (accel >= alo) & (accel < ahi)
      if int(mask.sum()) < min_count:
        continue
      values = gas[mask]
      rows.append({"speed_lo": float(vlo), "speed_hi": float(vhi),
                   "accel_lo": float(alo), "accel_hi": float(ahi),
                   "n": int(len(values)),
                   "median": float(np.median(values)),
                   "q10": float(np.percentile(values, 10)),
                   "q90": float(np.percentile(values, 90))})
  return rows


def transition_metrics(times, domains, gas, *, max_gap_s=0.25):
  """Measure command timing and domain transitions without bridging log gaps."""
  t = np.asarray(times, dtype=float)
  d = np.asarray(domains)
  g = np.asarray(gas, dtype=float)
  if len(t) < 2:
    return {"samples": int(len(t)), "rate_hz": 0.0, "gap_count": 0, "transitions": {},
            "direct_gas_to_brake": 0, "direct_brake_to_gas": 0,
            "gas_to_coast_to_brake": 0, "first_live_gas": []}
  dt = np.diff(t)
  contiguous = np.isfinite(dt) & (dt > 0) & (dt <= max_gap_s)
  transitions = {}
  first_live = []
  direct_gas_to_brake = direct_brake_to_gas = gas_to_coast_to_brake = 0
  for i in np.flatnonzero(contiguous & (d[1:] != d[:-1])) + 1:
    key = f"{d[i - 1]}->{d[i]}"
    transitions[key] = transitions.get(key, 0) + 1
    if d[i - 1] == "gas" and d[i] == "brake":
      direct_gas_to_brake += 1
    if d[i - 1] == "brake" and d[i] == "gas":
      direct_brake_to_gas += 1
    if d[i - 1] == "coast" and d[i] == "brake":
      j = i - 1
      while j > 0 and d[j] == "coast" and contiguous[j - 1]:
        j -= 1
      if d[j] == "gas":
        gas_to_coast_to_brake += 1
  for i in np.flatnonzero(contiguous & (d[1:] == "gas") & (d[:-1] != "gas")) + 1:
    first_live.append(float(g[i]))
  valid_dt = dt[contiguous]
  return {
    "samples": int(len(t)),
    "rate_hz": float(1.0 / np.median(valid_dt)) if len(valid_dt) else 0.0,
    "duration_s": float(np.sum(np.minimum(np.where(np.isfinite(dt), np.maximum(dt, 0.0), 0.0), max_gap_s))),
    "gap_count": int((~contiguous).sum()),
    "transitions": transitions,
    "direct_gas_to_brake": int(direct_gas_to_brake),
    "direct_brake_to_gas": int(direct_brake_to_gas),
    "gas_to_coast_to_brake": int(gas_to_coast_to_brake),
    "first_live_gas": first_live,
  }


def domain_seconds(times, domains, *, max_gap_s=0.25):
  """Integrate domain exposure while refusing to bridge segment/log gaps."""
  t = np.asarray(times, dtype=float)
  d = np.asarray(domains)
  if len(t) < 2:
    return dict.fromkeys(("inactive", "coast", "gas", "brake"), 0.0)
  dt = np.diff(t)
  dt = np.minimum(np.where(np.isfinite(dt) & (dt > 0), dt, 0.0), max_gap_s)
  return {name: float(np.sum(dt[d[:-1] == name])) for name in ("inactive", "coast", "gas", "brake")}


def quantiles(values):
  """Compact distribution summary used by the JSON report."""
  values = np.asarray(values, dtype=float)
  values = values[np.isfinite(values)]
  if not len(values):
    return {"n": 0}
  return {"n": int(len(values)),
          "min": float(np.min(values)),
          "q10": float(np.percentile(values, 10)),
          "median": float(np.median(values)),
          "q90": float(np.percentile(values, 90)),
          "max": float(np.max(values))}
