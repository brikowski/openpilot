from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.display_wake import DISPLAY_TIMEOUT, DisplayWakePolicy


def step(policy, now, *, ignition=True, started=True, enabled=False, alert=None, keep_awake=False,
         touch=False, offroad_alerts=None):
  return policy.update(now, DISPLAY_TIMEOUT, ignition=ignition, started=started, enabled=enabled, alert=alert,
                       keep_awake=keep_awake, touch=touch,
                       offroad_alerts=offroad_alerts, pc=False)


def test_onroad_timeout_touch_and_alert_wake():
  assert DISPLAY_TIMEOUT == 15
  policy = DisplayWakePolicy()
  assert step(policy, 0) == (True, False)
  assert step(policy, 15) == (True, False)
  assert step(policy, 15.1) == (False, True)
  assert step(policy, 16) == (False, False)
  assert step(policy, 17, touch=True) == (True, False)
  assert step(policy, 32.1) == (False, True)

  notification = (1, 0, 'Notification', '')
  assert step(policy, 33, alert=notification) == (True, False)
  assert step(policy, 48.1, alert=notification) == (False, True)


def test_continuous_activity_hold_and_full_timeout_after_release():
  policy = DisplayWakePolicy()
  for now in (0, 15, 31, 100):
    assert step(policy, now, keep_awake=True) == (True, False)
  assert step(policy, 101) == (True, False)
  assert step(policy, 116) == (True, False)
  assert step(policy, 116.1) == (False, True)
  assert step(policy, 117, keep_awake=True) == (True, False)


def test_hold_does_not_apply_offroad_or_replace_alert_timeout():
  policy = DisplayWakePolicy()
  step(policy, 0, started=False, keep_awake=True)
  assert not step(policy, 15.1, started=False, keep_awake=True)[0]
  warning = (2, 2, 'Take control', '')
  assert step(policy, 16, alert=warning)[0]
  assert not step(policy, 31.1, alert=warning)[0]


def test_engagement_disengagement_and_ignition_transitions_wake():
  policy = DisplayWakePolicy()
  step(policy, 0)
  assert not step(policy, 31)[0]
  assert step(policy, 32, enabled=True)[0]
  assert not step(policy, 63, enabled=True)[0]
  assert step(policy, 64, enabled=False)[0]
  assert not step(policy, 95, enabled=False)[0]
  assert step(policy, 96, ignition=False, started=False, enabled=None)[0]
  assert step(policy, 127, ignition=True, started=True)[0]


def test_new_offroad_notifications_wake_but_existing_ones_do_not_hold_display_on():
  policy = DisplayWakePolicy()
  assert step(policy, 0, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 15, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert not step(policy, 15.1, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 16, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]
  assert not step(policy, 31.1, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]


@pytest.fixture
def display(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  monkeypatch.setenv('SCALE', '1')
  from openpilot.selfdrive.ui import ui_state as module

  class SubMaster(dict):
    alive = {'carState': True, 'selfdriveState': True, 'radarState': True}
    valid = {'carState': True, 'selfdriveState': True, 'radarState': True}
    recv_frame = {'carState': 100, 'selfdriveState': 100, 'radarState': 100}

  sm = SubMaster(carState=SimpleNamespace(cruiseState=SimpleNamespace(enabled=False)),
                selfdriveState=SimpleNamespace(enabled=False, alertSize=SimpleNamespace(raw=0)),
                radarState=SimpleNamespace(leadOne=SimpleNamespace(present=False), leadTwo=SimpleNamespace(present=False)))
  state = SimpleNamespace(started=True, ignition=True, alpha_long_enabled=False, started_frame=100, sm=sm,
                          light_sensor=-1, params=SimpleNamespace(get=lambda _: None, get_bool=lambda _: False))
  monkeypatch.setattr(module, 'ui_state', state)
  monkeypatch.setattr(module, 'gui_app', SimpleNamespace(target_fps=20, mouse_events=[], set_should_render=lambda _: None))
  monkeypatch.setattr(module, 'PC', False)
  device = module.Device()
  monkeypatch.setattr(module.HARDWARE, 'set_display_power', lambda _: None)
  now = [0.0]
  monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
  return state, device, now


@pytest.mark.parametrize('cruise,alpha,engaged',
                         [(c, a, e) for c in (False, True) for a in (False, True) for e in (False, True)])
def test_cruise_without_lead_or_popup_still_times_out(display, cruise, alpha, engaged):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.sm['selfdriveState'].enabled = engaged
  state.alpha_long_enabled = alpha
  device._update_wakefulness()
  now[0] = 18
  device._update_wakefulness()
  assert not device.awake


@pytest.mark.parametrize('lead', ['leadOne', 'leadTwo'])
@pytest.mark.parametrize('cruise,alpha', [(c, a) for c in (False, True) for a in (False, True)])
def test_lead_holds_alpha_cruise_display_and_restarts_timeout_after_loss(display, lead, cruise, alpha):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.alpha_long_enabled = alpha
  selected = getattr(state.sm['radarState'], lead)
  selected.present = True
  device._update_wakefulness()
  now[0] = 30
  device._update_wakefulness()
  assert device.awake == (cruise and alpha)
  if not (cruise and alpha):
    return
  selected.present = False
  now[0] = 31
  device._update_wakefulness()
  assert device.awake
  now[0] = 46
  device._update_wakefulness()
  assert device.awake
  now[0] = 49
  device._update_wakefulness()
  assert not device.awake
  selected.present = True
  now[0] = 50
  device._update_wakefulness()
  assert device.awake


def test_popup_and_lead_must_both_clear_before_alpha_cruise_timeout(display):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = True
  state.alpha_long_enabled = True
  state.sm['radarState'].leadOne.present = True
  ss = state.sm['selfdriveState']
  ss.alertSize.raw = 1
  ss.alertStatus = SimpleNamespace(raw=0)
  ss.alertText1, ss.alertText2 = 'Notification', ''
  for timestamp in (0, 15, 60):
    now[0] = timestamp
    device._update_wakefulness()
    assert device.awake
  state.sm['radarState'].leadOne.present = False
  now[0] = 61
  device._update_wakefulness()
  now[0] = 90
  device._update_wakefulness()
  assert device.awake
  ss.alertSize.raw = 0
  now[0] = 91
  device._update_wakefulness()
  now[0] = 106
  device._update_wakefulness()
  assert device.awake
  now[0] = 109
  device._update_wakefulness()
  assert not device.awake
  ss.alertSize.raw = 1
  now[0] = 110
  device._update_wakefulness()
  assert device.awake


@pytest.mark.parametrize('unreliable', ['stale', 'invalid', 'previous_drive'])
def test_unreliable_cruise_state_releases_display_hold(display, unreliable):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = True
  state.alpha_long_enabled = True
  state.sm['radarState'].leadOne.present = True
  device._update_wakefulness()
  now[0] = 30
  device._update_wakefulness()
  assert device.awake
  if unreliable == 'stale':
    state.sm.alive['carState'] = False
  elif unreliable == 'invalid':
    state.sm.valid['carState'] = False
  else:
    state.sm.recv_frame['carState'] = state.started_frame - 1
  now[0] = 31
  device._update_wakefulness()
  now[0] = 49
  device._update_wakefulness()
  assert not device.awake


@pytest.mark.parametrize('unreliable', ['stale', 'invalid', 'previous_drive'])
def test_unreliable_lead_cannot_hold_alpha_cruise_display(display, unreliable):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = True
  state.alpha_long_enabled = True
  state.sm['radarState'].leadOne.present = True
  device._update_wakefulness()
  now[0] = 30
  device._update_wakefulness()
  assert device.awake
  if unreliable == 'stale':
    state.sm.alive['radarState'] = False
  elif unreliable == 'invalid':
    state.sm.valid['radarState'] = False
  else:
    state.sm.recv_frame['radarState'] = state.started_frame - 1
  now[0] = 31
  device._update_wakefulness()
  now[0] = 49
  device._update_wakefulness()
  assert not device.awake


@pytest.mark.parametrize('onroad', [False, True])
def test_timeout_applies_onroad_and_offroad_and_touch_restarts_it(display, onroad):
  from openpilot.selfdrive.ui import ui_state as module

  state, device, now = display
  state.started = onroad
  state.ignition = onroad
  state.params = SimpleNamespace(get=lambda _: None, get_bool=lambda _: False)
  device._update_wakefulness()
  now[0] = 18
  device._update_wakefulness()
  assert not device.awake
  module.gui_app.mouse_events = [SimpleNamespace(left_down=True)]
  now[0] = 19
  device._update_wakefulness()
  assert device.awake
  module.gui_app.mouse_events = []
  now[0] = 34
  device._update_wakefulness()
  assert device.awake
  now[0] = 37
  device._update_wakefulness()
  assert not device.awake


@pytest.fixture
def backlight(display, monkeypatch):
  from openpilot.selfdrive.ui import ui_state as module

  _, device, now = display
  power, render = [], []
  monkeypatch.setattr(device, '_start_brightness_thread', lambda: None)
  monkeypatch.setattr(module.HARDWARE, 'set_display_power', lambda on: power.append((now[0], on)))
  monkeypatch.setattr(module.gui_app, 'set_should_render', lambda on: render.append((now[0], on)))
  return power, render


@pytest.mark.parametrize('onroad', [False, True])
@pytest.mark.parametrize('brightness', [30, 100])
def test_idle_backlight_fades_before_panel_and_rendering_stop(display, backlight, onroad, brightness):
  state, device, now = display
  power, render = backlight
  state.started = state.ignition = onroad
  device.set_offroad_brightness(brightness)
  device._brightness_filter.x = brightness
  callbacks = []
  device.add_interactive_timeout_callback(lambda: callbacks.append(now[0]))
  device.update()

  levels = []
  for timestamp in (15, 15.4, 16, 16.6, 17, 18):
    now[0] = timestamp
    device.update()
    levels.append(device._brightness_target)
    assert device.awake == (timestamp < 17)
  assert levels == [brightness, round(brightness * 0.8), round(brightness * 0.5), round(brightness * 0.2), 0, 0]
  assert power == render == [(17, False)]
  assert callbacks == [15.4]


@pytest.mark.parametrize('wake', ['touch', 'popup', 'lead'])
@pytest.mark.parametrize('timestamp', [16, 18])
def test_activity_restores_backlight_in_same_update_during_fade_or_sleep(display, backlight, wake, timestamp):
  from openpilot.selfdrive.ui import ui_state as module

  state, device, now = display
  power, render = backlight
  state.alpha_long_enabled = state.sm['carState'].cruiseState.enabled = True
  device.set_offroad_brightness(80)
  device._brightness_filter.x = 80
  device.update()
  now[0] = timestamp
  device.update()
  assert device._brightness_target < 80
  was_awake = device.awake
  power.clear()
  render.clear()

  if wake == 'touch':
    module.gui_app.mouse_events = [SimpleNamespace(left_down=True)]
  elif wake == 'popup':
    ss = state.sm['selfdriveState']
    ss.alertSize.raw = 1
    ss.alertStatus = SimpleNamespace(raw=0)
    ss.alertText1, ss.alertText2 = 'Take control', ''
  else:
    state.sm['radarState'].leadOne.present = True
  now[0] += 0.05
  device.update()
  assert device.awake
  assert device._brightness_target == 80
  assert power == render == ([] if was_awake else [(now[0], True)])
  assert device._wake_policy.deadline == now[0] + DISPLAY_TIMEOUT


def test_delayed_ui_update_finishes_fade_without_extending_idle_time(display, backlight):
  _, device, now = display
  device.update()
  now[0] = 30
  device.update()
  assert not device.awake
  assert device._brightness_target == 0
  assert backlight[0] == backlight[1] == [(30, False)]


def test_pc_display_remains_bright_after_idle_timeout(display, backlight, monkeypatch):
  from openpilot.selfdrive.ui import ui_state as module

  _, device, now = display
  monkeypatch.setattr(module, 'PC', True)
  device.set_offroad_brightness(80)
  device._brightness_filter.x = 80
  device.update()
  now[0] = 30
  device.update()
  assert device.awake
  assert device._brightness_target == 80
  assert backlight == ([], [])


@pytest.mark.parametrize('variant', ['tizi', 'mici'])
def test_screen_timeout_has_no_setting_and_ignores_legacy_value(display, monkeypatch, variant):
  import pyray as rl
  from pathlib import Path
  from openpilot.common.params import Params, UnknownKeyName
  from openpilot.selfdrive.ui import ui_state as module
  from openpilot.system.ui.lib.application import gui_app

  params = Params()
  with pytest.raises(UnknownKeyName):
    params.get('ScreenTimeoutEnabled')
  Path(params.get_param_path('ScreenTimeoutEnabled')).write_text('0')
  state = object.__new__(module.UIState)
  state._initialize()
  monkeypatch.setattr(state, 'usb_connected', False)
  monkeypatch.setattr(state, '_engaged_transition_callbacks', [])
  monkeypatch.setattr(module, 'cable_connected', lambda: False)
  monkeypatch.setattr(gui_app, 'texture', lambda *args, **kwargs: rl.Texture())
  monkeypatch.setattr(gui_app, 'font', lambda *args, **kwargs: rl.Font())
  from openpilot.selfdrive.ui.layouts.settings import initial_cruise_speed
  monkeypatch.setattr(initial_cruise_speed, 'ui_state', state)
  from openpilot.selfdrive.ui.mici.layouts.settings import initial_cruise_speed as mici_initial_cruise_speed
  monkeypatch.setattr(mici_initial_cruise_speed, 'ui_state', state)
  if variant == 'tizi':
    from openpilot.selfdrive.ui.layouts.settings import toggles
    monkeypatch.setattr(toggles, 'ui_state', state)
    layout = toggles.TogglesLayout()
    assert 'ScreenTimeoutEnabled' not in layout._toggles
  else:
    from openpilot.selfdrive.ui.mici.layouts.settings import toggles as mici_toggles
    monkeypatch.setattr(mici_toggles, 'ui_state', state)
    layout = mici_toggles.TogglesLayoutMici()
    assert 'ScreenTimeoutEnabled' not in dict(layout._refresh_toggles)
  state.update_params()
  layout._update_toggles()
  assert not hasattr(state, 'screen_timeout_enabled')
  assert params.get('OnroadCycleRequested') is None
