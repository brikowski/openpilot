from unittest.mock import Mock, call

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
