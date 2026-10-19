#!/usr/bin/env python3
"""Summarize recorded Odyssey distance, driver inputs and native ECON fuel use.

Fuel units remain uncalibrated unless --fuel-ticks-per-liter supplies an assumption.
Reports describe available logged coverage, not necessarily a complete drive. This is
passive analysis; it neither changes vehicle control nor writes learner parameters.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from extract import _segments, _source_signature, plan_to_control
from openpilot.tools.lib.logreader import LogReader
from tuning_metrics import sample_rate

MILE = 1609.344
GALLON = 3.785411784
STATE_GAP = .1
FUEL_GAP = .25


def decode(messages):
  """Keep native publications; CAN is ordered globally before checksum/counter parsing."""
  from opendbc.can import CANParser

  state, control, mode, buttons, can, lane_change = [], [], [], [], [], []
  for m in messages:
    t, kind = m.logMonoTime / 1e9, m.which()
    if kind == 'carState':
      s = m.carState
      state.append((t, s.vEgoRaw, s.canValid, s.gasPressed, s.brakePressed, s.steeringPressed, s.steeringTorque))
      if s.canValid and s.ecoModeValid:
        mode.append((t, s.ecoMode))
      buttons.extend((t, int(b.type.raw)) for b in s.buttonEvents if b.pressed)
    elif kind == 'modelV2':
      meta = m.modelV2.meta
      lane_change.append((t, int(meta.laneChangeState.raw), int(meta.laneChangeDirection.raw), m.valid))
    elif kind == 'carControl':
      control.append((t, m.carControl.latActive, m.carControl.longActive))
    elif kind == 'can':
      can.extend((m.logMonoTime, f.address, bytes(f.dat)) for f in m.can if f.src == 1 and f.address == 0x324)
  fuel = []
  parser = CANParser('honda_odyssey_5g_mmr_generated', [('CRUISE', 0)], 1)
  for now, address, data in sorted(can):
    if address in parser.update([(now, [(address, data, 1)])]):
      fuel.append((now / 1e9, parser.vl['CRUISE']['TRIP_FUEL_CONSUMED']))
  return {name: np.asarray(sorted(rows), dtype=float).reshape(-1, width)
          for name, rows, width in (('state', state, 7), ('control', control, 3), ('mode', mode, 2),
                                    ('buttons', buttons, 2), ('fuel', fuel, 2), ('lane_change', lane_change, 4))}


def confirmed_lane_changes(samples):
  """Observed starting/finishing phases confirm contiguous same-direction preparation.

  A blinker/preparation alone never qualifies. Invalid or missing model publications
  end coverage; no time padding extends the maneuver. Directions match DesireHelper.
  """
  windows = []
  preparation = active = None
  previous_t = previous_direction = None
  for t, phase, direction, valid in samples:
    gap = previous_t is not None and t - previous_t > STATE_GAP + 1e-9
    changed = previous_direction is not None and direction != previous_direction
    supported = bool(valid) and phase in (0, 1, 2, 3) and (direction in (1, 2) or phase == 0)
    if gap or changed or not supported:
      if active is not None:
        windows.append((active, t if supported and not gap else previous_t, previous_direction))
      preparation = active = None
    if supported:
      if phase == 1:  # preLaneChange
        if active is not None:
          windows.append((active, t, direction))
          active = None
        if preparation is None:
          preparation = t
      elif phase in (2, 3):  # laneChangeStarting / laneChangeFinishing
        if active is None:
          active = preparation if preparation is not None else t
        preparation = None
      else:
        if active is not None:
          windows.append((active, t, direction))
        preparation = active = None
    previous_t, previous_direction = t, direction
  if active is not None:
    windows.append((active, previous_t, previous_direction))
  return [w for w in windows if w[1] > w[0]]


def steering_for_lane_change(times, torque, windows):
  excluded = np.zeros(len(times), dtype=bool)
  for start, end, direction in windows:
    sign = 1 if direction == 1 else -1
    excluded |= (times >= start) & (times < end) & (torque * sign > 0)
  return excluded


def longest_distance(distance, eligible, breaks):
  longest = current = 0.
  for value, valid, interrupted in zip(distance, eligible, breaks, strict=True):
    if interrupted or not valid:
      current = 0.
    if valid:
      current += value
      longest = max(longest, current)
  return float(longest)


def summarize(data, fuel_ticks_per_liter=None, *, exclude_lane_change_steering=True):
  """Integrate supported native intervals; never infer a fuel wrap or driver-caused disengagement."""
  if fuel_ticks_per_liter is not None and (not np.isfinite(fuel_ticks_per_liter) or fuel_ticks_per_liter <= 0):
    raise ValueError('fuel ticks per liter must be finite and positive')
  state, control, mode, buttons, fuel = (data[k] for k in ('state', 'control', 'mode', 'buttons', 'fuel'))
  if len(state) < 2:
    raise ValueError('at least two carState samples are required')
  if sample_rate(state[:, 0]) < 50. or (len(control) >= 2 and sample_rate(control[:, 0]) < 50.):
    raise ValueError('input statistics require full-rate carState and carControl, not decimated logs')
  grid = np.unique(np.concatenate([v[:, 0] for v in data.values()]))
  t, dt = grid[:-1], np.diff(grid)

  def held(samples, column, gap):
    values = plan_to_control(t, samples[:, 0], samples[:, column])
    age = t - plan_to_control(t, samples[:, 0], samples[:, 0])
    return values, (age >= 0) & (age + dt <= gap + 1e-9)

  speed, state_fresh = held(state, 1, STATE_GAP)
  can_valid, _ = held(state, 2, STATE_GAP)
  valid = (state_fresh & (can_valid > .5) & np.isfinite(speed) & (speed >= 0) &
           (t >= state[0, 0]) & (grid[1:] <= state[-1, 0]))
  distance = np.where(valid, speed * dt / MILE, 0.)
  lat, control_fresh = held(control, 1, STATE_GAP)
  long, _ = held(control, 2, STATE_GAP)
  both = valid & control_fresh & (lat > .5) & (long > .5)
  maneuvers = confirmed_lane_changes(data.get('lane_change', np.empty((0, 4))))
  steering_torque, _ = held(state, 6, STATE_GAP)
  selected = maneuvers if exclude_lane_change_steering else []
  lane_steering = steering_for_lane_change(t, steering_torque, selected)
  native_lane_steering = steering_for_lane_change(state[:, 0], state[:, 6], selected)
  override = np.zeros(len(t), dtype=bool)
  inputs = {}
  for column, name in ((3, 'accelerator'), (4, 'brake'), (5, 'steering_override')):
    value, _ = held(state, column, STATE_GAP)
    override |= (value > .5) & (~lane_steering if column == 5 else True)
    raw_edges = np.flatnonzero((state[1:, column] > .5) & (state[:-1, column] <= .5)) + 1
    counted = (state[:, column] > .5) & (~native_lane_steering if column == 5 else True)
    edges = np.flatnonzero(counted[1:] & ~counted[:-1]) + 1
    times = state[edges, 0]
    prior = np.searchsorted(control[:, 0], times, side='right') - 1
    safe = np.maximum(prior, 0)
    assisted = ((prior >= 0) & (times - control[safe, 0] <= STATE_GAP) &
                (control[safe, 1] > .5) & (control[safe, 2] > .5)) if len(control) else np.zeros(len(times), bool)
    inputs[name] = {'recorded_rising_edges': int(len(raw_edges)),
                    'lane_change_edges_excluded': int(native_lane_steering[raw_edges].sum()) if column == 5 else 0,
                    'while_both_axes_active': int(assisted.sum())}
  clean = both & ~override
  button_breaks = np.isin(t, buttons[:, 0])
  button_indices = np.searchsorted(t, buttons[:, 0])
  assisted_buttons = int(np.sum(both[np.minimum(button_indices, len(t) - 1)] & (button_indices < len(t))))
  modes, mode_fresh = held(mode, 1, FUEL_GAP)
  modes = np.where(mode_fresh, modes, -1)
  mode_breaks = np.r_[False, modes[1:] != modes[:-1]]
  disengagements = int(np.sum(both[:-1] & ~both[1:] & valid[1:] & control_fresh[1:]))
  total, assisted = float(distance.sum()), float(distance[clean].sum())
  out = {
    'scope': 'Available recorded coverage; assistance requires both steering and longitudinal control active.',
    'recorded_miles': total,
    'lane_change_steering_excluded': exclude_lane_change_steering,
    'confirmed_lane_changes': len(maneuvers),
    'supported_seconds': float(dt[valid].sum()),
    'unsupported_seconds': float(dt[~valid].sum()),
    'assisted_miles_without_detected_override': assisted,
    'assisted_share_percent': 100. * assisted / total if total else None,
    'longest_without_detected_input_miles': longest_distance(distance, clean, button_breaks),
    'recorded_cruise_button_presses': int(len(buttons)),
    'cruise_button_presses_while_assisted': assisted_buttons,
    'driver_inputs': inputs,
    'both_axes_disengagements': disengagements,
    'definitions': {
      'inputs': ('Raw rising edges are retained. Counted steering filters lane-change inputs first; opposite or continuing inputs outside the maneuver count. '
                 'An input held at capture start is not a new raw event.'),
      'longest': 'Both axes active without counted pedal/steering override; button presses, disengagements and coverage gaps break the stretch.',
      'lane_changes': ('Exclude same-direction steering in a recorded starting/finishing maneuver and its contiguous confirmed preparation. '
                       'Canceled preparation, opposite steering and pedals count; mileage and fuel are retained.'),
      'disengagements': 'Observed loss of both-axis assistance with supported state/control; cause is not inferred.',
      'mileage': 'Integrates published vEgoRaw over supported intervals; no GPS or dashboard distance substitution.',
      'fuel': 'Checksum/counter-accepted CRUISE.TRIP_FUEL_CONSUMED increments; gaps and counter decreases are excluded, not unwrapped.',
      'comparison': 'Mode totals are descriptive. Route, speed, terrain, stops and following personality can differ.',
    },
    'fuel_ticks_per_liter_assumed': fuel_ticks_per_liter,
    'fuel_counter_decreases': int(np.sum(np.diff(fuel[:, 1]) < 0)),
    'excluded_fuel_intervals': 0,
    'modes': {},
  }
  matched_distance = dict.fromkeys(('Standard', 'ECON', 'unknown_or_mixed'), 0.)
  ticks = dict.fromkeys(matched_distance, 0.)
  cumulative_distance = np.r_[0., np.cumsum(distance)]
  cumulative_supported = np.r_[0., np.cumsum(np.where(valid, dt, 0.))]
  for (start, before), (end, after) in zip(fuel[:-1], fuel[1:], strict=True):
    a, b = np.searchsorted(grid, [start, end])
    delta = after - before
    if not 0 < end - start <= FUEL_GAP or delta < 0 or abs(cumulative_supported[b] - cumulative_supported[a] - (end - start)) > 1e-7:
      out['excluded_fuel_intervals'] += 1
      continue
    selected = modes[a:b]
    key = ('ECON' if selected[0] > .5 else 'Standard') if len(selected) and np.all(selected == selected[0]) and selected[0] >= 0 else 'unknown_or_mixed'
    matched_distance[key] += float(cumulative_distance[b] - cumulative_distance[a])
    ticks[key] += float(delta)
  for name, number in (('Standard', 0), ('ECON', 1), ('unknown_or_mixed', -1)):
    mask = valid & (modes == number)
    seconds = float(dt[mask].sum())
    miles = float(distance[mask].sum())
    liters = ticks[name] / fuel_ticks_per_liter if fuel_ticks_per_liter else None
    out['modes'][name] = {
      'seconds': seconds, 'miles': miles,
      'assisted_miles_without_detected_override': float(distance[mask & clean].sum()),
      'mean_mph_including_stops': miles * 3600 / seconds if seconds else None,
      'stationary_seconds': float(dt[mask & (speed == 0)].sum()),
      'fuel_matched_miles': matched_distance[name], 'fuel_counter_ticks': ticks[name],
      'estimated_liters': liters,
      'estimated_mpg': matched_distance[name] * GALLON / liters if liters else None,
    }
  out['native_mode_changes'] = int(np.sum(mode_breaks & (modes >= 0) & np.r_[False, modes[:-1] >= 0]))
  out['shareable_text'] = combined([out])['shareable_text']
  return out



def fuel_source_matches(child):
  """Qualify the recorded fuel message against this decoder's DBC."""
  source = 'opendbc/dbc/generator/honda/_honda_common.dbc'
  try:
    recorded = subprocess.check_output(['git', '-C', 'opendbc_repo', 'show', f'{child}:{source}'], stderr=subprocess.DEVNULL, text=True)
  except subprocess.CalledProcessError:
    return False
  current = Path('opendbc_repo', source).read_text()
  pattern = r'^BO_ 804 CRUISE:.*?(?=^BO_ |\Z)'
  a, b = (re.search(pattern, text, re.MULTILINE | re.DOTALL) for text in (recorded, current))
  return bool(a and b and a.group() == b.group())


def combined(reports):
  """Sum distances, never percentages; route boundaries never join uninterrupted stretches."""
  policies = {r.get('lane_change_steering_excluded', False) for r in reports}
  if len(policies) > 1:
    raise ValueError('cannot combine different lane-change input policies')
  exclusion = policies == {True}
  total = sum(r['recorded_miles'] for r in reports)
  assisted = sum(r['assisted_miles_without_detected_override'] for r in reports)
  longest = max((r['longest_without_detected_input_miles'] for r in reports), default=0.)
  percent = 100. * assisted / total if total else None
  note = ' Same-direction steering inputs during confirmed lane changes excluded.' if exclusion else ''
  return {'recordings': len(reports), 'recorded_miles': total,
          'lane_change_steering_excluded': exclusion,
          'confirmed_lane_changes': sum(r.get('confirmed_lane_changes', 0) for r in reports),
          'lane_change_steering_events_excluded': sum(r['driver_inputs']['steering_override'].get('lane_change_edges_excluded', 0) for r in reports),
          'assisted_miles_without_detected_override': assisted, 'assisted_share_percent': percent,
          'longest_without_detected_input_miles': longest,
          'shareable_text': (f'{assisted:.1f} supervised assisted miles out of {total:.1f} recorded miles ({percent:.1f}%). '
                             f'Longest stretch without a counted steering, pedal or cruise-button input: {longest:.1f} miles.{note}')
                            if total else 'No supported driving distance in these recordings.'}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('routes', nargs='+')
  parser.add_argument('--fuel-ticks-per-liter', type=float, help='assumed scale; all MPG remains labeled estimated')
  parser.add_argument('--output', type=Path, help='save private JSON report')
  args = parser.parse_args()
  from validate_log import _provenance
  reports = []
  for route in args.routes:
    full, paths = _segments(route)
    if any(r['route'] == full for r in reports):
      raise ValueError('duplicate route would count the same miles twice')
    before = _source_signature(paths)
    first = list(LogReader(paths[:1]))
    provenance = _provenance(first)
    if not any(m.which() == 'carParams' and m.carParams.carFingerprint == 'HONDA_ODYSSEY_5G_MMR' for m in first):
      raise ValueError('this fuel decoder is restricted to the Bosch Odyssey')
    if not fuel_source_matches(provenance['opendbc_commit_full']):
      raise ValueError('recorded fuel DBC could not be qualified against the decoder')
    report = summarize(decode(LogReader(paths)), args.fuel_ticks_per_liter)
    if not np.array_equal(before, _source_signature(paths)):
      raise RuntimeError('source logs changed during analysis')
    reports.append({'route': full, 'provenance': provenance,
                    'segments': [{'name': Path(path).parent.name, 'sha256': digest} for path, digest in before], **report})
  summary = combined(reports)
  text = json.dumps({'recordings': reports, 'combined': summary}, indent=2, allow_nan=False) + '\n'
  if args.output:
    args.output.write_text(text)
    print(summary['shareable_text'])
  else:
    print(text, end='')


if __name__ == '__main__':
  main()
