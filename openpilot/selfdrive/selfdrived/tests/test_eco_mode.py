import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opendbc.car.structs import car
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.constants import CV
from opendbc.car.honda.values import CAR as HONDA
from openpilot.selfdrive.selfdrived import selfdrived


@pytest.fixture
def daemon(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  params = Params()
  Path(params.get_param_path('EcoModeEnabled')).write_text('1')
  monkeypatch.setattr(selfdrived.messaging, 'PubMaster', Mock())
  monkeypatch.setattr(selfdrived.messaging, 'SubMaster', Mock(return_value=SimpleNamespace(frame=1)))
  monkeypatch.setattr(selfdrived.messaging, 'sub_sock', Mock())
  metadata = SimpleNamespace(openpilot=SimpleNamespace(comma_remote=False), tested_channel=False)
  monkeypatch.setattr(selfdrived, 'get_build_metadata', lambda: metadata)
  return selfdrived.SelfdriveD(car.CarParams.new_message(brand='honda', openpilotLongitudinalControl=True))


def poll_params(daemon, monkeypatch):
  done = threading.Event()
  monkeypatch.setattr(selfdrived.time, 'sleep', lambda _: done.set())
  daemon.params_thread(done)


def test_old_software_setting_cannot_select_eco(daemon, monkeypatch):
  with pytest.raises(UnknownKeyName):
    daemon.params.get('EcoModeEnabled')
  assert daemon.eco_mode is False
  assert daemon.factory_eco_mode is False
  poll_params(daemon, monkeypatch)
  daemon.publish_selfdriveState(car.CarState.new_message())
  assert daemon.pm.send.call_args.args[1].selfdriveState.ecoMode is False


@pytest.mark.parametrize('longitudinal,passive', [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize('initial_factory_eco', [False, True])
def test_factory_state_selects_matching_published_preference(daemon, monkeypatch, longitudinal, passive, initial_factory_eco):
  daemon.CP.openpilotLongitudinalControl = longitudinal
  daemon.CP.passive = passive
  for selected in (initial_factory_eco, not initial_factory_eco, initial_factory_eco):
    CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=selected)
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    daemon.publish_selfdriveState(CS)
    message = daemon.pm.send.call_args.args[1].selfdriveState
    enabled = selected and longitudinal and not passive
    assert message.ecoMode == enabled
    assert message.personality == (2 if enabled else 1)
    # Old stored software selections cannot override the factory switch.
    Path(daemon.params.get_param_path('EcoModeEnabled')).write_text('0' if selected else '1')
    poll_params(daemon, monkeypatch)
    assert daemon.eco_mode == enabled


def test_distance_button_saves_each_mode_independently(daemon, monkeypatch):
  assert daemon.params.get('EcoLongitudinalPersonality', return_default=True) == 2
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  monkeypatch.setattr(daemon.params, 'put', lambda key, value, **kwargs: Params.put(daemon.params, key, value, block=True))
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True)
  CS.buttonEvents = [{'type': 'gapAdjustCruise', 'pressed': False}]

  for eco, initial, changed in ((True, 2, 1), (False, 1, 0), (True, 2, 1), (False, 1, 0)):
    CS.ecoMode = eco
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    assert daemon.personality == initial
    daemon._update_personality(CS)
    assert daemon.personality == changed
    key = 'EcoLongitudinalPersonality' if eco else 'LongitudinalPersonality'
    assert daemon.params.get(key) == changed


def test_eco_entry_starts_relaxed_after_closer_selection(daemon, monkeypatch):
  daemon.params.put('EcoLongitudinalPersonality', 0, block=True)
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  monkeypatch.setattr(daemon.params, 'put', lambda key, value, **kwargs: Params.put(daemon.params, key, value, block=True))
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=True)
  CS.buttonEvents = [{'type': 'gapAdjustCruise', 'pressed': False}]

  for activation in range(2):
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    daemon.pm.send.reset_mock()
    daemon.publish_selfdriveState(CS)
    message = daemon.pm.send.call_args_list[0].args[1].selfdriveState
    assert message.ecoMode is True
    assert message.personality == 2
    assert daemon.params.get('EcoLongitudinalPersonality') == 2
    assert daemon.params.get('LongitudinalPersonality') == (0 if activation == 0 else 1)

    # A live adjustment survives repeated ECON frames and parameter polling.
    daemon._update_personality(CS)
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    assert daemon.personality == 1

    CS.ecoMode = False
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    assert daemon.personality == 1
    assert daemon.params.get('LongitudinalPersonality') == 1
    assert daemon.params.get('EcoLongitudinalPersonality') == 1
    CS.ecoMode = True


def test_factory_selection_runs_in_existing_step(daemon):
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=True)
  daemon.data_sample = Mock(return_value=CS)
  daemon.update_events = daemon.update_alerts = daemon.publish_selfdriveState = Mock()
  daemon.step()
  assert daemon.factory_eco_mode is True


@pytest.mark.parametrize('can_valid,mode_valid', [(False, True), (True, False), (False, False)])
@pytest.mark.parametrize('previous_eco', [False, True])
def test_missing_factory_state_preserves_last_valid_selection(daemon, monkeypatch, can_valid, mode_valid, previous_eco):
  daemon._update_eco_mode(car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=previous_eco))
  daemon._update_eco_mode(car.CarState.new_message(canValid=can_valid, ecoModeValid=mode_valid, ecoMode=not previous_eco))
  poll_params(daemon, monkeypatch)
  assert daemon.factory_eco_mode == previous_eco
  assert daemon.eco_mode == previous_eco


@pytest.mark.parametrize('previous_eco', [False, True])
def test_mode_switch_waits_for_matching_following_preference(daemon, monkeypatch, previous_eco):
  daemon.eco_mode = previous_eco
  daemon.personality = 2 if previous_eco else 0
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  daemon._update_eco_mode(car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=not previous_eco))
  get = daemon.params.get

  def read_with_publication(key, **kwargs):
    if key in ('LongitudinalPersonality', 'EcoLongitudinalPersonality'):
      # The native Params read releases the GIL; publication may run while it is pending.
      daemon.publish_selfdriveState(car.CarState.new_message())
    return get(key, **kwargs)

  monkeypatch.setattr(daemon.params, 'get', read_with_publication)
  poll_params(daemon, monkeypatch)
  pending = daemon.pm.send.call_args.args[1].selfdriveState
  assert pending.ecoMode == previous_eco
  assert pending.personality == (2 if previous_eco else 0)
  daemon.publish_selfdriveState(car.CarState.new_message())
  applied = daemon.pm.send.call_args.args[1].selfdriveState
  assert applied.ecoMode == (not previous_eco)
  assert applied.personality == (1 if previous_eco else 2)


def test_odyssey_speed_selects_native_profiles_and_preserves_eco(daemon, monkeypatch):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  for eco, mph, expected in ((True, 70, 2), (False, 0, 0), (False, 44.9, 0), (False, 50, 1), (False, 70, 2),
                             (False, 55, 1), (True, 30, 2), (True, 70, 2), (False, 70, 2),
                             (False, 30, 0)):
    CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=eco, vEgo=mph * CV.MPH_TO_MS)
    daemon.CS_prev = CS
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    daemon.publish_selfdriveState(CS)
    message = daemon.pm.send.call_args.args[1].selfdriveState
    assert message.personality == expected
    assert message.ecoMode == eco
    assert not daemon.events.contains(selfdrived.ET.WARNING)


@pytest.mark.parametrize('initial_mph,profile,boundary_noise,return_mph', [
  (40., 0, (44.9, 45.1, 46.9, 45.0), 47.1),
  (70., 2, (65.1, 64.9, 63.1, 65.0), 62.9),
])
def test_automatic_following_does_not_swap_near_speed_boundaries(
    daemon, monkeypatch, initial_mph, profile, boundary_noise, return_mph):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  CS = car.CarState.new_message(canValid=True, vEgo=initial_mph * CV.MPH_TO_MS)
  daemon.CS_prev = CS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == profile
  put = Mock(wraps=daemon.params.put)
  monkeypatch.setattr(daemon.params, 'put', put)

  for mph in boundary_noise * 3:
    CS.vEgo = mph * CV.MPH_TO_MS
    poll_params(daemon, monkeypatch)
    assert daemon.personality == profile
  put.assert_not_called()

  CS.vEgo = return_mph * CV.MPH_TO_MS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 1
  put.assert_called_once_with('LongitudinalPersonality', 1, block=True)
  put.reset_mock()
  for mph in (45.1, 55.1, 54.9, 64.9) * 3:
    CS.vEgo = mph * CV.MPH_TO_MS
    poll_params(daemon, monkeypatch)
    assert daemon.personality == 1
  put.assert_not_called()


@pytest.mark.parametrize('mph,profile', [(44.9, 0), (45.1, 1), (64.9, 1), (65.1, 2)])
def test_automatic_following_starts_in_the_requested_speed_band(daemon, monkeypatch, mph, profile):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  daemon.CS_prev = car.CarState.new_message(canValid=True, vEgo=mph * CV.MPH_TO_MS)
  poll_params(daemon, monkeypatch)
  assert daemon.personality == profile


@pytest.mark.parametrize('initial_mph,held_mph,profile', [(40., 46., 0), (70., 64., 2)])
@pytest.mark.parametrize('invalid', ['can', 'speed'])
def test_invalid_speed_state_does_not_discard_following_hysteresis(
    daemon, monkeypatch, initial_mph, held_mph, profile, invalid):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  CS = car.CarState.new_message(canValid=True, vEgo=initial_mph * CV.MPH_TO_MS)
  daemon.CS_prev = CS
  poll_params(daemon, monkeypatch)
  CS.vEgo = float('nan') if invalid == 'speed' else held_mph * CV.MPH_TO_MS
  CS.canValid = invalid != 'can'
  poll_params(daemon, monkeypatch)
  assert daemon.personality == profile
  CS.canValid = True
  CS.vEgo = held_mph * CV.MPH_TO_MS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == profile


@pytest.mark.parametrize('mph,expected', [(30., 0), (46., 1), (64., 1), (70., 2)])
def test_econ_exit_selects_a_fresh_speed_band(daemon, monkeypatch, mph, expected):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=True, vEgo=mph * CV.MPH_TO_MS)
  daemon.CS_prev = CS
  daemon._update_eco_mode(CS)
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 2
  CS.ecoMode = False
  daemon._update_eco_mode(CS)
  poll_params(daemon, monkeypatch)
  assert daemon.personality == expected
  assert daemon.eco_mode is False


def test_odyssey_distance_button_lasts_until_next_automatic_selection(daemon, monkeypatch):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  CS = car.CarState.new_message(canValid=True, vEgo=30 * CV.MPH_TO_MS)
  CS.buttonEvents = [{'type': 'gapAdjustCruise', 'pressed': False}]
  daemon.CS_prev = CS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 0
  monkeypatch.setattr(daemon.params, 'put', lambda key, value, **kwargs: Params.put(daemon.params, key, value, block=True))
  daemon._update_personality(CS)
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 2
  CS.vEgo = 60 * CV.MPH_TO_MS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 1
  CS.vEgo = 30 * CV.MPH_TO_MS
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 0


@pytest.mark.parametrize('fingerprint,longitudinal,passive,can_valid,speed', [
  ('HONDA_CIVIC', True, False, True, 30.),
  (HONDA.HONDA_ODYSSEY_5G_MMR, False, False, True, 30.),
  (HONDA.HONDA_ODYSSEY_5G_MMR, True, True, True, 30.),
  (HONDA.HONDA_ODYSSEY_5G_MMR, True, False, False, 30.),
  (HONDA.HONDA_ODYSSEY_5G_MMR, True, False, True, float('nan')),
])
def test_automatic_personality_requires_odyssey_longitudinal_and_valid_speed(
    daemon, monkeypatch, fingerprint, longitudinal, passive, can_valid, speed):
  daemon.CP.carFingerprint = fingerprint
  daemon.CP.openpilotLongitudinalControl = longitudinal
  daemon.CP.passive = passive
  daemon.params.put('LongitudinalPersonality', 2, block=True)
  daemon.CS_prev = car.CarState.new_message(canValid=can_valid, vEgo=speed * CV.MPH_TO_MS)
  poll_params(daemon, monkeypatch)
  assert daemon.personality == 2


def test_highway_cruise_does_not_show_econ_reminders(daemon, monkeypatch):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  daemon.initialized = True
  daemon.enabled = True
  daemon.state_machine.state = selfdrived.State.enabled
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, vEgo=70 * CV.MPH_TO_MS)
  daemon.data_sample = Mock(return_value=CS)
  daemon.update_events = lambda _: daemon.events.clear()
  clock = Mock()
  monkeypatch.setattr(selfdrived.time, 'monotonic', clock)

  for now in (0., 60., 900., 1800.):
    clock.return_value = now
    daemon.pm.send.reset_mock()
    daemon.step()
    message = daemon.pm.send.call_args_list[0].args[1].selfdriveState
    assert message.enabled
    assert message.alertSize == selfdrived.log.SelfdriveState.AlertSize.none
    assert message.alertSound == car.CarControl.HUDControl.AudibleAlert.none
    assert message.alertText1 == message.alertText2 == ''
