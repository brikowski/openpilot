#!/usr/bin/env python3
"""Compare Odyssey controller pitch with independent GNSS velocity-derived grade.

GNSS grade is an offline observational label, not a surveyed road grade or a
runtime Honda input. This tool does not predict the effect of changing gas or
brake commands. Keep private rlogs local.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from extract import _segments
from inspect_response_model import fit_balanced, load_forecast_data
from tuning_metrics import causal_lpf


def gps_velocity_grade(north, east, down):
  """NED down velocity is positive on descents; uphill grade is positive."""
  return float(np.arctan2(-down, np.hypot(north, east)))


def load_gps_grade(route):
  from openpilot.tools.lib.logreader import LogReader
  _, paths = _segments(route)
  records = []
  for message in LogReader(paths):
    if message.which() != 'gpsLocation':
      continue
    gps = message.gpsLocation
    if not gps.hasFix or len(gps.vNED) != 3:
      continue
    north, east, down = map(float, gps.vNED)
    speed = float(np.hypot(north, east))
    if (not np.all(np.isfinite((north, east, down, gps.verticalAccuracy))) or
        speed < 8. or gps.verticalAccuracy > 5.):
      continue
    records.append((message.logMonoTime / 1e9, gps_velocity_grade(north, east, down), speed))
  return np.asarray(records, dtype=float).reshape(-1, 3)


def aligned_pitch_grade(data, gps):
  """Pair each GNSS observation with the latest earlier controller/state input."""
  if not len(gps):
    return np.empty((0, 3)), np.empty(0), np.empty((0, 3))
  time = gps[:, 0] - data['t0']
  ix = np.searchsorted(data['t'], time, side='right') - 1
  safe_ix = np.clip(ix, 0, len(data['t']) - 1)
  age = time - data['t'][safe_ix]
  speed = data['vego'][safe_ix]
  aego = data['aego'][safe_ix]
  pitch = data['pitch'][safe_ix]
  valid = ((ix >= 0) & (age >= 0.) & (age < .03) &
           data['active'][safe_ix] & data['response_state_fresh'][safe_ix] &
           ~data['gas_pressed'][safe_ix] & ~data['brake_pressed'][safe_ix] &
           (np.abs(gps[:, 2] - speed) < 2.) &
           np.isfinite(pitch) & np.isfinite(aego) & np.isfinite(speed))
  context = np.column_stack((np.ones(valid.sum()), aego[valid], speed[valid] ** 2 / 1000.))
  bias = pitch[valid] - gps[valid, 1]
  observations = np.column_stack((time[valid], pitch[valid], gps[valid, 1]))
  return context, bias, observations


def leave_one_route_out(groups, held, width):
  """Fit offset terms only on the other routes, with equal route weight."""
  train = [i for i in range(len(groups)) if i != held]
  coef, _ = fit_balanced([groups[i][0][:, :width] for i in train], [groups[i][1] for i in train])
  x, y, _ = groups[held]
  return coef, x[:, :width] @ coef - y


def gas_lookup_delta(request, pitch, offset):
  """Hypothetical feedforward-only count change through the actual Honda lookup."""
  from opendbc.car.honda.carcontroller import odyssey_uphill_gas_accel
  from opendbc.car.honda.values import CarControllerParams
  bp, values = CarControllerParams.BOSCH_GAS_LOOKUP_BP, CarControllerParams.BOSCH_GAS_LOOKUP_V
  original = odyssey_uphill_gas_accel(request, pitch)
  adjusted = odyssey_uphill_gas_accel(request, pitch - offset)
  return float(np.interp(adjusted, bp, values) - np.interp(original, bp, values))


def positive_gas_sensitivity(data, gps, offset):
  """Screen a hypothetical pitch offset on frozen positive-gas inputs only."""
  t = data['t']
  gps_t = gps[:, 0] - data['t0']
  gi = np.searchsorted(gps_t, t, side='right') - 1
  safe_gi = np.clip(gi, 0, len(gps_t) - 1)
  gps_age = t - gps_t[safe_gi]
  filtered = causal_lpf(data['pitch'], float(np.median(np.diff(t))), .5)
  future = np.searchsorted(t, t + .6, side='left')
  valid_future = future < len(t)
  future = np.clip(future, 0, len(t) - 1)
  valid = (data['active'] & data['pid'] & ~data['gas_pressed'] & ~data['brake_pressed'] &
           data['response_state_fresh'] & (data['gas_command'] > 0) & ~data['brake_request'] &
           (data['vego'] >= 8.) & (.1 < data['request']) & (data['request'] < .9) &
           (data['pitch'] > .015) & (filtered > .015) &
           (gi >= 0) & (gps_age >= 0.) & (gps_age < 1.5) &
           (np.abs(gps[safe_gi, 1]) < .01) & (np.abs(gps[safe_gi, 2] - data['vego']) < 2.) &
           valid_future & (t[future] - t >= .6) & (t[future] - t < .63) &
           data['active'][future] & (data['gas_command'][future] > 0) &
           (data['gear'] == data['gear'][future]) &
           (np.abs(data['request'][future] - data['request']) < .1) &
           np.isfinite(data['aego'][future]))
  ix = np.flatnonzero(valid & (np.arange(len(t)) % 10 == 0))
  changes = np.array([gas_lookup_delta(float(data['request'][i]), float(filtered[i]), offset) for i in ix])
  errors = data['aego'][future[ix]] - data['request'][ix]
  spans = int(1 + np.sum(np.diff(t[ix]) > .15)) if len(ix) else 0
  return changes, errors, spans


def gps_coast_response(data, gps, max_age=.5):
  """Descriptive settled-domain response, not a fresh brake-entry counterfactual."""
  t = data['t']
  gps_t = gps[:, 0] - data['t0']
  gi = np.searchsorted(gps_t, t, side='right') - 1
  safe_gi = np.clip(gi, 0, len(gps_t) - 1)
  age = t - gps_t[safe_gi]
  grade = gps[safe_gi, 1]
  prior = np.searchsorted(t, t - .1)
  future = np.searchsorted(t, t + .4)
  valid_future = future < len(t)
  future = np.clip(future, 0, len(t) - 1)
  gas = data['gas_command'] > -30000
  domains = {'coast': ~gas & ~data['brake_request'], 'brake': data['brake_request'] & ~gas}
  clean = (data['active'] & data['pid'] & ~data['gas_pressed'] & ~data['brake_pressed'] &
           data['response_state_fresh'])
  base = (clean & (data['vego'] >= 15.) & (data['vego'] < 30.) &
          (data['request'] >= -.2) & (data['request'] < -.1) &
          (gi >= 0) & (age >= 0.) & (age < max_age) &
          (np.abs(gps[safe_gi, 2] - data['vego']) < 2.) &
          valid_future & (t[future] - t >= .4) & (t[future] - t < .43) &
          (np.abs(data['request'][future] - data['request']) <= .1) &
          (data['gear'] == data['gear'][future]) & data['active'][future] &
          data['response_state_fresh'][future] & np.isfinite(data['aego'][future]))
  result = []
  for terrain, terrain_mask in (('downhill', grade < -.01), ('near_level', np.abs(grade) < .01),
                                ('uphill', grade > .01)):
    for domain_name, domain_mask in domains.items():
      ix = np.flatnonzero(base & terrain_mask & domain_mask & (np.arange(len(t)) % 10 == 0))
      ix = np.array([i for i in ix if (np.all(domain_mask[prior[i]:future[i] + 1] & clean[prior[i]:future[i] + 1]) and
                                            np.all(data['gear'][prior[i]:future[i] + 1] == data['gear'][i]) and
                                            np.max(np.abs(data['request'][prior[i]:future[i] + 1] - data['request'][i])) <= .1)],
                    dtype=int)
      if not len(ix):
        continue
      current_error = data['aego'][ix] - data['request'][ix]
      future_error = data['aego'][future[ix]] - data['request'][ix]
      episodes = np.split(np.arange(len(ix)), np.flatnonzero(np.diff(t[ix]) > .15) + 1)
      episode_errors = np.array([np.median(future_error[span]) for span in episodes])
      result.append({'terrain': terrain, 'domain': domain_name, 'rows': len(ix), 'episodes': len(episodes),
                     'positive_episodes': int(np.sum(episode_errors > 0.)),
                     'median_request': float(np.median(data['request'][ix])),
                     'median_grade': float(np.median(grade[ix])),
                     'median_future_error': float(np.median(future_error)),
                     'current_over_future_over': int(np.sum((current_error > .1) & (future_error > .1))),
                     'current_over_future_under': int(np.sum((current_error > .1) & (future_error < -.1)))})
  return result


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('routes', nargs='+')
  parser.add_argument('--opendbc', required=True, help='Full exact nested revision shared by all routes')
  parser.add_argument('--feedforward-offset', type=float, help='Optional frozen-input pitch-offset sensitivity, in radians')
  parser.add_argument('--coast-response', action='store_true', help='GPS-grade-conditioned stable coast/brake response screen')
  parser.add_argument('--coast-gps-max-age', type=float, default=.5, help='Maximum held GPS age for --coast-response (seconds)')
  args = parser.parse_args()
  if len(args.routes) < 3 or len(set(args.routes)) != len(args.routes):
    parser.error('Provide at least three distinct routes for leave-one-route-out validation')
  if args.feedforward_offset is not None and not 0. < args.feedforward_offset < .1:
    parser.error('Feedforward offset must be between zero and 0.1 radians')
  if not 0. < args.coast_gps_max_age <= 2.:
    parser.error('Coast GPS maximum age must be within (0, 2] seconds')
  ledger_path = Path(__file__).with_name('log-validation-ledger.jsonl')
  ledger = {row['route']: row for row in map(json.loads, ledger_path.read_text().splitlines())}
  groups = []
  for route in args.routes:
    row = ledger.get(route)
    if (row is None or row.get('opendbc_commit_full') != args.opendbc or row.get('qlog_fallback') or
        route.startswith('00000005--')):
      parser.error(f'{route}: missing/mismatched full-rate nested provenance')
    data = load_forecast_data(route)
    gps = load_gps_grade(route)
    group = aligned_pitch_grade(data, gps)
    if len(group[1]) < 10:
      parser.error(f'{route}: fewer than ten qualifying independent GNSS samples')
    groups.append(group)
    print(route, 'GPS rows', len(group[1]), 'pitch/GNSS-grade/offset medians',
          *(round(float(np.median(v)), 4) for v in (group[2][:, 1], group[2][:, 2], group[1])))
    if args.feedforward_offset is not None:
      changes, errors, spans = positive_gas_sensitivity(data, gps, args.feedforward_offset)
      print(route, 'frozen feedforward rows/spans', len(changes), spans,
            'median count change', round(float(np.median(changes)), 1) if len(changes) else None,
            'future over/under/middle', int(np.sum(errors > .1)), int(np.sum(errors < -.1)),
            int(np.sum(np.abs(errors) <= .1)))
    if args.coast_response:
      for row in gps_coast_response(data, gps, max_age=args.coast_gps_max_age):
        print(route, 'GPS coast response', row)
  for width, name in ((1, 'constant'), (2, 'acceleration'), (3, 'acceleration+speed2')):
    for held, route in enumerate(args.routes):
      coef, error = leave_one_route_out(groups, held, width)
      print(name, route, 'training-only coefficients', np.round(coef, 5),
            'held-out RMSE/median/p90abs',
            *(round(float(v), 4) for v in (np.sqrt(np.mean(error ** 2)), np.median(error),
                                           np.percentile(np.abs(error), 90))))


if __name__ == '__main__':
  main()
