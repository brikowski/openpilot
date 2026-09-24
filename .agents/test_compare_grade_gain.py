import numpy as np

from compare_grade_gain import absolute_gain, fitted_gains, one_to_one_matches, rolling_span


def test_rolling_span_rejects_edges_and_measures_centered_window():
  result = rolling_span(np.array([0.0, 1.0, 2.0, 1.0, 0.0]), 1)
  np.testing.assert_array_equal(np.isfinite(result), [False, True, True, True, False])
  np.testing.assert_allclose(result[1:4], [2.0, 1.0, 2.0])


def test_one_to_one_matches_do_not_reuse_baseline():
  baseline = np.array([[20.0, 0.2, 0.03, 5.0, 0.0, -0.2, 0.0],
                       [25.0, 0.2, 0.03, 5.0, 0.0, -0.1, 0.0]])
  candidate = np.array([[20.1, 0.2, 0.03, 5.0, 0.0, -0.1, 50.0],
                        [20.2, 0.2, 0.03, 5.0, 0.0, 0.0, 50.0]])
  ci, bi = one_to_one_matches(candidate, baseline)
  assert len(ci) == len(bi) == 1
  assert len(np.unique(bi)) == len(bi)


def test_fitted_gains_recovers_known_response_scale():
  baseline = np.array([-0.3, -0.2, -0.1])
  effect = np.array([0.4, 0.3, 0.2])
  candidate = baseline + effect
  least_squares, minimum_mae = fitted_gains(candidate, baseline)
  assert np.isclose(least_squares, 20.0 / 29.0)
  assert np.isclose(minimum_mae, 0.67)


def test_absolute_gain_maps_between_tested_calibrations():
  assert np.isclose(absolute_gain(0.2, 0.6, 1.0), 0.68)
