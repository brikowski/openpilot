from types import SimpleNamespace

import numpy as np
import pytest

import inspect_trip as trip


def data():
  t = np.arange(101) / 100
  return {'state': np.column_stack((t, np.full(len(t), trip.MILE), np.ones(len(t)), np.zeros((len(t), 4)))),
          'control': np.column_stack((t, np.ones((len(t), 2)))),
          'mode': np.column_stack((t, np.zeros(len(t)))),
          'buttons': np.empty((0, 2)),
          'fuel': np.array([[0., 100.], [.2, 110.], [.4, 120.], [.6, 130.], [.8, 140.], [1., 150.]])}


def test_distance_is_integrated_and_mpg_requires_an_explicit_assumption():
  d = data()
  r = trip.summarize(d)
  assert r['recorded_miles'] == pytest.approx(1.)
  assert r['assisted_share_percent'] == pytest.approx(100.)
  assert r['longest_without_detected_input_miles'] == pytest.approx(1.)
  assert r['modes']['Standard']['fuel_counter_ticks'] == 50
  assert r['modes']['Standard']['estimated_mpg'] is None
  assumed = trip.summarize(d, 10000)['modes']['Standard']
  assert assumed['estimated_liters'] == pytest.approx(.005)
  assert assumed['estimated_mpg'] == pytest.approx(trip.GALLON / .005)
  for invalid in (0., -1., np.nan, np.inf):
    with pytest.raises(ValueError):
      trip.summarize(d, invalid)


def test_pedals_steering_and_buttons_interrupt_at_their_native_publication():
  d = data()
  d['state'][20:30, 3] = 1
  d['state'][40:50, 5] = 1
  d['buttons'] = np.array([[.7, 1.], [.7, 2.]])
  r = trip.summarize(d)
  assert r['recorded_miles'] == pytest.approx(1.)
  assert r['assisted_miles_without_detected_override'] == pytest.approx(.8)
  assert r['longest_without_detected_input_miles'] == pytest.approx(.3)
  assert r['driver_inputs']['accelerator']['while_both_axes_active'] == 1
  assert r['driver_inputs']['steering_override']['while_both_axes_active'] == 1
  assert r['cruise_button_presses_while_assisted'] == 2
  assert r['both_axes_disengagements'] == 0


def test_one_axis_disengagement_and_missing_control_break_the_stretch():
  d = data()
  d['control'][20:30, 1] = 0
  d['control'] = d['control'][(d['control'][:, 0] < .4) | (d['control'][:, 0] >= .7)]
  r = trip.summarize(d)
  assert r['recorded_miles'] == pytest.approx(1.)
  assert r['assisted_miles_without_detected_override'] == pytest.approx(.69)
  assert r['both_axes_disengagements'] == 1  # A stale stream is not another observed disengagement.
  assert r['longest_without_detected_input_miles'] == pytest.approx(.3)


def test_invalid_state_and_sample_gaps_do_not_become_successful_miles():
  d = data()
  d['state'][20:30, 2] = 0
  d['state'] = d['state'][(d['state'][:, 0] < .4) | (d['state'][:, 0] >= .7)]
  r = trip.summarize(d)
  assert r['recorded_miles'] == pytest.approx(.69)
  assert r['unsupported_seconds'] == pytest.approx(.31)
  assert r['longest_without_detected_input_miles'] == pytest.approx(.3)
  assert r['excluded_fuel_intervals'] > 0


def test_mode_updates_are_held_without_future_values_or_cross_mode_fuel_assignment():
  d = data()
  d['mode'] = d['mode'][d['mode'][:, 0] >= .1]
  d['mode'][d['mode'][:, 0] >= .3, 1] = 1
  r = trip.summarize(d)
  assert r['modes']['unknown_or_mixed']['miles'] == pytest.approx(.1)
  assert r['modes']['Standard']['miles'] == pytest.approx(.2)
  assert r['modes']['ECON']['miles'] == pytest.approx(.7)
  assert r['modes']['Standard']['fuel_counter_ticks'] == 0
  assert r['modes']['ECON']['fuel_counter_ticks'] == 30
  assert r['modes']['unknown_or_mixed']['fuel_counter_ticks'] == 20
  assert r['native_mode_changes'] == 1
  assert r['longest_without_detected_input_miles'] == pytest.approx(1.)


def test_mode_staleness_is_unknown_and_not_standard():
  d = data()
  d['mode'] = np.array([[0., 1.]])
  r = trip.summarize(d)
  assert r['modes']['ECON']['miles'] == pytest.approx(.25)
  assert r['modes']['Standard']['miles'] == 0
  assert r['native_mode_changes'] == 0


def test_fuel_reset_wrap_and_gaps_are_not_invented_consumption():
  d = data()
  d['fuel'] = np.array([[0., 65533.], [.2, 0.], [.4, 3.], [.8, 8.], [1., 12.]])
  r = trip.summarize(d)
  assert r['fuel_counter_decreases'] == 1
  assert r['excluded_fuel_intervals'] == 2
  assert r['modes']['Standard']['fuel_counter_ticks'] == 7
  assert r['modes']['Standard']['fuel_matched_miles'] == pytest.approx(.4)
  d['state'][:, 1] = 0
  parked = trip.summarize(d, 10000)
  assert parked['recorded_miles'] == 0
  assert parked['assisted_share_percent'] is None
  assert parked['modes']['Standard']['estimated_mpg'] == 0
  assert parked['modes']['Standard']['estimated_liters'] > 0


def test_missing_control_and_initially_held_input_do_not_invent_events():
  d = data()
  d['control'] = np.empty((0, 3))
  d['state'][:, 3] = 1
  r = trip.summarize(d)
  assert r['recorded_miles'] == pytest.approx(1.)
  assert r['assisted_share_percent'] == 0
  assert r['driver_inputs']['accelerator']['recorded_rising_edges'] == 0


def test_combined_distance_share_does_not_average_percentages_or_join_routes():
  a, b = data(), data()
  b['state'][:, 1] *= 9
  b['control'][:, 1] = 0
  r = trip.combined([trip.summarize(a), trip.summarize(b)])
  assert r['recorded_miles'] == pytest.approx(10.)
  assert r['assisted_share_percent'] == pytest.approx(10.)
  assert r['longest_without_detected_input_miles'] == pytest.approx(1.)


def test_decoder_uses_only_accepted_bus_one_fuel_and_new_valid_mode_publications():
  from opendbc.can import CANPacker
  from opendbc.car import structs
  packer = CANPacker('honda_odyssey_5g_mmr_generated')
  def message(t, src=1, corrupt=False):
    address, payload, _ = packer.make_can_msg('CRUISE', src, {'TRIP_FUEL_CONSUMED': 300, 'COUNTER': 1})
    if corrupt:
      payload = payload[:-1] + bytes([payload[-1] ^ 1])
    return SimpleNamespace(logMonoTime=t, which=lambda: 'can', can=[SimpleNamespace(address=address, dat=payload, src=src)])
  def state(t, valid=True, can_valid=True):
    s = structs.CarState(ecoMode=True, ecoModeValid=valid, canValid=can_valid)
    return SimpleNamespace(logMonoTime=t, which=lambda: 'carState', carState=s)
  r = trip.decode([message(1_020_000_000, corrupt=True), message(1_010_000_000), message(1_000_000_000, src=0),
                   state(1_030_000_000, False), state(1_040_000_000, can_valid=False), state(1_050_000_000)])
  np.testing.assert_array_equal(r['fuel'], [[1.01, 300.]])
  np.testing.assert_array_equal(r['mode'], [[1.05, 1.]])


def test_decimated_logs_cannot_claim_input_free_distance():
  d = data()
  for stream in ('state', 'control'):
    sparse = dict(d)
    sparse[stream] = d[stream][::10]
    with pytest.raises(ValueError, match='full-rate'):
      trip.summarize(sparse)


def test_recorded_fuel_dbc_must_match_the_decoder(monkeypatch):
  from pathlib import Path
  import subprocess
  current = Path('opendbc_repo/opendbc/dbc/generator/honda/_honda_common.dbc').read_text()
  monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: current)
  assert trip.fuel_source_matches('synthetic')
  monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: current.replace('TRIP_FUEL_CONSUMED : 23|16', 'TRIP_FUEL_CONSUMED : 23|8'))
  assert not trip.fuel_source_matches('synthetic')
  def missing(*args, **kwargs):
    raise subprocess.CalledProcessError(128, 'git')
  monkeypatch.setattr(subprocess, 'check_output', missing)
  assert not trip.fuel_source_matches('missing')


def test_validator_automatically_retains_passive_trip_stats(monkeypatch):
  import validate_log
  from openpilot.cereal import log
  monkeypatch.setattr(validate_log, '_provenance', lambda _: {
    'provenance_exact': True, 'opendbc_commit_full': 'synthetic',
    'opendbc_commit': None, 'honda_brake_firmware': [],
  })
  monkeypatch.setattr(trip, 'fuel_source_matches', lambda _: True)
  messages = []
  for i in range(120):
    t = 1_000_000_000 + i * 10_000_000
    for name in ('carControl', 'carOutput', 'carState'):
      m = log.Event.new_message(logMonoTime=t)
      value = m.init(name)
      if name == 'carControl':
        value.latActive = value.longActive = True
      elif name == 'carState':
        value.vEgoRaw = value.vEgo = 20.
        value.canValid = value.ecoModeValid = True
      messages.append(m)
  r = validate_log.analyze(messages, validate_log.ODYSSEY, alpha_longitudinal=True)
  assert r['trip_summary']['recorded_miles'] == pytest.approx(20 * 1.19 / trip.MILE)
  assert r['trip_summary']['assisted_share_percent'] == pytest.approx(100.)
  assert r['trip_summary']['modes']['Standard']['estimated_mpg'] is None
  monkeypatch.setattr(trip, 'fuel_source_matches', lambda _: False)
  assert 'trip_summary' not in validate_log.analyze(messages, validate_log.ODYSSEY, alpha_longitudinal=True)


def maneuver(d, direction=1, confirmed=True):
  t = np.arange(21) / 20
  phase = np.where((t >= .1) & (t < .2), 1, 0)
  if confirmed:
    phase[(t >= .2) & (t < .35)] = 2
  d['lane_change'] = np.column_stack((t, phase, np.where(phase > 0, direction, 0), np.ones(len(t))))
  d['state'][15:30, 5] = 1
  d['state'][:, 6] = 1 if direction == 1 else -1
  return d


def test_confirmed_lane_change_retains_miles_and_fuel_but_excludes_its_steering():
  d = maneuver(data())
  strict = trip.summarize(d, exclude_lane_change_steering=False)
  adjusted = trip.summarize(d)
  assert adjusted['recorded_miles'] == strict['recorded_miles'] == pytest.approx(1.)
  assert adjusted['modes']['Standard']['fuel_counter_ticks'] == strict['modes']['Standard']['fuel_counter_ticks']
  assert strict['assisted_miles_without_detected_override'] == pytest.approx(.85)
  assert adjusted['assisted_miles_without_detected_override'] == pytest.approx(1.)
  assert adjusted['longest_without_detected_input_miles'] == pytest.approx(1.)
  assert adjusted['confirmed_lane_changes'] == 1
  assert adjusted['driver_inputs']['steering_override'] == {
    'recorded_rising_edges': 1, 'lane_change_edges_excluded': 1, 'while_both_axes_active': 0,
  }
  assert 'lane changes excluded' in adjusted['shareable_text']


def test_canceled_preparation_does_not_excuse_steering():
  r = trip.summarize(maneuver(data(), confirmed=False))
  assert r['confirmed_lane_changes'] == 0
  assert r['assisted_miles_without_detected_override'] == pytest.approx(.85)
  assert r['driver_inputs']['steering_override']['while_both_axes_active'] == 1


@pytest.mark.parametrize('direction,torque,excluded', [(1, 1., True), (1, -1., False), (2, -1., True), (2, 0., False)])
def test_lane_change_direction_must_match_steering(direction, torque, excluded):
  d = maneuver(data(), direction)
  d['state'][:, 6] = torque
  r = trip.summarize(d)
  assert r['driver_inputs']['steering_override']['while_both_axes_active'] == (0 if excluded else 1)
  assert r['assisted_miles_without_detected_override'] == pytest.approx(1. if excluded else .85)


def test_opposite_steering_and_inputs_continuing_after_the_maneuver_still_count():
  d = maneuver(data())
  d['state'][25:45, 5] = 1
  d['state'][25:30, 6] = -1
  r = trip.summarize(d)
  assert r['driver_inputs']['steering_override']['while_both_axes_active'] == 2
  assert r['assisted_miles_without_detected_override'] == pytest.approx(.85)  # Opposite .05s + continued .10s.


def test_lane_change_does_not_excuse_pedals_buttons_or_disengagements():
  d = maneuver(data())
  d['state'][22:25, 4] = 1
  d['buttons'] = np.array([[.24, 1.]])
  d['control'][26:30, 1] = 0
  r = trip.summarize(d)
  assert r['driver_inputs']['brake']['while_both_axes_active'] == 1
  assert r['cruise_button_presses_while_assisted'] == 1
  assert r['both_axes_disengagements'] == 1
  assert r['assisted_miles_without_detected_override'] == pytest.approx(.93)
  assert r['longest_without_detected_input_miles'] == pytest.approx(.7)


@pytest.mark.parametrize('fault', ['gap', 'invalid', 'direction'])
def test_confirmation_cannot_bridge_missing_invalid_or_different_direction_preparation(fault):
  d = maneuver(data())
  if fault == 'gap':
    d['lane_change'] = d['lane_change'][d['lane_change'][:, 0] != .15]
    d['lane_change'] = d['lane_change'][d['lane_change'][:, 0] != .2]
  elif fault == 'invalid':
    d['lane_change'][d['lane_change'][:, 0] == .2, 3] = 0
  else:
    d['lane_change'][d['lane_change'][:, 0] >= .2, 2] = 2
    d['state'][:, 6] = -1  # Opposite the old preparation, matching the new maneuver.
  r = trip.summarize(d)
  assert r['assisted_miles_without_detected_override'] < 1.
  assert r['driver_inputs']['steering_override']['while_both_axes_active'] >= 1


def test_lane_change_decoder_retains_native_state_direction_and_validity():
  from openpilot.cereal import log
  messages = []
  for t, phase, direction, valid in [(1., 'preLaneChange', 'left', True), (1.05, 'laneChangeStarting', 'left', True),
                                     (1.1, 'laneChangeFinishing', 'right', False)]:
    m = log.Event.new_message(logMonoTime=int(t * 1e9), valid=valid)
    meta = m.init('modelV2').meta
    meta.laneChangeState, meta.laneChangeDirection = phase, direction
    messages.append(m)
  np.testing.assert_array_equal(trip.decode(messages)['lane_change'], [[1., 1, 1, 1], [1.05, 2, 1, 1], [1.1, 3, 2, 0]])


def test_different_lane_change_policies_are_not_combined_silently():
  d = maneuver(data())
  legacy = trip.summarize(d, exclude_lane_change_steering=False)
  legacy.pop('lane_change_steering_excluded')
  for fields in legacy['driver_inputs'].values():
    fields.pop('lane_change_edges_excluded')
  assert trip.combined([legacy])['lane_change_steering_events_excluded'] == 0
  with pytest.raises(ValueError, match='different lane-change'):
    trip.combined([trip.summarize(d), legacy])
