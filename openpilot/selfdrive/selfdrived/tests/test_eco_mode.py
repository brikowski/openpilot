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
  Path(params.get_param_path('EcoLongitudinalPersonality')).write_text('2')
  monkeypatch.setattr(selfdrived.messaging, 'PubMaster', Mock())
  monkeypatch.setattr(selfdrived.messaging, 'SubMaster', Mock(return_value=SimpleNamespace(frame=1, updated={'driverAssistance': False})))
  monkeypatch.setattr(selfdrived.messaging, 'sub_sock', Mock())
  metadata = SimpleNamespace(openpilot=SimpleNamespace(comma_remote=False), tested_channel=False)
  monkeypatch.setattr(selfdrived, 'get_build_metadata', lambda: metadata)
  return selfdrived.SelfdriveD(car.CarParams.new_message(brand='honda', openpilotLongitudinalControl=True))


def poll_params(daemon, monkeypatch):
  done = threading.Event()
  monkeypatch.setattr(selfdrived.time, 'sleep', lambda _: done.set())
  daemon.params_thread(done)


def test_old_software_setting_cannot_select_eco(daemon, monkeypatch):
  for key in ('EcoModeEnabled', 'EcoLongitudinalPersonality'):
    with pytest.raises(UnknownKeyName):
      daemon.params.get(key)
  assert daemon.eco_mode is False
  poll_params(daemon, monkeypatch)
  daemon.publish_selfdriveState(car.CarState.new_message())
  assert daemon.pm.send.call_args.args[1].selfdriveState.ecoMode is False


@pytest.mark.parametrize('longitudinal,passive', [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize('initial_factory_eco', [False, True])
@pytest.mark.parametrize('profile', [0, 1, 2])
def test_factory_state_preserves_manual_following_preference(daemon, monkeypatch, longitudinal, passive, initial_factory_eco, profile):
  daemon.CP.openpilotLongitudinalControl = longitudinal
  daemon.CP.passive = passive
  daemon.params.put('LongitudinalPersonality', profile, block=True)
  writes = Mock(wraps=daemon.params.put)
  monkeypatch.setattr(daemon.params, 'put', writes)
  for selected in (initial_factory_eco, not initial_factory_eco, initial_factory_eco):
    CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=selected)
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    daemon.publish_selfdriveState(CS)
    message = daemon.pm.send.call_args.args[1].selfdriveState
    enabled = selected and longitudinal and not passive
    assert message.ecoMode == enabled
    assert message.personality == profile
    assert daemon.params.get('LongitudinalPersonality') == profile
    # Old stored software selections cannot override the factory switch.
    Path(daemon.params.get_param_path('EcoModeEnabled')).write_text('0' if selected else '1')
    poll_params(daemon, monkeypatch)
    assert daemon.eco_mode == enabled
  writes.assert_not_called()


def test_distance_button_saves_shared_preference_across_eco_changes(daemon, monkeypatch):
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  monkeypatch.setattr(daemon.params, 'put', lambda key, value, **kwargs: Params.put(daemon.params, key, value, block=True))
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True)
  CS.buttonEvents = [{'type': 'gapAdjustCruise', 'pressed': False}]

  for eco, initial, changed in ((True, 0, 2), (False, 2, 1), (True, 1, 0), (False, 0, 2)):
    CS.ecoMode = eco
    daemon._update_eco_mode(CS)
    poll_params(daemon, monkeypatch)
    assert daemon.personality == initial
    daemon._update_personality(CS)
    assert daemon.personality == changed
    assert daemon.params.get('LongitudinalPersonality') == changed


def test_factory_selection_runs_in_existing_step(daemon):
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=True)
  daemon.data_sample = Mock(return_value=CS)
  daemon.update_events = daemon.update_alerts = daemon.publish_selfdriveState = Mock()
  daemon.step()
  assert daemon.eco_mode is True


@pytest.mark.parametrize('can_valid,mode_valid', [(False, True), (True, False), (False, False)])
@pytest.mark.parametrize('previous_eco', [False, True])
def test_missing_factory_state_preserves_last_valid_selection(daemon, monkeypatch, can_valid, mode_valid, previous_eco):
  daemon._update_eco_mode(car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=previous_eco))
  daemon._update_eco_mode(car.CarState.new_message(canValid=can_valid, ecoModeValid=mode_valid, ecoMode=not previous_eco))
  poll_params(daemon, monkeypatch)
  assert daemon.eco_mode == previous_eco


@pytest.mark.parametrize('eco', [False, True])
@pytest.mark.parametrize('profile', [0, 1, 2])
def test_manual_personality_survives_sustained_speed_changes(daemon, monkeypatch, eco, profile):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, ecoMode=eco)
  daemon.CS_prev = CS
  daemon._update_eco_mode(CS)
  poll_params(daemon, monkeypatch)
  daemon.params.put('LongitudinalPersonality', profile, block=True)
  writes = Mock(wraps=daemon.params.put)
  monkeypatch.setattr(daemon.params, 'put', writes)

  for mph in (0., 40., 54.9, 55., 55.1, 70., 40., 0.):
    CS.vEgo = mph * CV.MPH_TO_MS
    # Hold each speed longer than the retired one-minute average, in both modes.
    for _ in range(610):
      poll_params(daemon, monkeypatch)
    daemon.publish_selfdriveState(CS)
    message = daemon.pm.send.call_args.args[1].selfdriveState
    assert message.personality == profile
    assert message.ecoMode == eco
    assert daemon.params.get('LongitudinalPersonality') == profile
  writes.assert_not_called()


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
