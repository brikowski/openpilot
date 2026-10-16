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


def test_continuous_cruise_hold_and_full_timeout_after_release():
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
    alive = {'carState': True, 'selfdriveState': True}
    valid = {'carState': True, 'selfdriveState': True}
    recv_frame = {'carState': 100, 'selfdriveState': 100}

  sm = SubMaster(carState=SimpleNamespace(cruiseState=SimpleNamespace(enabled=False)),
                selfdriveState=SimpleNamespace(enabled=False, alertSize=SimpleNamespace(raw=0)))
  state = SimpleNamespace(started=True, ignition=True, alpha_long_enabled=False, started_frame=100, sm=sm)
  monkeypatch.setattr(module, 'ui_state', state)
  monkeypatch.setattr(module, 'gui_app', SimpleNamespace(target_fps=20, mouse_events=[]))
  monkeypatch.setattr(module, 'PC', False)
  device = module.Device()
  monkeypatch.setattr(device, '_set_awake', lambda awake: setattr(device, '_awake', awake))
  now = [0.0]
  monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
  return state, device, now


@pytest.mark.parametrize('cruise,alpha,engaged',
                         [(c, a, e) for c in (False, True) for a in (False, True) for e in (False, True)])
def test_display_uses_cruise_and_alpha_long(display, cruise, alpha, engaged):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = cruise
  state.sm['selfdriveState'].enabled = engaged
  state.alpha_long_enabled = alpha
  device._update_wakefulness()
  now[0] = 15.1
  device._update_wakefulness()
  assert device.awake == (cruise and alpha)


@pytest.mark.parametrize('unreliable', ['stale', 'invalid', 'previous_drive'])
def test_unreliable_cruise_state_releases_display_hold(display, unreliable):
  state, device, now = display
  state.sm['carState'].cruiseState.enabled = True
  state.alpha_long_enabled = True
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
  now[0] = 46.1
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
  now[0] = 15.1
  device._update_wakefulness()
  assert not device.awake
  module.gui_app.mouse_events = [SimpleNamespace(left_down=True)]
  now[0] = 16
  device._update_wakefulness()
  assert device.awake
  module.gui_app.mouse_events = []
  now[0] = 31
  device._update_wakefulness()
  assert device.awake
  now[0] = 31.1
  device._update_wakefulness()
  assert not device.awake


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
