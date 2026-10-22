from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from compare_lateral_response import (authority_blocks, can_schema_verified, comparison, held,
                                      history_supported, match_turns, native_streams, output_agreement, route_report)


def native(counts=2560, direction=1):
  t = np.arange(601)*.01
  pose_t = t[::5]
  def columns(*values):
    return np.column_stack([np.full(len(t), x) for x in values])
  return {
    'state': np.c_[t, columns(20, 0, 0, 0, 1, 0, 0, 1)],
    'control': np.c_[t, columns(1, direction, .8*direction, -direction, 1, 1)],
    'wire': np.c_[t, columns(counts*direction, 1, -direction, 1)],
    'output': np.c_[t+.001, columns(counts*direction, -direction)],
    'pose': np.c_[pose_t, np.full(len(pose_t), .8*direction/20), np.full(len(pose_t), .01),
                  np.ones(len(pose_t)), pose_t+.025],
    'parameters': np.c_[t, columns(.01, 1)],
    'model': np.c_[t, columns(0)],
    'mode': np.c_[t[::4], np.zeros(len(t[::4]))],
    'delay': np.c_[t, columns(.15, 1)],
    'torque': np.c_[t, columns(.9, 0, .2)],
  }


def test_hold_never_uses_future_or_stale_publications():
  values, valid = held(np.array([[1., 7.], [2., 9.]]), [0., 1., 1.01, 1.5, 2.], .04)
  np.testing.assert_array_equal(valid, [False, True, True, False, True])
  assert np.isnan(values[0]).all() and np.isnan(values[3]).all()
  assert values[2, 1] == 7


def test_transmission_matches_following_output_once_and_does_not_mask_corruption():
  wire = np.array([[0., 2560], [.01, 2560], [.02, 3000], [.04, 3000]])
  output = np.array([[.015, 2560], [.025, 2999]])
  np.testing.assert_array_equal(output_agreement(wire, output), [False, True, False, False])


def test_driver_history_includes_held_boundary_and_rejects_missing_state():
  d = native()
  d['state'][49, 6] = 600  # Held through the left boundary at .495s; current input is zero.
  assert not history_supported(d['state'], np.array([.995]), .5, 300)[0]
  assert history_supported(d['state'], np.array([1.]), .5, 1200)[0]
  rows = d['state'][100:]
  assert not history_supported(rows, np.array([1.1]), .5, 300)[0]
  rows = np.delete(d['state'], np.arange(60, 70), axis=0)
  assert not history_supported(rows, np.array([1.]), .5, 1200)[0]


@pytest.mark.parametrize('direction', [1, -1])
def test_stock_limit_undertracking_uses_body_motion_and_preserves_turn_identity(direction):
  rows, coverage = authority_blocks(native(direction=direction), width=1., driver_limit=300)
  assert len(rows) >= 4
  assert len({r['turn'] for r in rows}) == 1
  assert coverage['turns'] == 1
  assert all(r['authority'] == 'stock_limit' and r['direction'] == direction for r in rows)
  np.testing.assert_allclose([r['body_under'] for r in rows], .2)
  np.testing.assert_allclose([r['body_sigma'] for r in rows], .2)


@pytest.mark.parametrize('kind', ['mode_unknown', 'lane_change', 'stale_model', 'bad_pose', 'stale_wire',
                                  'output_mismatch', 'driver_override', 'steering_fault', 'wire_sign'])
def test_unreliable_exposure_cannot_become_steering_authority_evidence(kind):
  d = native()
  if kind == 'mode_unknown':
    d['mode'] = np.empty((0, 2))
  elif kind == 'lane_change':
    d['model'][:, 1] = 2
  elif kind == 'stale_model':
    d['model'] = d['model'][:1]
  elif kind == 'bad_pose':
    d['pose'][:, 3] = 0
  elif kind == 'stale_wire':
    d['wire'] = d['wire'][:1]
  elif kind == 'output_mismatch':
    d['output'][:, 1] -= 1
  elif kind == 'driver_override':
    d['state'][:, 2] = 1
  elif kind == 'steering_fault':
    d['state'][:, 3] = 1
  elif kind == 'wire_sign':
    d['wire'][:, 1] *= -1
  rows, coverage = authority_blocks(d, width=1., driver_limit=300)
  assert not rows
  assert sum(coverage['rejected_windows'].values()) > 0


def test_authority_must_precede_response_through_measured_delay():
  d = native(counts=3840)
  d['delay'][:, 1] = .8
  d['wire'][d['wire'][:, 0] < 1, 1] = 2560
  d['output'][d['output'][:, 0] < 1, 1] = 2560
  rows, coverage = authority_blocks(d, width=.5, driver_limit=300)
  assert coverage['rejected_windows']['authority_not_settled'] > 0
  assert not any(r['authority'] == 'extra' and r['start'] < 2 for r in rows)
  assert any(r['authority'] == 'extra' for r in rows)


def test_fault_after_a_qualified_window_is_retained_rather_than_censored():
  d = native()
  d['state'][d['state'][:, 0] > 4.1, 3] = 1
  rows, _ = authority_blocks(d, width=1., driver_limit=300)
  assert any(r['following_driver_or_fault'] for r in rows)
  assert any(not r['following_driver_or_fault'] for r in rows)


def block(route='candidate', turn=1, **values):
  return dict(route=route, turn=turn, direction=1, econ=False, speed=20., demand=1., roll=.01,
              demand_span=.1, demand_trend=0., body_mae=.1, controller_mae=.1, body_sigma=.2,
              authority='extra', width=1., driver_limit=300, **values)


def test_matching_never_reuses_a_turn_or_its_donors():
  candidate = [block(), block()]
  baseline = [block('baseline', 1), block('baseline', 2)]
  pairs = match_turns(candidate, baseline, 1.)
  assert len(pairs) == 1
  assert pairs[0]['body_sigma_sum'] == .4  # No false precision from repeated pose samples.


@pytest.mark.parametrize('field,value', [('direction', -1), ('econ', True), ('speed', 25.),
                                        ('demand', 2.), ('roll', .03), ('demand_span', .5), ('demand_trend', 1.)])
def test_comparison_requires_overlap_in_each_motion_condition(field, value):
  other = block('baseline')
  other[field] = value
  assert not match_turns([block()], [other], 1.)


def report(route, authority, parent='a'*40):
  b = block(route)
  b['authority'] = authority
  return {'route': route, 'blocks': [b], 'provenance': {
    'git_commit_full': parent, 'opendbc_commit_full': 'b'*40,
    'provenance_exact': True, 'steering_dbc_verified': True,
  }}


def test_empty_overlap_and_better_observations_do_not_automatically_increase_torque():
  candidate = report('candidate', 'extra')
  baseline = report('baseline', 'stock_limit')
  candidate['blocks'][0]['body_mae'] = .01
  result = comparison([candidate], [baseline])
  assert result['assessment'] == 'matched_observations_for_review'
  assert 'source_compatibility' in result['next_evidence']
  baseline['blocks'][0]['speed'] = 30.
  result = comparison([candidate], [baseline])
  assert result['assessment'] == 'inconclusive'
  assert result['next_evidence'] == 'no_comparable_turns_in_primary_mask'


def test_missing_exposure_provenance_and_mixed_revisions_are_explicit():
  candidate, baseline = report('candidate', 'extra'), report('baseline', 'stock_limit')
  candidate['blocks'] = []
  assert comparison([candidate], [baseline])['next_evidence'] == 'no_settled_higher_authority_exposure'
  candidate['provenance']['provenance_exact'] = False
  assert comparison([candidate], [baseline])['next_evidence'] == 'resolve_exact_parent_child_and_model'
  other = deepcopy(candidate)
  other['route'] = 'other'
  other['provenance']['git_commit_full'] = 'c'*40
  with pytest.raises(ValueError, match='revision'):
    comparison([candidate, other], [baseline])
  with pytest.raises(ValueError, match='duplicate'):
    comparison([baseline], [baseline])


def test_manual_decoder_checks_source_semantics_and_actual_checksum(monkeypatch):
  from opendbc.can import CANPacker
  packer = CANPacker('acura_rdx_2020_can_generated')
  address, dat, bus = packer.make_can_msg('STEERING_CONTROL', 1, {'STEER_TORQUE': -3072, 'STEER_TORQUE_REQUEST': 1})
  bad = dat[:-1]+bytes([dat[-1] ^ 1])
  _, inactive, _ = packer.make_can_msg('STEERING_CONTROL', 1, {'STEER_TORQUE': 0, 'STEER_TORQUE_REQUEST': 0})

  def message(kind, **kwargs):
    return SimpleNamespace(logMonoTime=0, which=lambda: kind, **kwargs)

  messages = [message('carParams', carParams=SimpleNamespace(carFingerprint='HONDA_ODYSSEY_5G_MMR', openpilotLongitudinalControl=True)),
              message('sendcan', sendcan=[SimpleNamespace(address=address, dat=dat, src=bus),
                                          SimpleNamespace(address=address, dat=bad, src=bus),
                                          SimpleNamespace(address=address, dat=dat, src=0),
                                          SimpleNamespace(address=address, dat=inactive, src=bus)])]
  d, bad_packets = native_streams(messages)
  assert bad_packets == 1
  np.testing.assert_array_equal(d['wire'][:, 1:3], [[-3072, 1], [0, 0]])
  from pathlib import Path
  source = Path('opendbc_repo/opendbc/dbc/generator/honda/_bosch_2018.dbc').read_text()
  monkeypatch.setattr('compare_lateral_response.subprocess.run', lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=source))
  assert can_schema_verified('a'*40)
  source = source.replace('7|16@0-', '7|16@0+')
  assert not can_schema_verified('a'*40)


def test_ordinary_turn_response_and_unknown_followup_remain_visible():
  rows, coverage = authority_blocks(native(counts=1500), width=1., driver_limit=300)
  assert rows and coverage['by_authority']['ordinary'] == len(rows)
  assert rows[-1]['following_driver_or_fault'] is None
  assert rows[0]['following_driver_or_fault'] is False


def test_driver_history_extends_to_longer_observed_response_delay():
  d = native()
  d['delay'][:, 1] = .9
  d['state'][80:90, 6] = 600
  rows, _ = authority_blocks(d, width=.5, driver_limit=300)
  assert not any(1.5 <= r['start'] < 1.8 for r in rows)
  assert any(r['start'] >= 2 for r in rows)


def test_physical_tracking_is_independent_of_the_controller_angle_estimate():
  d = native()
  d['pose'][:, 1] = .6/20
  rows, _ = authority_blocks(d, width=1., driver_limit=300)
  assert rows
  np.testing.assert_allclose([r['body_under'] for r in rows], .4)
  np.testing.assert_allclose([r['controller_under'] for r in rows], .2)


def test_mixed_dirty_recording_cannot_keep_an_exact_source_label(monkeypatch):
  def message(kind, **kwargs):
    return SimpleNamespace(logMonoTime=0, which=lambda: kind, **kwargs)
  messages = [message('carParams', carParams=SimpleNamespace(carFingerprint='HONDA_ODYSSEY_5G_MMR', openpilotLongitudinalControl=True)),
              message('initData', initData=SimpleNamespace(gitCommit='a'*40, dirty=True))]
  monkeypatch.setattr('compare_lateral_response.can_schema_verified', lambda _child: True)
  r = route_report(messages, 'synthetic', {'git_commit_full': 'a'*40, 'provenance_exact': True})
  assert not r['provenance']['provenance_exact']


def test_received_mode_is_held_between_updates_but_not_through_missing_packets():
  d = native()
  d['state'][:, 8] = 0  # A per-cycle update flag is normally false between packets.
  rows, _ = authority_blocks(d, width=1., driver_limit=300)
  assert rows and all(not r['econ'] for r in rows)
  d['mode'] = d['mode'][:1]
  rows, _ = authority_blocks(d, width=1., driver_limit=300)
  assert not rows


def test_collector_accepts_only_received_factory_mode_updates():
  def message(kind, t=0, **kwargs):
    return SimpleNamespace(logMonoTime=t, which=lambda: kind, valid=True, **kwargs)
  def state(mode, updated):
    return SimpleNamespace(vEgo=20., steeringPressed=False, steerFaultTemporary=False,
      steerFaultPermanent=False, canValid=True, steeringTorque=0., ecoMode=mode, ecoModeValid=updated)
  messages = [message('carParams', carParams=SimpleNamespace(carFingerprint='HONDA_ODYSSEY_5G_MMR', openpilotLongitudinalControl=True)),
              message('carState', 10_000_000, carState=state(False, True)),
              message('carState', 20_000_000, carState=state(True, False)),
              message('carState', 30_000_000, carState=state(True, True))]
  data, _ = native_streams(messages)
  np.testing.assert_array_equal(data['mode'], [[.01, 0.], [.03, 1.]])


def test_small_low_speed_request_at_the_cap_is_still_authority_exposure():
  d = native()
  d['state'][:, 1] = 2.
  d['control'][:, 2:4] = [.1, .08]
  d['pose'][:, 1] = .08/2
  rows, _ = authority_blocks(d, width=1., driver_limit=300)
  assert rows and all(r['authority'] == 'stock_limit' for r in rows)
  np.testing.assert_allclose([r['body_under'] for r in rows], .02)


@pytest.mark.parametrize('change', ['unchanged', 'mtime_only', 'same_size', 'missing_segment', 'new_segment',
                                  'missing_hashes', 'moved_root', 'missing_assessment', 'changed_assessment'])
def test_saved_report_requires_current_sources_and_assessment(tmp_path, monkeypatch, change):
  import hashlib
  import json
  import os
  import compare_lateral_response as assessment

  route = 'synthetic-route'
  source = tmp_path / 'rlogs' / (route+'--0') / 'rlog.zst'
  source.parent.mkdir(parents=True)
  source.write_bytes(b'original')
  paths = [str(source)]
  sources = [[str(source), hashlib.sha256(source.read_bytes()).hexdigest()]]
  saved = dict(report(route, 'extra'), version=assessment.VERSION, sources=sources, tool_sha256=assessment.TOOL_SHA256)
  before = source.stat()
  if change == 'mtime_only':
    os.utime(source, (before.st_atime+100, before.st_mtime+100))
  elif change == 'same_size':
    source.write_bytes(b'modified')
    os.utime(source, (before.st_atime, before.st_mtime))
  elif change == 'missing_segment':
    paths.clear()
  elif change == 'new_segment':
    other = tmp_path / 'rlogs' / (route+'--1') / 'rlog.zst'
    other.parent.mkdir()
    other.write_bytes(b'new tail')
    paths.append(str(other))
  elif change == 'missing_hashes':
    saved.pop('sources')
  elif change == 'moved_root':
    sources[0][0] = '/another-analysis-host/'+source.parent.name+'/rlog.zst'
  elif change == 'missing_assessment':
    saved.pop('tool_sha256')
  elif change == 'changed_assessment':
    saved['tool_sha256'] = assessment.TOOL_SHA256[:-1] + ('0' if assessment.TOOL_SHA256[-1] != '0' else '1')
  monkeypatch.setattr('extract._segments', lambda _route: (route, paths))
  filename = tmp_path / 'report.json'
  filename.write_text(json.dumps(saved))
  monkeypatch.setattr('sys.argv', ['compare_lateral_response.py', str(filename)])
  if change in ('same_size', 'missing_segment', 'new_segment', 'missing_hashes', 'missing_assessment', 'changed_assessment'):
    with pytest.raises(ValueError, match='stale|source hashes|assessment code'):
      assessment.main()
  else:
    assessment.main()


@pytest.mark.parametrize('change', ['contents', 'inventory'])
def test_sources_changing_during_assessment_cannot_be_saved(tmp_path, monkeypatch, change):
  import compare_lateral_response as assessment

  route = 'synthetic-route'
  source = tmp_path / (route+'--0') / 'rlog.zst'
  source.parent.mkdir()
  source.write_bytes(b'original')
  paths = [str(source)]
  monkeypatch.setattr('extract._segments', lambda _route: (route, list(paths)))
  monkeypatch.setattr('openpilot.tools.lib.logreader.LogReader', lambda _paths: [])
  monkeypatch.setattr('validate_log._provenance', lambda _messages: {})

  def changing_report(*_args):
    if change == 'contents':
      source.write_bytes(b'modified')
    else:
      other = tmp_path / (route+'--1') / 'rlog.zst'
      other.parent.mkdir()
      other.write_bytes(b'new tail')
      paths.append(str(other))
    return report(route, 'extra')

  saved = []
  monkeypatch.setattr(assessment, 'route_report', changing_report)
  monkeypatch.setattr(assessment, 'save_report', lambda value: saved.append(value))
  monkeypatch.setattr('sys.argv', ['compare_lateral_response.py', route])
  with pytest.raises(ValueError, match='changed during'):
    assessment.main()
  assert not saved
