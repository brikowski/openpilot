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
  for eco, mph, expected in ((True, 70, 2), (False, 0, 0), (False, 54.99, 0), (False, 55, 1), (False, 70, 1),
                             (False, 54.99, 0), (True, 30, 2), (True, 70, 2), (False, 70, 1),
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


@pytest.fixture
def econ_advisory(daemon, monkeypatch):
  daemon.CP.carFingerprint = HONDA.HONDA_ODYSSEY_5G_MMR
  daemon.enabled = True
  daemon.state_machine.state = selfdrived.State.enabled
  clock = Mock(return_value=100.)
  monkeypatch.setattr(selfdrived.time, 'monotonic', clock)
  CS = car.CarState.new_message(canValid=True, ecoModeValid=True, vEgo=55 * CV.MPH_TO_MS)
  return daemon, CS, clock


@pytest.mark.parametrize('longitudinal', [False, True])
def test_econ_suggestion_waits_for_highway_cruise_and_repeats_after_fifteen_minutes(econ_advisory, longitudinal):
  daemon, CS, clock = econ_advisory
  daemon.CP.openpilotLongitudinalControl = longitudinal
  original = daemon.factory_eco_mode, daemon.eco_mode, daemon.personality
  for now, expected in ((100., False), (159.99, False), (160., True), (1059.99, False), (1060., True)):
    clock.return_value = now
    daemon.events.clear()
    daemon._update_econ_suggestion(CS)
    assert (selfdrived.EventName.econSuggestion in daemon.events.names) == expected
  assert (daemon.factory_eco_mode, daemon.eco_mode, daemon.personality) == original


@pytest.mark.parametrize('fault', ['speed', 'nan', 'can', 'eco', 'disabled', 'passive', 'other_car'])
def test_econ_suggestion_restarts_qualification_after_ineligible_driving(econ_advisory, fault):
  daemon, CS, clock = econ_advisory
  daemon._update_econ_suggestion(CS)
  clock.return_value = 159.
  if fault == 'speed':
    CS.vEgo = 54.99 * CV.MPH_TO_MS
  elif fault == 'nan':
    CS.vEgo = float('nan')
  elif fault == 'can':
    CS.canValid = False
  elif fault == 'eco':
    CS.ecoMode = True
  elif fault == 'disabled':
    daemon.enabled = False
  elif fault == 'passive':
    daemon.CP.passive = True
  else:
    daemon.CP.carFingerprint = 'HONDA_CIVIC'
  daemon._update_econ_suggestion(CS)
  assert daemon.econ_cruise_start is None
  assert not daemon.events.names


def test_econ_suggestion_accepts_normal_status_spacing_but_resets_on_stale_or_unknown_mode(econ_advisory):
  daemon, CS, clock = econ_advisory
  CS.ecoModeValid = False
  daemon._update_econ_suggestion(CS)
  assert daemon.econ_cruise_start is None
  for frame in range(6101):
    clock.return_value = 100. + frame * .01
    CS.ecoModeValid = frame % 4 == 0
    daemon._update_econ_suggestion(CS)
  assert selfdrived.EventName.econSuggestion in daemon.events.names
  daemon.events.clear()
  CS.ecoModeValid = False
  clock.return_value = 162.
  daemon._update_econ_suggestion(CS)
  assert daemon.econ_cruise_start is None
  assert not daemon.events.names


def test_econ_suggestion_defers_for_driving_alerts_and_yields_to_fcw(econ_advisory):
  from openpilot.selfdrive.selfdrived.events import AlertSize, AlertStatus, AudibleAlert, EVENTS, ET, Priority, VisualAlert

  daemon, CS, clock = econ_advisory
  daemon._update_econ_suggestion(CS)
  clock.return_value = 160.
  daemon.events.add(selfdrived.EventName.laneChange)
  daemon._update_econ_suggestion(CS)
  assert selfdrived.EventName.econSuggestion not in daemon.events.names
  daemon.events.clear()
  daemon.AM.current_alert = EVENTS[selfdrived.EventName.userBookmark][ET.PERMANENT]
  daemon._update_econ_suggestion(CS)
  assert selfdrived.EventName.econSuggestion not in daemon.events.names
  daemon.AM.current_alert = selfdrived.AlertManager().current_alert
  daemon._update_econ_suggestion(CS)
  assert selfdrived.EventName.econSuggestion in daemon.events.names
  alert = daemon.events.create_alerts([ET.WARNING])[0]
  assert (alert.alert_size, alert.alert_status, alert.priority) == (AlertSize.small, AlertStatus.normal, Priority.LOWEST)
  assert alert.audible_alert == AudibleAlert.none and alert.visual_alert == VisualAlert.none
  assert alert.duration == int(4. / selfdrived.DT_CTRL)
  daemon.events.add(selfdrived.EventName.fcw)
  daemon.state_machine.current_alert_types = [ET.PERMANENT, ET.WARNING]
  daemon.update_alerts(CS)
  assert daemon.AM.current_alert.alert_type == 'fcw/permanent'


def test_econ_suggestion_runs_in_the_normal_step(econ_advisory):
  daemon, CS, _ = econ_advisory
  daemon.initialized = True
  daemon.data_sample = Mock(return_value=CS)
  daemon.update_events = daemon.update_alerts = daemon.publish_selfdriveState = Mock()
  daemon.step()
  assert daemon.econ_cruise_start == 100.
