from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.display_wake import DISPLAY_TIMEOUT, DisplayWakePolicy


def step(policy, now, *, ignition=True, started=True, enabled=False, alert=None,
         touch=False, offroad_alerts=None):
  return policy.update(now, DISPLAY_TIMEOUT, ignition=ignition, started=started, enabled=enabled, alert=alert,
                       touch=touch, offroad_alerts=offroad_alerts, pc=False)


def test_onroad_timeout_touch_and_alert_wake():
  assert DISPLAY_TIMEOUT == 60
  policy = DisplayWakePolicy()
  assert step(policy, 0) == (True, False)
  assert step(policy, 60) == (True, False)
  assert step(policy, 60.1) == (False, True)
  assert step(policy, 61) == (False, False)
  assert step(policy, 62, touch=True) == (True, False)
  assert step(policy, 122.1) == (False, True)

  notification = (1, 0, 'Notification', '')
  assert step(policy, 123, alert=notification) == (True, False)
  assert step(policy, 184, alert=notification) == (True, False)
  assert step(policy, 185) == (True, False)
  assert step(policy, 245) == (True, False)
  assert step(policy, 245.1) == (False, True)


def test_offroad_alert_argument_does_not_hold_display_on():
  policy = DisplayWakePolicy()
  warning = (2, 2, 'Take control', '')
  assert step(policy, 0, started=False, alert=warning)[0]
  assert not step(policy, DISPLAY_TIMEOUT + .1, started=False, alert=warning)[0]


@pytest.mark.parametrize('name', ['leadDeparting', 'trafficReady'])
def test_departure_popup_wakes_a_sleeping_display_and_then_allows_sleep(display, name):
  from openpilot.cereal import log
  from openpilot.selfdrive.selfdrived.events import EVENTS, ET

  state, device, now = display
  device._update_wakefulness()
  now[0] = DISPLAY_TIMEOUT + 3
  device._update_wakefulness()
  assert not device.awake
  popup = EVENTS[getattr(log.OnroadEvent.EventName, name)][ET.PERMANENT]
  ss = state.sm['selfdriveState']
  ss.alertSize.raw, ss.alertStatus.raw = int(popup.alert_size), int(popup.alert_status)
  ss.alertText1, ss.alertText2 = popup.alert_text_1, popup.alert_text_2
  device._update_wakefulness()
  assert device.awake
  assert ss.alertStatus.raw == 0
  now[0] += 3.1
  ss.alertSize.raw = 0
  device._update_wakefulness()
  now[0] += DISPLAY_TIMEOUT + 3
  device._update_wakefulness()
  assert not device.awake


def test_engagement_disengagement_and_ignition_transitions_wake():
  policy = DisplayWakePolicy()
  step(policy, 0)
  assert not step(policy, 61)[0]
  assert step(policy, 62, enabled=True)[0]
  assert not step(policy, 123, enabled=True)[0]
  assert step(policy, 124, enabled=False)[0]
  assert not step(policy, 185, enabled=False)[0]
  assert step(policy, 186, ignition=False, started=False, enabled=None)[0]
  assert step(policy, 247, ignition=True, started=True)[0]


def test_new_offroad_notifications_wake_but_existing_ones_do_not_hold_display_on():
  policy = DisplayWakePolicy()
  assert step(policy, 0, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 60, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert not step(policy, 60.1, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 61, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]
  assert not step(policy, 121.1, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]


@pytest.fixture
def display(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  monkeypatch.setenv('SCALE', '1')
  from openpilot.selfdrive.ui import ui_state as module

  class SubMaster(dict):
    alive = {'carState': True, 'selfdriveState': True, 'radarState': True}
    valid = {'carState': True, 'selfdriveState': True, 'radarState': True}
    recv_frame = {'carState': 100, 'selfdriveState': 100, 'radarState': 100}
    updated = {'selfdriveState': True}
    recv_time = {'selfdriveState': 0.0}

  sm = SubMaster(carState=SimpleNamespace(cruiseState=SimpleNamespace(enabled=False)),
                selfdriveState=SimpleNamespace(enabled=False, alertSize=SimpleNamespace(raw=0),
                                               alertStatus=SimpleNamespace(raw=0), alertText1='', alertText2=''),
                radarState=SimpleNamespace(leadOne=SimpleNamespace(present=False), leadTwo=SimpleNamespace(present=False)))
  state = SimpleNamespace(started=True, ignition=True, alpha_long_enabled=False, started_frame=100, started_time=0., sm=sm,
                          light_sensor=-1, params=SimpleNamespace(get=lambda _: None, get_bool=lambda _: False))
  monkeypatch.setattr(module, 'ui_state', state)
  monkeypatch.setattr(module, 'gui_app', SimpleNamespace(target_fps=20, mouse_events=[], set_should_render=lambda _: None))
  monkeypatch.setattr(module, 'PC', False)
  from openpilot.selfdrive.ui.onroad import alert_renderer
  monkeypatch.setattr(alert_renderer, 'ui_state', state)
  monkeypatch.setattr(alert_renderer, 'COMMA_HARDWARE', False)
  device = module.Device()
  monkeypatch.setattr(module.HARDWARE, 'set_display_power', lambda _: None)
  now = [0.0]
  monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
  return state, device, now


@pytest.mark.parametrize('cruise,alpha', [(c, a) for c in (False, True) for a in (False, True)])
@pytest.mark.parametrize('status', [0, 1, 2])
def test_active_onroad_alert_cannot_fade_or_sleep(display, backlight, cruise, alpha, status):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.alpha_long_enabled = alpha
  ss = state.sm['selfdriveState']
  device.set_offroad_brightness(80)
  device._brightness_filter.x = 80
  device.update()
  now[0] = DISPLAY_TIMEOUT + 3
  device.update()
  assert not device.awake
  ss.alertSize.raw, ss.alertStatus.raw, ss.alertText1 = 1, status, 'Attention required'
  for timestamp in (64, 100, 200):
    now[0] = timestamp
    device.update()
    assert device.awake and device._brightness_target == 80
  ss.alertSize.raw = 0
  now[0] = 201
  device.update()
  now[0] = 264
  device.update()
  assert not device.awake


@pytest.mark.parametrize('startup', [False, True])
def test_generated_system_alert_wakes_and_holds_display(display, backlight, monkeypatch, startup):
  from openpilot.selfdrive.ui.onroad import alert_renderer

  state, device, now = display
  monkeypatch.setattr(alert_renderer, 'COMMA_HARDWARE', True)
  state.sm['selfdriveState'].enabled = not startup
  device.update()
  now[0] = DISPLAY_TIMEOUT + 3
  device.update()
  assert not device.awake
  state.sm.updated['selfdriveState'] = state.sm.alive['selfdriveState'] = False
  if startup:
    state.sm.recv_frame['selfdriveState'] = state.started_frame - 1
  for timestamp in (64, 100, 200):
    now[0] = timestamp
    device.update()
    assert device.awake and device._brightness_target > 0


@pytest.mark.parametrize('cruise,alpha,engaged',
                         [(c, a, e) for c in (False, True) for a in (False, True) for e in (False, True)])
def test_cruise_and_engagement_do_not_hold_display_on(display, cruise, alpha, engaged):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.sm['selfdriveState'].enabled = engaged
  state.alpha_long_enabled = alpha
  device._update_wakefulness()
  now[0] = DISPLAY_TIMEOUT + 3
  device._update_wakefulness()
  assert not device.awake


@pytest.mark.parametrize('lead', ['leadOne', 'leadTwo'])
@pytest.mark.parametrize('cruise,alpha', [(c, a) for c in (False, True) for a in (False, True)])
def test_lead_presence_changes_do_not_reset_timeout_or_wake(display, lead, cruise, alpha):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.alpha_long_enabled = alpha
  selected = getattr(state.sm['radarState'], lead)
  device._update_wakefulness()
  now[0] = DISPLAY_TIMEOUT - 1
  selected.present = True
  device._update_wakefulness()
  now[0] = DISPLAY_TIMEOUT + 3
  device._update_wakefulness()
  assert not device.awake
  for timestamp, present in ((DISPLAY_TIMEOUT + 4, False), (DISPLAY_TIMEOUT + 5, True)):
    now[0] = timestamp
    selected.present = present
    device._update_wakefulness()
    assert not device.awake


@pytest.mark.parametrize('lead_present', [False, True])
def test_popup_holds_display_and_full_timeout_starts_after_it_clears(display, lead_present):
  state, device, now = display
  state.alpha_long_enabled = state.sm['carState'].cruiseState.enabled = True
  state.sm['radarState'].leadOne.present = lead_present
  ss = state.sm['selfdriveState']
  ss.alertSize.raw = 1
  ss.alertText1 = 'Notification'
  for timestamp in (0, 60, 120):
    now[0] = timestamp
    device._update_wakefulness()
    assert device.awake
  ss.alertSize.raw = 0
  now[0] = 121
  device._update_wakefulness()
  now[0] = 181
  device._update_wakefulness()
  assert device.awake
  now[0] = 184
  device._update_wakefulness()
  assert not device.awake


@pytest.mark.parametrize('onroad', [False, True])
def test_timeout_applies_onroad_and_offroad_and_touch_restarts_it(display, onroad):
  from openpilot.selfdrive.ui import ui_state as module

  state, device, now = display
  state.started = state.ignition = onroad
  device._update_wakefulness()
  now[0] = DISPLAY_TIMEOUT + 3
  device._update_wakefulness()
  assert not device.awake
  module.gui_app.mouse_events = [SimpleNamespace(left_down=True)]
  now[0] = 64
  device._update_wakefulness()
  assert device.awake
  module.gui_app.mouse_events = []
  now[0] = 124
  device._update_wakefulness()
  assert device.awake
  now[0] = 127
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
  for offset in (0, .4, 1, 1.6, 2, 3):
    now[0] = DISPLAY_TIMEOUT + offset
    device.update()
    levels.append(device._brightness_target)
    assert device.awake == (offset < 2)
  assert levels == [brightness, round(brightness * 0.8), round(brightness * 0.5), round(brightness * 0.2), 0, 0]
  assert power == render == [(DISPLAY_TIMEOUT + 2, False)]
  assert callbacks == [DISPLAY_TIMEOUT + .4]


@pytest.mark.parametrize('wake', ['touch', 'popup'])
@pytest.mark.parametrize('offset', [1, 3])
def test_activity_restores_backlight_in_same_update_during_fade_or_sleep(display, backlight, wake, offset):
  from openpilot.selfdrive.ui import ui_state as module

  state, device, now = display
  power, render = backlight
  state.alpha_long_enabled = state.sm['carState'].cruiseState.enabled = True
  device.set_offroad_brightness(80)
  device._brightness_filter.x = 80
  device.update()
  now[0] = DISPLAY_TIMEOUT + offset
  device.update()
  assert device._brightness_target < 80
  was_awake = device.awake
  power.clear()
  render.clear()

  if wake == 'touch':
    module.gui_app.mouse_events = [SimpleNamespace(left_down=True)]
  else:
    ss = state.sm['selfdriveState']
    ss.alertSize.raw = 1
    ss.alertText1 = 'Take control'
  now[0] += .05
  device.update()
  assert device.awake
  assert device._brightness_target == 80
  assert power == render == ([] if was_awake else [(now[0], True)])
  assert device._wake_policy.deadline == now[0] + DISPLAY_TIMEOUT


def test_delayed_ui_update_finishes_fade_without_extending_idle_time(display, backlight):
  _, device, now = display
  device.update()
  now[0] = DISPLAY_TIMEOUT + 10
  device.update()
  assert not device.awake
  assert device._brightness_target == 0
  assert backlight[0] == backlight[1] == [(DISPLAY_TIMEOUT + 10, False)]


def test_pc_display_remains_bright_after_idle_timeout(display, backlight, monkeypatch):
  from openpilot.selfdrive.ui import ui_state as module

  _, device, now = display
  monkeypatch.setattr(module, 'PC', True)
  device.set_offroad_brightness(80)
  device._brightness_filter.x = 80
  device.update()
  now[0] = DISPLAY_TIMEOUT + 10
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
