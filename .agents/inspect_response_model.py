#!/usr/bin/env python3
"""Screen gas/brake acceleration models with whole-route holdouts.

Observational prediction only: coefficients are not identified actuator gains and must not be
inverted into a controller. Excludes transitions; uses cached ZOH CAN, not independently checked
sent-frame freshness. Separate gas and brake fits preserve their distinct command units.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from extract import load
from tuning_metrics import causal_lpf


def delayed_response(signal, dt, delay, tau):
  """Causal first-order candidate; unavailable delayed history stays NaN."""
  filtered = causal_lpf(np.asarray(signal, dtype=float), dt, tau)
  frames = int(round(delay / dt))
  if not frames:
    return filtered
  output = np.full(len(filtered), np.nan)
  if frames < len(filtered):
    output[frames:] = filtered[:-frames]
  return output


def continuous_mask(valid, gear, t, history_s=2.0):
  """Require uninterrupted eligibility and unchanged target gear over the lookback."""
  valid = np.asarray(valid, dtype=bool)
  t = np.asarray(t, dtype=float)
  gear = np.asarray(gear, dtype=float)
  out = np.zeros(len(t), dtype=bool)
  start = 0
  for i in range(len(t)):
    if not valid[i] or not np.isfinite(gear[i]):
      start = i + 1
    elif i and (not valid[i - 1] or gear[i] != gear[i - 1] or not 0 < t[i] - t[i - 1] < .04):
      start = i
    if start <= i:
      out[i] = t[i] - t[start] >= history_s
  return out


def fit_balanced(matrices, targets):
  """Equal total least-squares weight per training route; no held-out samples."""
  weights = np.concatenate([np.full(len(y), 1 / np.sqrt(len(y))) for y in targets])
  x, y = np.vstack(matrices), np.concatenate(targets)
  coef = np.linalg.lstsq(x * weights[:, None], y * weights, rcond=None)[0]
  return coef, float(np.sum(((x @ coef - y) * weights) ** 2))


def prepare(data, domain):
  # Sample held CAN and state on actual control timestamps, approximately 50 Hz.
  ix = np.arange(0, len(data['t']), 2)
  t = data['t'][ix]
  gas = data['gas_command'][ix]
  brake = data['brake_request'][ix]
  active = (data['active'][ix] & data['pid'][ix] & ~data['gas_pressed'][ix] &
            ~data['brake_pressed'][ix] & (data['vego'][ix] >= 8))
  if domain == 'gas':
    domain_active = (gas > 0) & ~brake
    signal = np.where(domain_active, gas / 1000, 0.0)
  else:
    domain_active = brake & (gas == -30000)
    signal = np.where(domain_active, data['accel_command'][ix], 0.0)
  speed = data['vego'][ix]
  pitch = data['pitch'][ix]
  actual = data['aego'][ix]
  valid = active & domain_active & np.isfinite(actual) & np.isfinite(speed) & np.isfinite(pitch) & np.isfinite(signal)
  mask = continuous_mask(valid, data['gear'][ix], t)
  mask &= np.arange(len(t)) % 5 == 0
  context = np.column_stack((speed ** 2 / 1000, 9.81 * np.sin(pitch), np.ones(len(t))))
  return signal, context, actual, mask, float(np.median(np.diff(t)))


def inspect(routes, data, domain):
  candidates = [(delay, tau) for delay in (0., .1, .2, .4, .6) for tau in (0., .1, .25, .5, 1.)]
  prepared = [prepare(d, domain) for d in data]
  print(domain, 'eligible 10-Hz rows', {r: int(p[3].sum()) for r, p in zip(routes, prepared, strict=True)})
  if any(p[3].sum() < 10 for p in prepared):
    print('Insufficient selected exposure for this multi-route fit; no model selected.')
    return
  matrices = [[np.column_stack((delayed_response(p[0], p[4], delay, tau), p[1]))[p[3]]
               for p in prepared] for delay, tau in candidates]
  targets = [p[2][p[3]] for p in prepared]
  for held, route in enumerate(routes):
    train = [i for i in range(len(routes)) if i != held]
    fits = [fit_balanced([xs[i] for i in train], [targets[i] for i in train]) for xs in matrices]
    best = min(range(len(fits)), key=lambda i: fits[i][1])
    error = matrices[best][held] @ fits[best][0] - targets[held]
    static_error = matrices[0][held] @ fits[0][0] - targets[held]
    print(route, 'delay/tau', candidates[best], 'coefficients input/speed2/grade/bias', np.round(fits[best][0], 4),
          'RMSE dynamic/static', round(float(np.sqrt(np.mean(error ** 2))), 4),
          round(float(np.sqrt(np.mean(static_error ** 2))), 4), 'bias', round(float(np.mean(error)), 4))


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('routes', nargs='+')
  parser.add_argument('--opendbc', required=True, help='Exact full nested revision required for every route')
  args = parser.parse_args()
  if len(set(args.routes)) < 2 or len(set(args.routes)) != len(args.routes):
    parser.error('Provide at least two distinct routes to separate training from held-out evaluation')
  ledger = {row['route']: row for row in map(json.loads, Path(__file__).with_name('log-validation-ledger.jsonl').read_text().splitlines())}
  for route in args.routes:
    if route not in ledger or ledger[route].get('opendbc_commit_full') != args.opendbc or route.startswith('00000005--'):
      parser.error(f'{route}: missing/mismatched nested provenance or excluded route')
  data = [load(route) for route in args.routes]
  for domain in ('gas', 'brake'):
    inspect(args.routes, data, domain)


if __name__ == '__main__':
  main()
