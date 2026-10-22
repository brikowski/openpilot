#!/usr/bin/env python3
"""Assess Odyssey steering authority from native rlogs, without changing vehicle control.

validate_log saves per-route reports automatically. Compare recorded configurations with:
  compare_lateral_response.py CANDIDATE_REPORT ... --baseline STOCK_REPORT ... --output REPORT

Matched turns are observational. A feedback-selected boost cannot identify the effect of a
fixed ceiling. Missing overlap is inconclusive; CAN agreement does not prove EPS acceptance.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

STOCK_CAP = 2560
VERSION = 1
TOOL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MATCH_LIMITS = {'speed': 1.5, 'demand': .20, 'roll': .01, 'demand_span': .20, 'demand_trend': .25}


def can_schema_verified(child):
  """Check the exact pinned source before interpreting manually decoded steering bits."""
  if not child or not re.fullmatch('[0-9a-f]{40}', child):
    return False
  result = subprocess.run(['git', '-C', 'opendbc_repo', 'show',
                           child+':opendbc/dbc/generator/honda/_bosch_2018.dbc'], capture_output=True, text=True)
  text = ' '.join(result.stdout.split())
  return result.returncode == 0 and all(part in text for part in (
    'BO_ 228 STEERING_CONTROL: 5 ', 'SG_ STEER_TORQUE : 7|16@0- (1,0)',
    'SG_ STEER_TORQUE_REQUEST : 23|1@0+ (1,0)', 'SG_ CHECKSUM : 35|4@0+ (1,0)'))


def held(rows, times, max_age):
  """Hold prior publications only; absent or stale streams remain explicitly unsupported."""
  rows, times = np.asarray(rows), np.asarray(times)
  if not len(rows):
    return np.full((len(times), rows.shape[1]), np.nan), np.zeros(len(times), dtype=bool)
  ix = np.searchsorted(rows[:, 0], times, side='right') - 1
  values = rows[np.maximum(ix, 0)].copy()
  age = times - values[:, 0]
  valid = (ix >= 0) & (age >= 0) & (age <= max_age)
  values[~valid] = np.nan
  return values, valid


def history_supported(rows, times, lookback, limit):
  """Include the value held at the left boundary, faults and gaps throughout the window."""
  out = np.zeros(len(times), dtype=bool)
  for i, (t, span) in enumerate(zip(times, np.broadcast_to(lookback, len(times)), strict=True)):
    a = np.searchsorted(rows[:, 0], t-span, side='right') - 1
    b = np.searchsorted(rows[:, 0], t, side='right')
    if a < 0 or b <= a:
      continue
    window = rows[a:b]
    out[i] = (t-span-window[0, 0] <= .04 and t-window[-1, 0] <= .04 and
              np.max(np.diff(window[:, 0]), initial=0) <= .04 and
              np.all(window[:, 2:6] == [0, 0, 0, 1]) and
              np.all(np.isfinite(window[:, 6])) and np.max(abs(window[:, 6])) <= limit)
  return out


def native_streams(messages):
  """Retain independently timed commands, physical yaw, state, and published calibration.

  Scope is the Bosch Odyssey with Alpha Long's direct bus-1 steering. Wire columns are
  t/count/request/staged-carControl-torque/active. No motor-magnitude-to-force conversion.
  """
  from openpilot.selfdrive.locationd.helpers import Pose, PoseCalibrator
  from opendbc.car.honda.hondacan import honda_checksum

  widths = {'state': 9, 'control': 7, 'wire': 5, 'output': 3, 'pose': 5, 'parameters': 3, 'model': 2, 'delay': 3, 'torque': 4, 'mode': 2}
  data = {k: [] for k in widths}
  calibrator = PoseCalibrator()
  latest = staged = None
  supported = False
  bad_packets = 0
  for m in sorted(messages, key=lambda x: x.logMonoTime):
    kind, t = m.which(), m.logMonoTime / 1e9
    if kind == 'carParams':
      supported = m.carParams.carFingerprint == 'HONDA_ODYSSEY_5G_MMR' and m.carParams.openpilotLongitudinalControl
      if not supported:
        raise ValueError('steering assessment requires Odyssey Alpha Long direct steering')
    elif kind == 'carControl':
      latest = (m.carControl.actuators.torque, m.carControl.latActive)
    elif kind == 'carState':
      staged = latest
      s = m.carState
      data['state'].append([t, s.vEgo, s.steeringPressed, s.steerFaultTemporary, s.steerFaultPermanent,
                            s.canValid and m.valid, s.steeringTorque, s.ecoMode, s.ecoModeValid])
      # ecoModeValid is a new-packet flag, not continuous validity between updates.
      if s.ecoModeValid and s.canValid and m.valid:
        data['mode'].append([t, s.ecoMode])
    elif kind == 'controlsState' and m.controlsState.lateralControlState.which() == 'torqueState':
      s = m.controlsState.lateralControlState.torqueState
      data['control'].append([t, s.active and m.valid, s.desiredLateralAccel, s.actualLateralAccel,
                              s.output, s.saturated, s.p+s.i+s.f])
    elif kind == 'sendcan':
      for f in m.sendcan:
        if f.address != 0xe4 or f.src != 1:
          continue
        b = bytes(f.dat)
        if len(b) != 5 or honda_checksum(f.address, None, b) != b[-1] & 15:
          bad_packets += 1
          continue
        data['wire'].append([t, int.from_bytes(b[:2], 'big', signed=True), (b[2] >> 7) & 1,
                             *(staged if staged is not None else (np.nan, False))])
    elif kind == 'carOutput':
      a = m.carOutput.actuatorsOutput
      data['output'].append([t, a.torqueOutputCan, a.torque])
    elif kind == 'extrinsicsCalibration':
      calibrator.feed_extrinsics_calibration(m.extrinsicsCalibration)
    elif kind == 'deviceMotion':
      s = m.deviceMotion
      p = calibrator.build_calibrated_pose(Pose.from_device_motion(s))
      valid = (m.valid and calibrator.calib_valid and s.angularVelocityDevice.valid and
               s.orientationNED.valid and s.inputsOK and s.sensorsOK and s.posenetOK)
      data['pose'].append([s.timestamp / 1e9, p.angular_velocity.yaw, p.angular_velocity.yaw_std, valid, t])
    elif kind == 'vehicleParameters':
      s = m.vehicleParameters
      data['parameters'].append([t, s.roll, m.valid and s.valid])
    elif kind == 'modelV2':
      data['model'].append([t, m.modelV2.meta.laneChangeState.raw if m.valid else np.nan])
    elif kind == 'lateralDelay':
      data['delay'].append([t, m.lateralDelay.lateralDelay, m.valid])
    elif kind == 'lateralTorqueParameters':
      s = m.lateralTorqueParameters
      data['torque'].append([t, s.latAccelFactorFiltered, s.latAccelOffsetFiltered, s.frictionCoefficientFiltered])
  if not supported:
    raise ValueError('missing supported carParams')
  arrays = {k: np.asarray(v, dtype=float).reshape(-1, widths[k]) for k, v in data.items()}
  for k, a in arrays.items():
    arrays[k] = a[np.argsort(a[:, 0], kind='stable')]
  return arrays, bad_packets


def output_agreement(wire, output):
  """Pair each TX with its following carOutput, without reusing an output publication."""
  if not len(output):
    return np.zeros(len(wire), dtype=bool)
  ix = np.searchsorted(output[:, 0], wire[:, 0], side='left')
  valid = ix < len(output)
  ix = np.minimum(ix, len(output)-1)
  valid &= (output[ix, 0]-wire[:, 0] <= .04) & (output[ix, 1] == wire[:, 1])
  # The last TX before a publication owns it. Earlier batched TXs are not extra confirmations.
  valid[:-1] &= ix[:-1] != ix[1:]
  return valid


def authority_blocks(d, *, width, driver_limit, cap=STOCK_CAP):
  """Disjoint windows with their turn identity, exclusions, uncertainty and aftermath.

  desiredLateralAccel is already the controller's delayed target. Hold it at physical pose
  timestamps; require the issued authority to cover the measured actuator-delay lead-in too.
  """
  pose, state, wire = d['pose'], d['state'], d['wire']
  if not len(pose) or not len(state) or not len(wire):
    return [], {'missing_native_streams': True}
  t = pose[:, 0]
  s, sv = held(state, t, .04)
  c, cv = held(d['control'], t, .04)
  w, wv = held(wire, t, .04)
  p, pv = held(d['parameters'], t, 2.5)
  lane, lv = held(d['model'], t, .15)
  mode, mv = held(d['mode'], t, .06)
  delay, dv = held(d['delay'], t, 2.5)
  tq, _ = held(d['torque'], t, 2.5)
  good_output = output_agreement(wire, d['output'])
  fidelity, fv = held(np.c_[wire[:, 0], good_output], t, .04)
  driver_ok = history_supported(state, t, np.maximum(.5, delay[:, 1]), driver_limit)
  body, sigma = s[:, 1]*pose[:, 1], s[:, 1]*pose[:, 2]
  desired = c[:, 2]
  direction = np.sign(desired)
  finite = np.isfinite(np.c_[body, sigma, desired, c[:, 3], p[:, 1], w[:, 1], w[:, 3]]).all(axis=1) & (sigma >= 0)
  checks = {
    'fresh_state_control_wire': sv & cv & wv & fv,
    'valid_body_parameters_delay': (pose[:, 3] > .5) & pv & (p[:, 2] > .5) & dv & (delay[:, 2] > .5) &
                                    (delay[:, 1] >= 0) & (delay[:, 1] <= 1),
    'active_healthy': (c[:, 1] > .5) & (w[:, 2] > .5) & (w[:, 4] > .5) &
                      (s[:, 5] > .5) & np.all(s[:, 2:5] == 0, axis=1),
    'driver_history': driver_ok,
    'known_mode_no_lane_change': mv & lv & (lane[:, 1] == 0),
    'wire_output_agreement': fidelity[:, 1] > .5,
    'finite_turn': finite & (s[:, 1] > 0) & (abs(desired) > 0) & (np.sign(w[:, 1]) == direction),
  }
  healthy = np.logical_and.reduce(list(checks.values()))
  active_turn = cv & (c[:, 1] > .5) & np.isfinite(desired) & (abs(desired) > 0)
  # Low-authority parts of a bend remain in the same cluster. Windows on that bend cannot
  # become independent repeats merely by having different driver/authority eligibility.
  starts = active_turn & (~np.r_[False, active_turn[:-1]] | np.r_[True, np.diff(t) > .12] |
                          np.r_[True, direction[1:] != direction[:-1]])
  turns = np.cumsum(starts)
  t0 = d['control'][0, 0] if len(d['control']) else t[0]
  ids = np.floor((t-t0)/width).astype(int)
  blocks = []
  rejected = Counter()
  for block in np.unique(ids[active_turn]):
    ix = np.flatnonzero(ids == block)
    if len(ix) < max(3, int(width*15)) or t[ix[-1]]-t[ix[0]] < width*.7 or np.max(np.diff(t[ix])) > .12:
      rejected['body_window_gap'] += 1
      continue
    failed = [name for name, mask in checks.items() if not np.all(mask[ix])]
    if failed:
      rejected.update(failed)
      continue
    if len(np.unique(turns[ix])) != 1 or len(np.unique(mode[ix, 1])) != 1:
      rejected['turn_or_mode_transition'] += 1
      continue
    magnitude = abs(w[ix, 1])
    authority = ('extra' if np.all(magnitude > cap) else 'stock_limit' if np.all(abs(magnitude-cap) <= 1)
                 else 'ordinary' if np.all(magnitude < cap-1) else 'mixed')
    if authority == 'mixed':
      rejected['not_sustained_reference_or_extra'] += 1
      continue
    # Inspect commands already issued before physical response; never choose a best-fit lag.
    a = np.searchsorted(wire[:, 0], t[ix[0]]-np.max(delay[ix, 1]), side='right')-1
    b = np.searchsorted(wire[:, 0], t[ix[-1]], side='right')
    prior = wire[max(a, 0):b]
    settled = (a >= 0 and len(prior) > 0 and np.max(np.diff(prior[:, 0]), initial=0) <= .04 and
               np.all(prior[:, 2] > .5) and np.all(np.sign(prior[:, 1]) == direction[ix[0]]))
    if authority == 'extra':
      settled &= bool(np.all(abs(prior[:, 1]) > cap))
    elif authority == 'stock_limit':
      settled &= bool(np.all(abs(abs(prior[:, 1])-cap) <= 1))
    else:
      settled &= bool(np.all(abs(prior[:, 1]) < cap-1))
    if not settled:
      rejected['authority_not_settled'] += 1
      continue
    signed = direction[ix]*(desired[ix]-body[ix])
    controller_error = direction[ix]*(desired[ix]-c[ix, 3])
    aftermath = state[(state[:, 0] >= t[ix[-1]]) & (state[:, 0] <= t[ix[-1]]+1)]
    aftermath_supported = (len(aftermath) > 1 and aftermath[-1, 0]-t[ix[-1]] >= .9 and
                           np.max(np.diff(aftermath[:, 0])) <= .04)
    blocks.append({'turn': int(turns[ix[0]]), 'start': float(t[ix[0]]-t0), 'width': width, 'driver_limit': driver_limit,
      'authority': authority, 'speed': float(np.median(s[ix, 1])), 'demand': float(np.median(abs(desired[ix]))),
      'roll': float(np.median(p[ix, 1])), 'demand_span': float(np.ptp(desired[ix])),
      'demand_trend': float(direction[ix[0]]*(desired[ix[-1]]-desired[ix[0]])/(t[ix[-1]]-t[ix[0]])),
      'direction': int(direction[ix[0]]), 'econ': bool(mode[ix[0], 1]), 'counts': float(np.median(magnitude)),
      'request_torque': float(np.median(w[ix, 3])), 'controller_output': float(np.median(c[ix, 4])),
      'body_under': float(np.median(signed)), 'body_mae': float(np.mean(abs(signed))),
      'controller_under': float(np.median(controller_error)), 'controller_mae': float(np.mean(abs(controller_error))),
      'body_sigma': float(np.median(sigma[ix])),
      'torque_factor': float(np.median(tq[ix, 1])) if np.isfinite(tq[ix, 1]).all() else None,
      'friction': float(np.median(tq[ix, 3])) if np.isfinite(tq[ix, 3]).all() else None,
      'following_driver_or_fault': bool(np.any(aftermath[:, 2:5] > .5)) if aftermath_supported else None})
  coverage = {'poses': len(t), 'eligible_poses': int(healthy.sum()), 'rejected_windows': dict(rejected),
                  'blocks': len(blocks), 'turns': len({b['turn'] for b in blocks}), 'by_authority': dict(Counter(b['authority'] for b in blocks)),
                  'invalid_pose_counts': {name: int(np.sum(~mask)) for name, mask in checks.items()}}
  return blocks, coverage


def route_report(messages, route, provenance):
  d, bad_packets = native_streams(messages)
  blocks, exposure = [], []
  for width in (.5, 1.):
    for driver in (300, 1200):
      rows, coverage = authority_blocks(d, width=width, driver_limit=driver)
      blocks.extend(rows)
      exposure.append(dict(width=width, driver_limit=driver, **coverage))
  wire = d['wire']
  active = wire[:, 2] > .5
  provenance = dict(provenance)
  if any(m.initData.gitCommit != provenance.get('git_commit_full') or m.initData.dirty
         for m in messages if m.which() == 'initData'):
    provenance['provenance_exact'] = False
  provenance = dict(provenance, steering_dbc_verified=can_schema_verified(provenance.get('opendbc_commit_full')))
  return {'version': VERSION, 'tool_sha256': TOOL_SHA256,
    'route': route, 'provenance': provenance, 'stock_reference': STOCK_CAP,
    'wire': {'frames': len(wire), 'extra_frames': int(np.sum(active & (abs(wire[:, 1]) > STOCK_CAP))),
              'output_mismatches': int(np.sum(~output_agreement(wire, d['output']))), 'bad_packets': bad_packets},
    'faults_or_overrides': int(np.sum(np.any(d['state'][:, 2:5] > .5, axis=1))),
    'exposure': exposure, 'blocks': blocks,
    'scope': 'Physical motion and controller tracking; TX/carOutput agreement is not EPS acceptance. '
          'Learned calibration is reported as part of the configuration, not matched away. '
          'Diagnostic thresholds select events; they do not authorize tuning.'}


def match_turns(candidate, baseline, scale):
  """Unique whole-turn donors; never count multiple windows of a curve as repeats."""
  candidates = []
  for i, a in enumerate(candidate):
    for j, b in enumerate(baseline):
      if a['direction'] != b['direction'] or a['econ'] != b['econ']:
        continue
      differences = [abs(a[k]-b[k])/(v*scale) for k, v in MATCH_LIMITS.items()]
      if max(differences) <= 1:
        candidates.append((sum(x*x for x in differences), i, j))
  used_c, used_b, pairs = set(), set(), []
  for _, i, j in sorted(candidates):
    a, b = candidate[i], baseline[j]
    ca, cb = (a['route'], a['turn']), (b['route'], b['turn'])
    if ca in used_c or cb in used_b:
      continue
    used_c.add(ca)
    used_b.add(cb)
    pairs.append({'candidate': a, 'baseline': b, 'body_mae_change': a['body_mae']-b['body_mae'],
                      'controller_mae_change': a['controller_mae']-b['controller_mae'],
                      # Correlated fused-motion uncertainty is not reduced by sample count.
                      'body_sigma_sum': a['body_sigma']+b['body_sigma']})
  return pairs


def comparison(candidate, baseline):
  """Report sensitivity and the next evidence gap; make no automatic torque adjustment."""
  def identity(r):
    return (r['provenance'].get('git_commit_full'), r['provenance'].get('opendbc_commit_full'),
            r['provenance'].get('model_blob_full'))
  if any(len({identity(r) for r in group}) > 1 for group in (candidate, baseline)):
    raise ValueError('compare each exact revision pair separately; do not pool unresolved behavior revisions')
  if len({r['route'] for r in candidate+baseline}) != len(candidate+baseline):
    raise ValueError('duplicate or shared candidate/baseline route')
  if len({r.get('tool_sha256') for r in candidate+baseline}) > 1:
    raise ValueError('regenerate reports with the same assessment source before comparing')
  rows = []
  for exposure in ('limit', 'ordinary'):
    for width in (.5, 1.):
      for driver in (300, 1200):
        a = [dict(x, route=r['route']) for r in candidate for x in r['blocks']
             if x['width'] == width and x['driver_limit'] == driver and
             x['authority'] == ('extra' if exposure == 'limit' else 'ordinary')]
        b = [dict(x, route=r['route']) for r in baseline for x in r['blocks']
             if x['width'] == width and x['driver_limit'] == driver and
             x['authority'] == ('stock_limit' if exposure == 'limit' else 'ordinary')]
        for scale in (.5, 1., 1.5):
          pairs = match_turns(a, b, scale)
          rows.append({'exposure': exposure, 'width': width, 'driver_limit': driver, 'tolerance_scale': scale,
                       'candidate_windows': len(a), 'baseline_windows': len(b), 'pairs': pairs,
                       'body_mae_change': float(np.median([p['body_mae_change'] for p in pairs])) if pairs else None})
  primary = next(r for r in rows if r['exposure'] == 'limit' and r['width'] == 1 and r['driver_limit'] == 300 and r['tolerance_scale'] == 1)
  exact = all(r['provenance'].get('provenance_exact') and r['provenance'].get('steering_dbc_verified')
              for r in candidate+baseline)
  if not exact:
    gap = 'resolve_exact_parent_child_and_model'
  elif not any(x['authority'] == 'extra' for r in candidate for x in r['blocks']):
    gap = 'no_settled_higher_authority_exposure'
  elif not any(x['authority'] == 'stock_limit' for r in baseline for x in r['blocks']):
    gap = 'no_settled_stock_limit_reference'
  elif not primary['pairs']:
    gap = 'no_comparable_turns_in_primary_mask'
  else:
    gap = 'review_source_compatibility_assignment_response_uncertainty_and_regressions'
  return {'assessment': 'inconclusive' if not primary['pairs'] or not exact else 'matched_observations_for_review',
    'next_evidence': gap, 'comparisons': rows, 'match_limits': MATCH_LIMITS,
    'provenance': {k: [dict(route=r['route'], **r['provenance']) for r in v] for k, v in [('candidate', candidate), ('baseline', baseline)]},
    'decision_rule': 'Increase only after source-qualified fixed-configuration exposure demonstrates '
      'repeatable stock-cap undertracking and an attributable improvement without unacceptable '
      'faults, overrides or ordinary-turn regression. Feedback-gated pre/post improvement alone '
      'does not meet that rule. Missing overlap is not evidence of equal strength.'}


def save_report(report):
  from private_paths import evidence_root
  folder = evidence_root()/'steering-authority'
  folder.mkdir(exist_ok=True)
  path = folder/(report['route']+'.json')
  path.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
  return path


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('candidate', nargs='+', help='native route IDs or saved report JSON files')
  parser.add_argument('--baseline', nargs='+', default=[], help='stock reference route IDs or report JSON files')
  parser.add_argument('--output', type=Path, help='comparison JSON destination')
  args = parser.parse_args()

  def read(value):
    if Path(value).is_file():
      report = json.loads(Path(value).read_text())
      if report['version'] != VERSION:
        raise ValueError('unsupported steering report version')
      return report
    from extract import _segments, _source_signature
    from validate_log import _local_segment_coverage, _provenance
    from openpilot.tools.lib.logreader import LogReader
    route, paths = _segments(value)
    messages = list(LogReader(paths))
    report = route_report(messages, route, _provenance(messages))
    report['sources'] = _source_signature(paths).tolist()
    report['segment_coverage'] = _local_segment_coverage([Path(p).parent.name for p in paths])
    print(save_report(report))
    return report

  candidate, baseline = [read(v) for v in args.candidate], [read(v) for v in args.baseline]
  if baseline:
    result = comparison(candidate, baseline)
    result['input_sha256'] = [hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest() for r in candidate+baseline]
    if args.output:
      args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(result['assessment']+': '+result['next_evidence'])
    for row in result['comparisons']:
      print(f"{row['exposure']} width={row['width']} driver={row['driver_limit']} tolerance={row['tolerance_scale']}: "
            f"{len(row['pairs'])} unique turn pairs; body MAE change={row['body_mae_change']}")


if __name__ == '__main__':
  main()
