from unittest.mock import Mock, call

import pytest

from openpilot.selfdrive.ui.layouts.settings.lateral_maneuver import set_lateral_maneuver_mode


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
def test_eco_personality_keeps_normal_preference(monkeypatch, tmp_path, variant):
  import pyray as rl
  from pathlib import Path
  from openpilot.cereal import log
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.ui_state import UIState
  from openpilot.system.ui.lib.application import gui_app

  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  params = Params()
  params.put('LongitudinalPersonality', 0, block=True)
  Path(params.get_param_path('EcoModeEnabled')).write_text('1')
  state = object.__new__(UIState)
  state._initialize()
  state._engaged_transition_callbacks = []
  state.started = True
  message = log.SelfdriveState.new_message(personality=0)
  state.sm.data['selfdriveState'] = message
  state.sm.updated['selfdriveState'] = True
  monkeypatch.setattr(gui_app, 'texture', lambda *args, **kwargs: rl.Texture())
  monkeypatch.setattr(gui_app, 'font', lambda *args, **kwargs: rl.Font())
  if variant == 'tici':
    from openpilot.selfdrive.ui.layouts.settings import toggles
    monkeypatch.setattr(toggles, 'ui_state', state)
    layout = toggles.TogglesLayout()
    assert 'EcoModeEnabled' not in layout._toggles
    selected = layout._long_personality_setting.action_item.get_selected_button

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
      profile._handle_mouse_release(None)

  assert selected() == 0
  message.ecoMode = True
  message.personality = 2
  layout._update_state()
  assert selected() == 2
  select_standard()
  assert selected() == 1
  assert params.get('LongitudinalPersonality') == 0
  assert params.get('EcoLongitudinalPersonality') == 1
  for enabled, personality in ((False, 0), (True, 1)):
    message.ecoMode = enabled
    message.personality = personality
    layout._update_state()
    assert selected() == personality
