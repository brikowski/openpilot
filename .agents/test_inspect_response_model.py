import numpy as np
import pytest

import inspect_response_model as response_model
from inspect_response_model import brake_entry_events, continuous_mask, delayed_response, entry_response, fit_balanced, select_entry_dynamics


def entry_data():
  t = np.arange(0., 3., .01)
  return {'t': t, 'aego': np.full_like(t, -.2), 'request': np.full_like(t, -.4),
          'accel_command': np.full_like(t, -.3), 'brake_request': t >= 1.,
          'gas_command': np.full_like(t, -30000.), 'active': np.ones(len(t), dtype=bool),
          'pid': np.ones(len(t), dtype=bool), 'gas_pressed': np.zeros(len(t), dtype=bool),
          'brake_pressed': np.zeros(len(t), dtype=bool), 'vego': np.full_like(t, 20.),
          'gear': np.full_like(t, 6.)}


def test_entry_selection_preserves_request_and_initial_state_with_continuous_coast():
  data = entry_data()
  event, = brake_entry_events(data, 1.)
  assert event['time'] == 1.
  assert event['initial'] == pytest.approx(-.2)
  np.testing.assert_allclose(event['request'], -.4)
  data['gas_command'][80] = 100.
  event, = brake_entry_events(data)
  assert event['coast_s'] == pytest.approx(.19)
  assert not brake_entry_events(data, .3)
  data['gas_command'][80] = -30000
  data['t'][160:] += .1
  assert not brake_entry_events(data)


def test_entry_prediction_is_causal_and_does_not_feed_measured_response_back():
  event = {'t': np.arange(6) * .125, 'request': np.full(6, -1.), 'initial': 0., 'actual': np.full(6, -5.)}
  result = entry_response(event, .25, .125)
  np.testing.assert_allclose(result, [0., 0., -.5, -.75, -.875, -.9375])
  event['request'][-1] = 5.
  event['actual'][:] = 100.
  np.testing.assert_allclose(entry_response(event, .25, .125), result)
  np.testing.assert_allclose(entry_response(event, .25, 0.), [0., 0., -1., -1., -1., -1.])


def test_entry_dynamics_selects_training_model_and_balances_routes():
  event = {'t': np.arange(100) * .01, 'request': np.full(100, -1.), 'initial': 0.}
  quick, slow = (0., .1), (.5, .1)
  quick_event = {**event, 'actual': entry_response(event, *quick)}
  slow_event = {**event, 'actual': entry_response(event, *slow)}
  assert select_entry_dynamics([[quick_event], [quick_event]], [slow, quick]) == quick
  # Two routes favor quick, while one route with many more events favors slow.
  assert select_entry_dynamics([[quick_event], [quick_event], [slow_event] * 20], [slow, quick]) == quick
  assert select_entry_dynamics([[]], [quick]) is None


def test_entry_screen_never_passes_evaluation_events_to_fit(monkeypatch):
  training, = brake_entry_events(entry_data())
  evaluation = {**training, 'actual': training['actual'] + 10.}
  seen = []
  def fit(groups, candidates):
    assert len(groups) == 1 and groups[0][0] is training
    seen.append(True)
    return .2, .1
  monkeypatch.setattr(response_model, 'brake_entry_events', lambda data, coast: data)
  monkeypatch.setattr(response_model, 'select_entry_dynamics', fit)
  response_model.inspect_brake_entries(['train'], [[training]], ['eval'], [[evaluation]])
  assert len(seen) == 3


def test_joint_states_keep_residual_gas_through_brake_entry():
  p = {'gas': np.array([1., 1., 0., 0., 0.]), 'brake': np.array([0., 0., -1., -1., 0.]),
       'domain': np.array([1, 1, 2, 2, 0]), 'dt': .1, 'context': np.zeros((5, 3)),
       'mask': np.ones(5, dtype=bool)}
  x = response_model.joint_matrix(p, (0., .1), (0., .1))
  np.testing.assert_allclose(x[:, 0], [1., 1., .5, .25, .125])
  np.testing.assert_allclose(x[:, 1], [0., 0., -.5, -.75, -.375])
  ablated = response_model.joint_matrix(p, (0., .1), (0., .1), False)
  np.testing.assert_allclose(ablated[2:, 0], 0.)
  assert ablated[-1, 1] == 0.


def test_joint_selection_preserves_transitions_but_excludes_driver_history():
  data = entry_data()
  data['pitch'] = np.zeros(len(data['t']))
  data['brake_request'] = data['t'] >= 2.5
  data['gas_command'] = np.where(data['brake_request'], -30000., 200.)
  p = response_model.prepare_joint(data)
  assert np.any(p['mask'] & (p['domain'] == 2) & (p['age'] <= .1))
  # A request-shaped numeric CAN value is not an active brake input in the gas domain.
  assert np.all(p['brake'][p['domain'] == 1] == 0.)
  data['gas_pressed'][245] = True
  p = response_model.prepare_joint(data)
  assert not np.any(p['mask'] & (p['domain'] == 2))


def test_joint_screen_fits_only_training_routes(monkeypatch):
  training = {'actual': np.array([1.]), 'mask': np.array([True]),
              'domain': np.array([1]), 'age': np.array([.5])}
  evaluation = {**training, 'actual': np.array([10000.])}
  seen = []
  def fit(matrices, targets):
    assert len(matrices) == len(targets) == 1
    np.testing.assert_array_equal(targets[0], [1.])
    seen.append(True)
    return np.zeros(5), 0.
  monkeypatch.setattr(response_model, 'prepare_joint', lambda d: d)
  monkeypatch.setattr(response_model, 'joint_matrix', lambda *args: np.ones((1, 5)))
  monkeypatch.setattr(response_model, 'fit_balanced', fit)
  response_model.inspect_joint(['train'], [training], ['eval'], [evaluation])
  assert len(seen) == 40


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
