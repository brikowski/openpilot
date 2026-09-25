import numpy as np

from inspect_response_model import continuous_mask, delayed_response, fit_balanced


def test_delay_filter_is_causal_and_preserves_negative_brake_input():
  signal = np.array([0., -1., -1., -1., -1.])
  np.testing.assert_allclose(delayed_response(signal, .1, .1, 0.), [np.nan, 0., -1., -1., -1.])
  smooth = delayed_response(signal, .1, .1, .1)
  np.testing.assert_allclose(smooth, [np.nan, 0., -.5, -.75, -.875])
  signal[-1] = 100
  np.testing.assert_allclose(delayed_response(signal, .1, .1, .1), smooth)


def test_continuity_rejects_pedals_gear_changes_and_log_gaps():
  t = np.arange(0., 1., .02)
  valid = np.ones(len(t), dtype=bool)
  gear = np.full(len(t), 5.)
  assert continuous_mask(valid, gear, t, .1)[15]
  valid[13] = False
  assert not continuous_mask(valid, gear, t, .1)[15]
  valid[13] = True
  gear[14:] = 6
  assert not continuous_mask(valid, gear, t, .1)[15]
  gear[:] = 5
  t[14:] += .1
  assert not continuous_mask(valid, gear, t, .1)[15]


def test_fit_balances_routes_not_row_counts():
  coef, loss = fit_balanced([np.ones((2, 1)), np.ones((20, 1))], [np.zeros(2), np.full(20, 2.)])
  np.testing.assert_allclose(coef, [1.])
  np.testing.assert_allclose(loss, 2.)
