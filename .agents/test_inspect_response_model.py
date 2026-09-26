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


def test_coast_transition_bins_require_fresh_same_domain_rows():
  joint = {'t': np.arange(8) * .02, 'eligible': np.array([1, 0, 1, 1, 1, 1, 1, 1], dtype=bool),
           'domain': np.array([0, 0, 0, 1, 0, 0, 0, 0]),
           'age': np.array([0., .02, .1, .12, .3, .32, .6, .62])}
  coast = {'t': np.arange(16) * .01,
           'opportunity': np.ones(16, dtype=bool)}
  coast['opportunity'][10] = False
  masks = response_model.coast_transition_bins(joint, coast)
  assert {name: np.flatnonzero(mask).tolist() for name, mask in masks.items()} == {
    '0-.1': [0], '.1-.3': [2], '.3-.6': [4], '.6+': [6, 7]}
  coast['t'][4] += .01
  with pytest.raises(ValueError, match='timelines'):
    response_model.coast_transition_bins(joint, coast)


def test_coast_transition_reports_tail_and_typical_error_separately():
  predicted = np.array([0., .2, 1., 100.])
  actual = np.zeros(4)
  selected = np.array([True, True, True, False])
  assert response_model.transition_error_stats(predicted, actual, selected) == (
    .5888, .4, .2, .84)


def test_coast_transition_fits_training_only(monkeypatch, capsys):
  train, evaluation = object(), object()
  t = np.arange(4) * .01
  train_coast = {'t': t, 'opportunity': np.ones(4, dtype=bool), 'context': np.ones((4, 3))}
  eval_coast = {**train_coast, 'context': np.full((4, 3), 10000.)}
  train_joint = {'t': t[::2], 'eligible': np.ones(2, dtype=bool), 'domain': np.zeros(2, dtype=int),
                 'age': np.array([0., .2]), 'actual': np.ones(2)}
  eval_joint = {**train_joint, 'actual': np.full(2, 10000.)}
  monkeypatch.setattr(response_model, 'prepare_coast', lambda d: train_coast if d is train else eval_coast)
  monkeypatch.setattr(response_model, 'prepare_joint', lambda d: train_joint if d is train else eval_joint)
  def fit_coast(training):
    assert training == [train_coast]
    return np.zeros(3)
  def fit_joint(training, carry):
    assert training == [train_joint]
    return ((0., 0.), (0., 0.)), np.zeros(5)
  monkeypatch.setattr(response_model, 'fit_coast', fit_coast)
  monkeypatch.setattr(response_model, 'fit_joint_model', fit_joint)
  monkeypatch.setattr(response_model, 'joint_matrix', lambda d, *args: np.zeros((len(d['t']), 5)))
  response_model.inspect_coast_transition(['train'], [train], ['eval'], [evaluation])
  assert 'eval held-out coast age' in capsys.readouterr().out


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


def test_torque_alignment_requires_an_actual_recent_receive_update():
  data = {'t': np.array([-.01, 0., .02, .04, .10]), 't0': 0.}
  updates = np.array([0., .04])
  values = np.array([[-130., 0.], [-180., 0.]])
  held = response_model.latest_received_torque(data, updates, values)
  np.testing.assert_allclose(held['engine_torque_rx'], [np.nan, -130., -130., -180., -180.])
  np.testing.assert_array_equal(held['torque_rx_fresh'], [False, True, True, True, False])
  values[1, 0] = 999.
  changed = response_model.latest_received_torque(data, updates, values)
  np.testing.assert_allclose(changed['engine_torque_rx'][:3], held['engine_torque_rx'][:3])


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


def trim_forecast_data():
  t = np.arange(0., 4., .01)
  return {'t': t, 'request': np.ones(len(t)), 'aego': np.ones(len(t)),
          'active': np.ones(len(t), dtype=bool), 'pid': np.ones(len(t), dtype=bool),
          'gas_pressed': np.zeros(len(t), dtype=bool),
          'brake_pressed': np.zeros(len(t), dtype=bool),
          'response_state_fresh': np.ones(len(t), dtype=bool),
          'gas_command': np.full(len(t), 1000.),
          'brake_request': np.zeros(len(t), dtype=bool),
          'vego': np.full(len(t), 15.), 'pitch': np.zeros(len(t)),
          'gear': np.full(len(t), 5.)}


def test_trim_forecast_uses_future_only_as_label_not_predictor():
  data = trim_forecast_data()
  baseline = response_model.trim_forecast_rows(data)
  before = np.flatnonzero(np.isclose(baseline['t'], 1.))[0]
  future = np.searchsorted(data['t'], 1.6, side='left')
  data['aego'][future] = 1.4
  changed = response_model.trim_forecast_rows(data)
  after = np.flatnonzero(np.isclose(changed['t'], 1.))[0]
  assert changed['actual_future'][after] == pytest.approx(.4)
  assert changed['current'][after] == baseline['current'][before]
  assert changed['delay_aligned'][after] == baseline['delay_aligned'][before]


def test_trim_forecast_rejects_intervening_domain_and_gear_changes():
  data = trim_forecast_data()
  assert np.any(np.isclose(response_model.trim_forecast_rows(data)['t'], 1.))
  data['gas_command'][120] = -30000.
  assert not np.any(np.isclose(response_model.trim_forecast_rows(data)['t'], 1.))
  data['gas_command'][120] = 1000.
  data['gear'][120] = 4.
  assert not np.any(np.isclose(response_model.trim_forecast_rows(data)['t'], 1.))
  data['gear'][120] = 5.
  data['response_state_fresh'][120] = False
  assert not np.any(np.isclose(response_model.trim_forecast_rows(data)['t'], 1.))
  data['response_state_fresh'][120] = True
  data['request'][120] = 1.2
  assert not np.any(np.isclose(response_model.trim_forecast_rows(data)['t'], 1.))


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


def test_exploratory_brake_release_requires_rising_request_and_restores_strong_brake():
  t = np.arange(0., 3.5, .01)
  request = np.full(len(t), -.4)
  first = (t >= 1.) & (t < 2.)
  second = (t >= 2.3) & (t < 3.)
  request[first] = -.28 + .26 * (t[first] - 1.)
  request[second] = -.28 + .26 * (t[second] - 2.3)
  original_request = request.copy()
  d = {'t': t, 'request': request, 'brake_request': (t >= .5) & (t < 3.),
       'aego': np.full(len(t), -.8), 'active': np.ones(len(t), dtype=bool),
       'pid': np.ones(len(t), dtype=bool), 'gas_pressed': np.zeros(len(t), dtype=bool),
       'brake_pressed': np.zeros(len(t), dtype=bool), 'response_state_fresh': np.ones(len(t), dtype=bool),
       'vego': np.full(len(t), 20.), 'gear': np.full(len(t), 6.)}
  release, events = response_model.exploratory_brake_release(d)
  assert len(events) == 1
  assert not release[90] and release[140]
  assert not release[210] and release[270]
  assert not release[310]
  d['request'][:] = -.2
  assert not response_model.exploratory_brake_release(d)[0].any()
  d['aego'][:] = request
  assert not response_model.exploratory_brake_release(d)[0].any()
  with pytest.raises(ValueError, match='positive'):
    response_model.exploratory_brake_release(d, 0.)
  d['request'] = original_request
  d['aego'][:] = -.8
  d['engine_torque_rx'] = -100. - 200. * t
  d['car_gas_rx'] = np.zeros(len(t))
  d['torque_rx_fresh'] = np.ones(len(t), dtype=bool)
  assert response_model.exploratory_brake_release(d, torque_drop=25.)[0].any()
  d['engine_torque_rx'][:] = -100.
  assert not response_model.exploratory_brake_release(d, torque_drop=25.)[0].any()
  d['engine_torque_rx'] = -100. - 200. * t
  d['torque_rx_fresh'][:] = False
  assert not response_model.exploratory_brake_release(d, torque_drop=25.)[0].any()
  with pytest.raises(ValueError, match='positive'):
    response_model.exploratory_brake_release(d, torque_drop=0.)


def test_release_screen_fits_only_other_training_routes(monkeypatch):
  raw = [{'t': np.arange(4) * .02, 'request': np.zeros(4)} for _ in range(3)]
  prepared = [{'t': d['t'][::2], 'brake': np.zeros(2), 'domain': np.zeros(2, dtype=int),
               'actual': np.zeros(2), 'mask': np.ones(2, dtype=bool)} for d in raw]
  seen = []
  monkeypatch.setattr(response_model, 'prepare_joint', lambda d: prepared[next(i for i, item in enumerate(raw) if item is d)])
  monkeypatch.setattr(response_model, 'exploratory_brake_release', lambda d, margin, torque: (np.zeros(4, dtype=bool), []))
  monkeypatch.setattr(response_model, 'joint_matrix', lambda p, *args: np.zeros((len(p['t']), 5)))
  def fit(groups):
    assert all(group is not prepared[2] for group in groups)
    seen.append(len(groups))
    return ((0., 0.), (0., 0.)), np.zeros(5)
  monkeypatch.setattr(response_model, 'fit_joint_model', fit)
  response_model.inspect_brake_release(['a', 'b'], raw[:2], ['held'], raw[2:])
  assert seen == [1, 1, 2]


def test_fit_balances_routes_not_row_counts():
  coef, loss = fit_balanced([np.ones((2, 1)), np.ones((20, 1))], [np.zeros(2), np.full(20, 2.)])
  np.testing.assert_allclose(coef, [1.])
  np.testing.assert_allclose(loss, 2.)
