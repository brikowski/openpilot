import numpy as np
import pytest

from inspect_pitch_grade import aligned_pitch_grade, gas_lookup_delta, gps_coast_response, gps_velocity_grade, leave_one_route_out
from opendbc.car.honda.values import CarControllerParams


def test_gps_ned_grade_sign_tracks_climb_and_descent():
  assert gps_velocity_grade(10., 0., -1.) > 0.
  assert gps_velocity_grade(10., 0., 1.) < 0.
  assert gps_velocity_grade(10., 0., 0.) == pytest.approx(0.)


def test_gps_alignment_uses_only_latest_published_controller_state():
  data = {'t0': 100., 't': np.array([0., .1, .2]),
          'pitch': np.array([.01, .02, .9]), 'vego': np.full(3, 10.),
          'aego': np.array([0., .5, 99.]), 'active': np.ones(3, dtype=bool),
          'response_state_fresh': np.ones(3, dtype=bool),
          'gas_pressed': np.zeros(3, dtype=bool),
          'brake_pressed': np.zeros(3, dtype=bool)}
  gps = np.array([[100.12, .005, 10.]])
  context, bias, observed = aligned_pitch_grade(data, gps)
  np.testing.assert_allclose(context, [[1., .5, .1]])
  np.testing.assert_allclose(bias, [.015])
  np.testing.assert_allclose(observed, [[.12, .02, .005]])
  data['pitch'][2] = -99.
  np.testing.assert_allclose(aligned_pitch_grade(data, gps)[1], bias)
  gps[0, 0] = 100.15
  assert not len(aligned_pitch_grade(data, gps)[1])


def test_pitch_offset_holdout_cannot_fit_the_held_route():
  groups = [(np.ones((5, 3)), np.full(5, value), np.empty((5, 3)))
            for value in (.02, .02, 1.)]
  coef, error = leave_one_route_out(groups, 2, 1)
  np.testing.assert_allclose(coef, [.02])
  np.testing.assert_allclose(error, -.98)


def test_feedforward_sensitivity_initializes_2000_count_odyssey_lookup(monkeypatch):
  monkeypatch.setattr(CarControllerParams, 'BOSCH_GAS_LOOKUP_V', [0, 1600])
  assert gas_lookup_delta(.3, .03, .022) == pytest.approx(-117.7, abs=.5)
  assert CarControllerParams.BOSCH_GAS_LOOKUP_V == [0, 2000]


def test_gps_coast_response_requires_recent_gps_and_keeps_coast_separate_from_brake():
  t = np.arange(200) * .01
  data = {'t0': 100., 't': t, 'active': np.ones(200, bool), 'pid': np.ones(200, bool),
          'gas_pressed': np.zeros(200, bool), 'brake_pressed': np.zeros(200, bool),
          'response_state_fresh': np.ones(200, bool), 'vego': np.full(200, 20.),
          'request': np.full(200, -.15), 'gear': np.full(200, 7), 'aego': np.full(200, .1),
          'gas_command': np.full(200, -30000.), 'brake_request': np.zeros(200, bool)}
  gps = np.array([[100., -.02, 20.]])
  rows = gps_coast_response(data, gps)
  assert len(rows) == 1
  assert rows[0]['terrain'] == 'downhill' and rows[0]['domain'] == 'coast'
  assert rows[0]['rows'] == 5 and rows[0]['positive_episodes'] == 1
  assert rows[0]['median_future_error'] == pytest.approx(.25)
  assert gps_coast_response(data, gps, max_age=1.5)[0]['rows'] > rows[0]['rows']
  data['brake_request'][:] = True
  rows = gps_coast_response(data, gps)
  assert len(rows) == 1 and rows[0]['domain'] == 'brake'
  data['brake_request'][30:60] = False
  assert not gps_coast_response(data, gps)
