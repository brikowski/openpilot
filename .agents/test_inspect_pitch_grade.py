import numpy as np
import pytest

from inspect_pitch_grade import aligned_pitch_grade, gas_lookup_delta, gps_velocity_grade, leave_one_route_out


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


def test_feedforward_sensitivity_uses_1600_count_honda_lookup():
  assert gas_lookup_delta(.3, .03, .022) == pytest.approx(-94.2, abs=.5)
