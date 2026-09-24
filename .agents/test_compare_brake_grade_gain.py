import numpy as np

from compare_brake_grade_gain import fitted_grade_gains, trailing_span


def test_trailing_span_rejects_leading_window_and_tracks_recent_values():
  result = trailing_span(np.array([0.0, 1.0, 2.0, 1.0, 1.5]), 3)
  np.testing.assert_array_equal(np.isfinite(result), [False, False, True, True, True])
  np.testing.assert_allclose(result[2:], [2.0, 1.0, 1.0])


def test_fitted_grade_gains_recovers_known_response_correction():
  grade_basis = np.array([-0.5, 0.5, 1.0, -1.0])
  error = -0.3 * grade_basis
  least_squares, minimum_mae = fitted_grade_gains(error, grade_basis)
  assert np.isclose(least_squares, 0.3)
  assert np.isclose(minimum_mae, 0.3)


def test_fitted_grade_gains_accounts_for_response_sensitivity():
  grade_basis = np.array([-0.5, 0.5, 1.0, -1.0])
  error = -0.3 * grade_basis
  least_squares, _ = fitted_grade_gains(error, grade_basis, response_sensitivity=0.5)
  assert np.isclose(least_squares, 0.6)


def test_fitted_grade_gains_honors_sample_weights():
  grade_basis = np.ones(3)
  error = np.array([-0.2, -0.8, -0.8])
  unweighted, _ = fitted_grade_gains(error, grade_basis)
  weighted, _ = fitted_grade_gains(error, grade_basis, weights=np.array([10.0, 1.0, 1.0]))
  assert np.isclose(unweighted, 0.6)
  assert np.isclose(weighted, 0.3)
