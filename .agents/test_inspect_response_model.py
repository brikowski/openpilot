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


def residual_data():
  t = np.arange(250) * .02
  return {'t': t, 'dt': .02, 'residual': np.full(len(t), .2),
          'eligible': np.ones(len(t), dtype=bool), 'mask': np.ones(len(t), dtype=bool),
          'domain': np.ones(len(t), dtype=int)}


def test_response_alignment_uses_only_published_state_and_rejects_staleness():
  data = {'t': np.array([-.01, 0., .01, .025, .03, .10]), 't0': 0.}
  state_t = np.array([0., .03])
  values = np.array([[10., -.2, 0., 0.], [11., -.4, 1., 0.]])
  held = response_model.latest_response_state(data, state_t, values)
  np.testing.assert_allclose(held['aego'], [np.nan, -.2, -.2, -.2, -.4, -.4])
  np.testing.assert_array_equal(held['response_state_fresh'], [False, True, True, True, True, False])
  np.testing.assert_array_equal(held['gas_pressed'][1:5], [False, False, False, True])
  values[1, 1] = 100.
  changed = response_model.latest_response_state(data, state_t, values)
  np.testing.assert_allclose(changed['aego'][:4], held['aego'][:4])


def test_residual_observer_is_bounded_causal_and_resets_after_invalid_history():
  data = residual_data()
  data['residual'][:] = 10.
  out, segment, age = response_model.observe_residual(data, .1, True)
  assert 0. < out[0] < .5 and np.max(out) <= .5
  data['residual'][-1] = -10.
  changed = response_model.observe_residual(data, .1, True)[0]
  np.testing.assert_allclose(changed[:-1], out[:-1])
  data['eligible'][60] = False
  data['t'][120:] += .1
  out, segment, age = response_model.observe_residual(data, .1, True)
  assert out[60] == out[120] == 0.
  assert age[60] == age[120] == 0.
  assert segment[61] > segment[59] and segment[121] > segment[119]
  assert out[61] == pytest.approx(.5 / 6)


def test_domain_reset_changes_estimate_not_the_forecast_cohort():
  data = residual_data()
  data['domain'][100:] = 2
  data['residual'][100:] = -.2
  carried = response_model.observe_residual(data, .1, False)
  reset = response_model.observe_residual(data, .1, True)
  assert carried[0][100] > 0. and reset[0][100] < 0.
  np.testing.assert_array_equal(carried[1], reset[1])
  np.testing.assert_array_equal(carried[2], reset[2])
  a = response_model.residual_forecast_errors(data, carried)
  b = response_model.residual_forecast_errors(data, reset)
  np.testing.assert_array_equal(a[0], b[0])
  np.testing.assert_array_equal(a[2], b[2])


def test_forecast_scoring_rejects_intervening_invalid_samples_and_route_end():
  data = residual_data()
  data['eligible'][60] = False
  observer = response_model.observe_residual(data, .1, False)
  valid, error, raw, future = response_model.residual_forecast_errors(data, observer, .3)
  assert valid[30]
  assert not valid[50]  # both endpoints valid but intervening sample 60 is invalid
  assert not valid[-1]
  assert .3 <= data['t'][future[30]] - data['t'][30] < .33
  np.testing.assert_allclose(error[valid], raw[valid] - observer[0][valid])


def test_residual_screen_keeps_evaluation_out_of_both_model_and_filter_selection(monkeypatch):
  training, evaluation = residual_data(), residual_data()
  training['actual'], evaluation['actual'] = training['residual'], -evaluation['residual']
  calls = []
  def model(groups, carry=True):
    assert len(groups) == 1 and groups[0] is training
    calls.append('model')
    return ((0., 0.), (0., 0.)), np.zeros(5)
  def select(groups, reset):
    assert len(groups) == 1 and groups[0] is training
    calls.append('filter')
    return .5
  monkeypatch.setattr(response_model, 'prepare_joint', lambda d: d)
  monkeypatch.setattr(response_model, 'fit_joint_model', model)
  monkeypatch.setattr(response_model, 'select_residual_filter', select)
  monkeypatch.setattr(response_model, 'joint_matrix', lambda d, *args: np.zeros((len(d['t']), 5)))
  response_model.inspect_residuals(['train'], [training], ['eval'], [evaluation])
  assert calls == ['model', 'filter', 'filter']


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


def test_coast_fit_excludes_transients_stale_state_and_gear_changes():
  t = np.arange(0., 2., .01)
  data = {'t': t, 'gas_command': np.full(len(t), -30000.),
          'brake_request': np.zeros(len(t), dtype=bool), 'active': np.ones(len(t), dtype=bool),
          'pid': np.ones(len(t), dtype=bool), 'gas_pressed': np.zeros(len(t), dtype=bool),
          'brake_pressed': np.zeros(len(t), dtype=bool), 'vego': np.full(len(t), 20.),
          'request': np.full(len(t), -.2), 'aego': np.full(len(t), -.1),
          'pitch': np.zeros(len(t)), 'gear': np.full(len(t), 6.),
          'response_state_fresh': np.ones(len(t), dtype=bool)}
  data['gas_command'][:50] = 100.
  data['response_state_fresh'][100] = False
  data['gear'][150:] = 5.
  prepared = response_model.prepare_coast(data)
  assert prepared['opportunity'][50] and not prepared['settled'][50]
  assert prepared['settled'][80]
  assert not prepared['settled'][100] and not prepared['settled'][120]
  assert prepared['settled'][140]
  assert not prepared['settled'][150] and prepared['settled'][180]


def test_coast_screen_never_fits_heldout_outcomes(monkeypatch, capsys):
  base = {'context': np.ones((10, 3)), 'actual': np.full(10, -.2),
          'settled': np.ones(10, dtype=bool), 'opportunity': np.ones(10, dtype=bool),
          'request': np.full(10, -.3), 't': np.arange(10) * .1}
  training = [base, {**base, 'actual': np.full(10, -.1)}]
  heldout = {**base, 'actual': np.full(10, 100.)}
  seen = []
  def fit(groups):
    assert all(group is not heldout for group in groups)
    seen.append(len(groups))
    return np.array([0., 0., -.1])
  monkeypatch.setattr(response_model, 'prepare_coast', lambda d: d)
  monkeypatch.setattr(response_model, 'fit_coast', fit)
  response_model.inspect_coast(['a', 'b'], training, ['held'], [heldout])
  assert seen == [2, 1, 1]
  assert 'held held-out settled RMSE/bias' in capsys.readouterr().out


def test_fit_balances_routes_not_row_counts():
  coef, loss = fit_balanced([np.ones((2, 1)), np.ones((20, 1))], [np.zeros(2), np.full(20, 2.)])
  np.testing.assert_allclose(coef, [1.])
  np.testing.assert_allclose(loss, 2.)
