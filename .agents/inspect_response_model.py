#!/usr/bin/env python3
"""Screen gas/brake acceleration models with whole-route holdouts.

Observational prediction only: coefficients are not identified actuator gains and must not be
inverted into a controller. Settled fits exclude transitions. The optional brake-entry screen
reuses the existing event detector and fits only a unit-gain delay/filter, not a brake map.
Uses cached ZOH CAN, not independently checked sent-frame freshness.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from extract import load, _segments
from tuning_metrics import brake_entry_tracking_profile, causal_lpf

JOINT_DYNAMICS = [(g, b) for g in ((0., 0.), (.1, .25), (.5, 0.), (.2, .5))
                  for b in ((0., 0.), (.3, .1), (.35, .2), (.05, .3), (.5, 0.))]


def latest_response_state(data, state_t, values):
  """Hold last published speed/acceleration/pedals; never interpolate a future carState."""
  state_t, values = np.asarray(state_t), np.asarray(values)
  grid = data['t'] + data['t0']
  if not len(state_t) or np.any(np.diff(state_t) < 0):
    raise ValueError('carState timestamps must be nonempty and chronological')
  ix = np.searchsorted(state_t, grid, side='right') - 1
  safe_ix = np.maximum(ix, 0)
  age = grid - state_t[safe_ix]
  out = data.copy()
  for column, key in enumerate(('vego', 'aego', 'gas_pressed', 'brake_pressed')):
    held = values[safe_ix, column]
    out[key] = held > .5 if column >= 2 else np.where(ix >= 0, held, np.nan)
  out['response_state_fresh'] = (ix >= 0) & (age >= 0.) & (age < .04)
  return out


def load_forecast_data(route):
  from openpilot.tools.lib.logreader import LogReader
  data = load(route)
  _, paths = _segments(route)
  states = sorted(([m.logMonoTime / 1e9, m.carState.vEgo, m.carState.aEgo,
                    m.carState.gasPressed, m.carState.brakePressed]
                   for m in LogReader(paths) if m.which() == 'carState'), key=lambda row: row[0])
  states = np.asarray(states, dtype=float).reshape(-1, 5)
  return latest_response_state(data, states[:, 0], states[:, 1:])


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


def brake_entry_events(data, min_coast_s=0.0):
  """Reuse brake-entry selection; retain initial response and uninterrupted coast history."""
  clean = data['active'] & data['pid'] & ~data['gas_pressed'] & ~data['brake_pressed']
  rows = brake_entry_tracking_profile(data['t'], data['aego'], data['accel_command'], data['brake_request'],
                                      data['gas_command'], clean, data['vego'], data['gear'],
                                      filter_tau=0., requested_accel=data['request'])
  t = data['t']
  events = []
  for row in rows:
    edge = row['time']
    index = int(np.searchsorted(t, edge))
    start = index
    while (start > 0 and clean[start - 1] and not data['brake_request'][start - 1] and
           data['gas_command'][start - 1] == -30000 and data['gear'][start - 1] == data['gear'][index] and
           0 < t[start] - t[start - 1] < .04):
      start -= 1
    coast_s = edge - t[start]
    pre = (t >= edge - .1) & (t < edge)
    post = (t >= edge) & (t <= edge + 1.0)
    interval = t[(t >= edge - .3) & (t <= edge + 1.05)]
    if (coast_s < min_coast_s or not pre.any() or np.any(np.diff(interval) >= .04) or
        np.any(np.diff(interval) <= 0)):
      continue
    initial = float(np.mean(data['aego'][pre]))
    request, actual = data['request'][post], data['aego'][post]
    if not (np.isfinite(initial) and np.all(np.isfinite(request)) and np.all(np.isfinite(actual))):
      continue
    events.append({'time': edge, 'speed': row['speed'], 'coast_s': coast_s,
                   't': t[post] - edge, 'request': request, 'actual': actual, 'initial': initial})
  return events


def entry_response(event, delay, tau):
  """Causal unit-gain hypothesis; never use the observed post-entry response as input."""
  t = np.asarray(event['t'])
  request = np.asarray(event['request'])
  output = np.full(len(t), event['initial'], dtype=float)
  for i, time in enumerate(t):
    if time < delay:
      continue
    target = request[max(0, np.searchsorted(t, time - delay, side='right') - 1)]
    if tau == 0:
      output[i] = target
    elif i:
      dt = t[i] - t[i - 1]
      output[i] = output[i - 1] + dt / (tau + dt) * (target - output[i - 1])
  return output


def select_entry_dynamics(training, candidates):
  """Select on training routes only, balancing routes and then events within each route."""
  nonempty = [events for events in training if events]
  if not nonempty:
    return None
  def loss(params):
    return np.mean([np.mean([np.mean((entry_response(event, *params) - event['actual']) ** 2)
                             for event in events]) for events in nonempty])
  return min(candidates, key=loss)


def inspect_brake_entries(train_routes, train_data, evaluation_routes, evaluation_data):
  candidates = [(delay, tau) for delay in np.arange(0., .81, .05) for tau in np.arange(0., .61, .05)]
  for min_coast in (0., .3, 1.):
    training = [brake_entry_events(d, min_coast) for d in train_data]
    selected = select_entry_dynamics(training, candidates)
    print('brake entries, minimum prior continuous coast', min_coast, 'training counts',
          dict(zip(train_routes, map(len, training), strict=True)), 'selected delay/tau', selected)
    if selected is None:
      continue
    evaluated = training + [brake_entry_events(d, min_coast) for d in evaluation_data]
    for i, (route, events) in enumerate(zip(train_routes + evaluation_routes, evaluated, strict=True)):
      if not events:
        print(route, 'no qualifying events')
        continue
      predicted_errors = [e['actual'] - entry_response(e, *selected) for e in events]
      request_errors = [e['actual'] - e['request'] for e in events]
      def rms(errors):
        return float(np.sqrt(np.mean([np.mean(x ** 2) for x in errors])))
      late_error = np.mean([np.mean(error[e['t'] >= .7]) for e, error in zip(events, predicted_errors, strict=True)])
      print(route, 'training' if i < len(training) else 'held-out', 'events', len(events),
            'raw/model RMSE', round(rms(request_errors), 4), round(rms(predicted_errors), 4),
            'late actual-model', round(float(late_error), 4))


def prepare_joint(data):
  """Keep clean gas/brake/coast transitions; only driver/gear/gap history breaks eligibility."""
  ix = np.arange(0, len(data['t']), 2)
  t = data['t'][ix]
  domain = np.where(data['brake_request'][ix], 2, np.where(data['gas_command'][ix] > -30000, 1, 0))
  gas = np.maximum(data['gas_command'][ix], 0.) / 1000.
  brake = np.where(domain == 2, data['accel_command'][ix], 0.)
  context = np.column_stack((data['vego'][ix] ** 2 / 1000, 9.81 * np.sin(data['pitch'][ix]), np.ones(len(t))))
  actual = data['aego'][ix]
  # Check history before decimating so a one-control-frame intervention is not skipped.
  valid = (data['active'] & data['pid'] & ~data['gas_pressed'] & ~data['brake_pressed'] &
           (data['vego'] >= 8) & np.isfinite(data['aego']) & np.isfinite(data['pitch']) &
           np.isfinite(data['vego']) & np.isfinite(data['gas_command']) & np.isfinite(data['accel_command']))
  valid &= data.get('response_state_fresh', True)
  eligible = continuous_mask(valid, data['gear'], data['t'])[ix]
  mask = eligible & (np.arange(len(t)) % 5 == 0)
  age = np.zeros(len(t))
  last = 0
  for i in range(1, len(t)):
    if domain[i] != domain[i - 1]:
      last = i
    age[i] = t[i] - t[last]
  return {'gas': gas, 'brake': brake, 'context': context, 'actual': actual, 'domain': domain,
          'age': age, 'mask': mask, 'eligible': eligible, 't': t, 'dt': float(np.median(np.diff(t)))}


def joint_matrix(prepared, gas_dynamics, brake_dynamics, carry=True):
  """Two causal actuator states; carry=False ablates residual effort outside its input domain."""
  gas = delayed_response(prepared['gas'], prepared['dt'], *gas_dynamics)
  brake = delayed_response(prepared['brake'], prepared['dt'], *brake_dynamics)
  if not carry:
    gas = np.where(prepared['domain'] == 1, gas, 0.)
    brake = np.where(prepared['domain'] == 2, brake, 0.)
  return np.column_stack((gas, brake, prepared['context']))[prepared['mask']]


def fit_joint_model(training, carry=True):
  targets = [d['actual'][d['mask']] for d in training]
  if not training or any(len(y) == 0 for y in targets):
    raise ValueError('Every training route needs selected exposure')
  fits = [fit_balanced([joint_matrix(d, *p, carry) for d in training], targets) for p in JOINT_DYNAMICS]
  best = min(range(len(fits)), key=lambda i: fits[i][1])
  return JOINT_DYNAMICS[best], fits[best][0]


def inspect_joint(train_routes, train_data, evaluation_routes, evaluation_data):
  """Prediction/ablation only; free fitted coefficients are not calibrated inverse gains."""
  data = [prepare_joint(d) for d in train_data + evaluation_data]
  targets = [d['actual'][d['mask']] for d in data[:len(train_data)]]
  if any(len(y) == 0 for y in targets):
    print('No joint fit: at least one training route has no selected exposure.')
    return
  for carry in (True, False):
    dynamics, coef = fit_joint_model(data[:len(train_data)], carry)
    print('joint carry', carry, 'gas delay/tau; brake delay/tau', dynamics,
          'coefficients gas/brake/speed2/grade/bias', np.round(coef, 4))
    for i, (route, d) in enumerate(zip(train_routes + evaluation_routes, data, strict=True)):
      error = joint_matrix(d, *dynamics, carry) @ coef - d['actual'][d['mask']]
      domain, age = d['domain'][d['mask']], d['age'][d['mask']]
      for name, selected in (('all', np.ones(len(error), dtype=bool)), ('gas', domain == 1),
                             ('brake', domain == 2), ('coast', domain == 0),
                             ('brake-first-second', (domain == 2) & (age <= 1.)),
                             ('gas-first-second', (domain == 1) & (age <= 1.))):
        if selected.any():
          print(route, 'training' if i < len(train_data) else 'held-out', name, 'rows', int(selected.sum()),
                'prediction RMSE/bias', round(float(np.sqrt(np.mean(error[selected] ** 2))), 4),
                round(float(np.mean(error[selected])), 4))


def observe_residual(data, tau, reset_domain, cap=.5):
  """Bounded causal estimate, not an actuator command. Invalid history clears all state."""
  t, residual = data['t'], data['residual']
  estimate = np.zeros(len(t))
  segment, age = np.zeros(len(t), dtype=int), np.zeros(len(t))
  if not len(t):
    return estimate, segment, age
  if tau < 0. or cap <= 0.:
    raise ValueError('Residual filter needs nonnegative tau and a positive cap')
  value, since, epoch = 0., t[0], 0
  for i, time in enumerate(t):
    dt = time - t[i - 1] if i else data['dt']
    if not data['eligible'][i] or not np.isfinite(residual[i]) or not 0 < dt < .04:
      value, since, epoch = 0., time, epoch + 1
    else:
      if reset_domain and i and data['domain'][i] != data['domain'][i - 1]:
        value = 0.
      value += dt / (tau + dt) * (max(-cap, min(cap, residual[i])) - value)
    estimate[i], segment[i], age[i] = value, epoch, time - since
  return estimate, segment, age


def residual_forecast_errors(data, observer, horizon=.3):
  """Score future residuals only across uninterrupted eligible history, on identical cohorts.

  Future wire commands define the future residual label, not the estimator input. This does
  not predict future carControl or establish a prospective acceleration trajectory.
  """
  estimate, segment, age = observer
  t = data['t']
  if horizon <= 0.:
    raise ValueError('Forecast horizon must be positive')
  if not len(t):
    return np.array([], dtype=bool), np.array([]), np.array([]), np.array([], dtype=int)
  future = np.minimum(np.searchsorted(t, t + horizon, side='left'), len(t) - 1)
  elapsed = t[future] - t
  valid = (data['mask'] & data['eligible'] & data['eligible'][future] & (age >= .5) &
           (segment == segment[future]) & (elapsed >= horizon - .001) & (elapsed < horizon + .03))
  raw = data['residual'][future]
  valid &= np.isfinite(raw)
  return valid, raw - estimate, raw, future


def select_residual_filter(training, reset_domain):
  candidates = (.05, .1, .2, .5, 1., 2., 5.)
  def loss(tau):
    losses = []
    for d in training:
      valid, error, _, _ = residual_forecast_errors(d, observe_residual(d, tau, reset_domain))
      if not valid.any():
        return np.inf
      losses.append(np.mean(error[valid] ** 2))
    return np.mean(losses) if losses else np.inf
  losses = [loss(tau) for tau in candidates]
  return candidates[int(np.argmin(losses))] if np.any(np.isfinite(losses)) else None


def inspect_residuals(train_routes, train_data, evaluation_routes, evaluation_data):
  data = [prepare_joint(d) for d in train_data + evaluation_data]
  dynamics, coef = fit_joint_model(data[:len(train_data)])
  print('causal-state model', dynamics, 'coefficients', np.round(coef, 6))
  for d in data:
    dense = {**d, 'mask': np.ones(len(d['t']), dtype=bool)}
    d['residual'] = d['actual'] - joint_matrix(dense, *dynamics) @ coef
  for reset in (False, True):
    tau = select_residual_filter(data[:len(train_data)], reset)
    print('reset residual on domain change', reset, 'selected tau', tau, 'residual cap', .5)
    if tau is None:
      continue
    for horizon in (.1, .3, .6):
      for i, (route, d) in enumerate(zip(train_routes + evaluation_routes, data, strict=True)):
        valid, error, raw, future = residual_forecast_errors(d, observe_residual(d, tau, reset), horizon)
        for name, selected in (('all', valid), ('gas', valid & (d['domain'] == 1)),
                               ('brake', valid & (d['domain'] == 2)),
                               ('domain-changes-within-horizon', valid & (d['domain'] != d['domain'][future]))):
          if selected.any():
            rms = [float(np.sqrt(np.mean(e[selected] ** 2))) for e in (raw, error)]
            print(route, 'training' if i < len(train_data) else 'held-out', 'horizon', horizon,
                  name, 'rows', int(selected.sum()), 'zero/estimated residual RMS', np.round(rms, 4))


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('routes', nargs='+')
  parser.add_argument('--opendbc', required=True, help='Exact full nested revision required for every route')
  mode = parser.add_mutually_exclusive_group()
  mode.add_argument('--brake-entries', action='store_true', help='Screen entry dynamics instead of settled fits')
  mode.add_argument('--joint', action='store_true', help='Screen two actuator states including domain transitions')
  mode.add_argument('--residual-forecast', action='store_true', help='Forecast model residual with latest-published carState')
  parser.add_argument('--evaluation-routes', nargs='+', default=[], help='Held-out routes, never used for fitting')
  parser.add_argument('--evaluation-opendbc', help='Exact nested revision of held-out routes; audit source compatibility separately')
  args = parser.parse_args()
  if len(set(args.routes)) < 2 or len(set(args.routes)) != len(args.routes):
    parser.error('Provide at least two distinct routes to separate training from held-out evaluation')
  comparison_mode = args.brake_entries or args.joint or args.residual_forecast
  if args.evaluation_routes and (not comparison_mode or not args.evaluation_opendbc):
    parser.error('Evaluation routes require a comparison mode and --evaluation-opendbc; audit source compatibility separately')
  if len(set(args.routes + args.evaluation_routes)) != len(args.routes + args.evaluation_routes):
    parser.error('Training and evaluation routes must be distinct and nonduplicated')
  ledger = {row['route']: row for row in map(json.loads, Path(__file__).with_name('log-validation-ledger.jsonl').read_text().splitlines())}
  for routes, revision in ((args.routes, args.opendbc), (args.evaluation_routes, args.evaluation_opendbc)):
    for route in routes:
      if (route not in ledger or ledger[route].get('opendbc_commit_full') != revision or
          ledger[route].get('qlog_fallback') or route.startswith('00000005--')):
        parser.error(f'{route}: missing/mismatched nested provenance, qlog fallback, or excluded route')
  loader = load_forecast_data if args.residual_forecast else load
  data = [loader(route) for route in args.routes]
  if comparison_mode:
    screen = inspect_residuals if args.residual_forecast else inspect_brake_entries if args.brake_entries else inspect_joint
    screen(args.routes, data, args.evaluation_routes, [loader(r) for r in args.evaluation_routes])
    return
  for domain in ('gas', 'brake'):
    inspect(args.routes, data, domain)


if __name__ == '__main__':
  main()
