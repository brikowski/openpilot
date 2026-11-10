from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from openpilot.selfdrive.ui.layouts.settings.lateral_maneuver import set_lateral_maneuver_mode


@pytest.fixture
def navigation(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  from openpilot.selfdrive.ui.layouts import main
  from openpilot.system.ui.widgets import Widget

  class Layout(Widget):
    def __init__(self):
      super().__init__()
      self._setup_widget = self
      self.completed = True

    def _render(self, rect):
      pass

    set_callbacks = set_open_settings_callback = set_current_panel = lambda *args, **kwargs: None

  for name in ('Sidebar', 'HomeLayout', 'BodyLayout', 'SettingsLayout', 'AugmentedRoadView', 'OnboardingWindow'):
    monkeypatch.setattr(main, name, Layout)
  monkeypatch.setattr(main, 'Screensaver', lambda *_: None)
  monkeypatch.setattr(main.messaging, 'PubMaster', Mock())
  state = SimpleNamespace(started=False, parked=False, ignition=False, is_body=False)
  monkeypatch.setattr(main, 'ui_state', state)
  device = SimpleNamespace(add_interactive_timeout_callback=Mock())
  state.add_on_body_changed_callbacks = Mock()
  monkeypatch.setattr(main, 'device', device)
  app = main.gui_app
  monkeypatch.setattr(app, '_nav_stack', [])
  monkeypatch.setattr(app, '_nav_stack_ticks', [])
  layout = main.MainLayout()

  def tick():
    for callback in app._nav_stack_ticks:
      callback()

  return SimpleNamespace(app=app, main=main, layout=layout, state=state, tick=tick, dialog=Layout,
                         timeout=device.add_interactive_timeout_callback.call_args.args[0])


def test_started_transition_reveals_road_view_under_nested_dialogs(navigation):
  n = navigation
  n.layout.open_settings(n.main.PanelType.NETWORK)
  n.app.push_widget(n.dialog())
  n.app.push_widget(n.dialog())
  n.state.started = n.state.ignition = True
  n.tick()
  assert n.app.get_active_widget() is n.layout
  assert n.layout._current_mode == n.main.MainState.ONROAD
  assert not n.layout._sidebar.is_visible


def test_leaving_park_reveals_road_view_without_another_started_edge(navigation):
  n = navigation
  n.state.started = n.state.ignition = n.state.parked = True
  n.tick()
  n.layout.open_settings(n.main.PanelType.DEVICE)
  n.app.push_widget(n.dialog())
  n.tick()
  assert n.app.get_active_widget() is not n.layout
  n.state.parked = False
  n.tick()
  assert n.app.get_active_widget() is n.layout
  assert n.layout._current_mode == n.main.MainState.ONROAD


def test_menu_timeout_returns_to_road_view_and_dismisses_dialog(navigation):
  n = navigation
  n.state.started = n.state.ignition = True
  n.tick()
  n.layout.open_settings(n.main.PanelType.DEVICE)
  n.app.push_widget(n.dialog())
  n.tick()
  assert n.app.get_active_widget() is not n.layout
  n.timeout()
  assert n.app.get_active_widget() is n.layout
  assert n.layout._current_mode == n.main.MainState.ONROAD


@pytest.mark.parametrize('started', [False, True])
def test_transition_and_timeout_preserve_onboarding(navigation, started):
  n = navigation
  n.app.push_widget(n.layout._onboarding_window)
  n.state.started = n.state.ignition = started
  n.tick()
  n.timeout()
  assert n.app.get_active_widget() is n.layout._onboarding_window
  assert n.layout._current_mode == n.main.MainState.HOME
  n.app.pop_widget()
  n.tick()
  assert n.layout._current_mode == (n.main.MainState.ONROAD if started else n.main.MainState.HOME)


def test_parked_menu_timeout_keeps_screensaver_visible(navigation):
  n = navigation
  n.state.started = n.state.ignition = n.state.parked = True
  n.tick()
  n.layout.open_settings(n.main.PanelType.DEVICE)
  screensaver = n.dialog()
  n.app.push_widget(screensaver)
  n.timeout()
  assert n.app.get_active_widget() is screensaver


def test_ignition_and_leaving_park_do_not_bypass_system_startup(navigation):
  n = navigation
  n.state.ignition = True
  n.state.parked = False
  n.tick()
  n.timeout()
  assert n.layout._current_mode == n.main.MainState.HOME


def test_offroad_transition_updates_home_without_dismissing_dialog(navigation):
  n = navigation
  n.state.started = n.state.ignition = True
  n.tick()
  dialog = n.dialog()
  n.app.push_widget(dialog)
  n.state.started = n.state.ignition = False
  n.tick()
  assert n.app.get_active_widget() is dialog
  assert n.layout._current_mode == n.main.MainState.HOME


def test_enabling_lateral_maneuver_mode_clears_live_delay():
  params = Mock()

  set_lateral_maneuver_mode(params, True)

  assert params.method_calls == [
    call.remove("LiveDelay"),
    call.put_bool("LateralManeuverMode", True, block=True),
  ]


def test_disabling_lateral_maneuver_mode_preserves_live_delay():
  params = Mock()

  set_lateral_maneuver_mode(params, False)

  assert params.method_calls == [
    call.put_bool("LateralManeuverMode", False, block=True),
  ]


@pytest.mark.parametrize('variant', ['tici', 'mici'])
def test_following_preference_is_shared_across_eco_states(monkeypatch, tmp_path, variant):
  import raylib_nb as rl
  from pathlib import Path
  from openpilot.cereal import log
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.ui_state import UIState
  from openpilot.system.ui.lib.application import gui_app

  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  params = Params()
  params.put('LongitudinalPersonality', 0, block=True)
  Path(params.get_param_path('EcoModeEnabled')).write_text('1')
  Path(params.get_param_path('EcoLongitudinalPersonality')).write_text('2')
  state = object.__new__(UIState)
  state._initialize()
  state._engaged_transition_callbacks = []
  state.started = True
  message = log.SelfdriveState.new_message(personality=0)
  state.sm.data['selfdriveState'] = message
  state.sm.updated['selfdriveState'] = True
  monkeypatch.setattr(gui_app, 'texture', lambda *args, **kwargs: rl.Texture())
  monkeypatch.setattr(gui_app, 'font', lambda *args, **kwargs: rl.Font())
  from openpilot.selfdrive.ui.layouts.settings import initial_cruise_speed
  monkeypatch.setattr(initial_cruise_speed, 'ui_state', state)
  from openpilot.selfdrive.ui.mici.layouts.settings import initial_cruise_speed as mici_initial_cruise_speed
  monkeypatch.setattr(mici_initial_cruise_speed, 'ui_state', state)
  if variant == 'tici':
    from openpilot.selfdrive.ui.layouts.settings import toggles
    monkeypatch.setattr(toggles, 'ui_state', state)
    layout = toggles.TogglesLayout()
    assert 'EcoModeEnabled' not in layout._toggles
    def selected():
      return layout._long_personality_setting.action_item.selected_button

    def select_standard():
      layout._set_longitudinal_personality(1)
      layout._refresh_personality()
  else:
    from openpilot.selfdrive.ui.mici.layouts.settings import toggles
    monkeypatch.setattr(toggles, 'ui_state', state)
    layout = toggles.TogglesLayoutMici()
    assert 'EcoModeEnabled' not in dict(layout._refresh_toggles)
    profile = layout._personality_toggle
    monkeypatch.setattr(profile._params, 'put', lambda key, value: Params.put(profile._params, key, value, block=True))

    def selected():
      return profile._options.index(profile.value)

    def select_standard():
      profile._handle_mouse_release(None)

  assert selected() == 0
  message.ecoMode = True
  layout._update_state()
  assert selected() == 0
  select_standard()
  assert selected() == 1
  assert params.get('LongitudinalPersonality') == 1
  for enabled, personality in ((False, 1), (True, 1)):
    message.ecoMode = enabled
    message.personality = personality
    layout._update_state()
    assert selected() == personality
