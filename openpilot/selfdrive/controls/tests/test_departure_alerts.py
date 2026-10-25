from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opendbc.car.structs import car
from openpilot.cereal import log, messaging
from openpilot.selfdrive.controls.lib.departure_alerts import DepartureAlerts


class Signals(dict):
  def __init__(self, engaged=False):
    super().__init__((name, getattr(messaging.new_message(name), name)) for name in
                     ('carState', 'carControl', 'modelV2', 'radarState', 'selfdriveState', 'driverAssistance'))
    self['carState'].canValid = True
    self['carState'].standstill = True
    self['carState'].gearShifter = 'drive'
    self['carControl'].enabled = self['selfdriveState'].enabled = engaged
    self['modelV2'].action.shouldStop = True
    self['radarState'].leadOne.dRel = 6.0
    self['radarState'].leadOne.radarTrackId = -1
    self.frame = 0
    self.logMonoTime = {}
    self.updated = dict.fromkeys(self, True)
    self.invalid = set()
    self.stale = set()

  def all_checks(self, services=None):
    return not self.invalid.intersection(services or self)

  def tick(self):
    self.frame += 1
    for name in self:
      self.logMonoTime[name] = 1_000_000_000 + self.frame * 50_000_000 - (1_000_000_000 if name in self.stale else 0)


def advance(detector, sm, frames, *, lead_speed=None):
  notifications = []
  for _ in range(frames):
    if lead_speed is not None:
      sm['radarState'].leadOne.vRel = lead_speed
      sm['radarState'].leadOne.dRel += lead_speed * 0.05
    sm.tick()
    result = detector.update(sm)
    if any(result):
      notifications.append(result)
  return notifications


@pytest.mark.parametrize('engaged', [False, True])
@pytest.mark.parametrize('radar', [False, True])
def test_stopped_lead_departure_chimes_once_in_manual_and_engaged_driving(engaged, radar):
  sm, detector = Signals(engaged), DepartureAlerts()
  sm['radarState'].leadOne.present = True
  sm['radarState'].leadOne.radar = radar
  sm['radarState'].leadOne.radarTrackId = 7 if radar else -1
  assert not advance(detector, sm, 45)
  assert advance(detector, sm, 80, lead_speed=2.0) == [(True, False)]
  assert not advance(detector, sm, 50, lead_speed=2.0)


@pytest.mark.parametrize('engaged', [False, True])
def test_model_stop_to_proceed_chimes_once_in_manual_and_engaged_driving(engaged):
  sm, detector = Signals(engaged), DepartureAlerts()
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert advance(detector, sm, 100) == [(False, True)]
  # Further stop/proceed predictions at the same vehicle stop do not repeat it.
  sm['modelV2'].action.shouldStop = True
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  assert not advance(detector, sm, 45)


def test_already_open_road_does_not_chime_without_an_observed_stop_prediction():
  sm, detector = Signals(), DepartureAlerts()
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 1.0
  assert not advance(detector, sm, 200)


def test_short_stop_and_transient_proceed_predictions_do_not_chime():
  sm, detector = Signals(), DepartureAlerts()
  assert not advance(detector, sm, 20)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert not advance(detector, sm, 20)
  sm['modelV2'].action.shouldStop = True
  assert not advance(detector, sm, 45)
  for _ in range(4):
    sm['modelV2'].action.shouldStop = False
    assert not advance(detector, sm, 6)
    sm['modelV2'].action.shouldStop = True
    assert not advance(detector, sm, 2)
  sm['modelV2'].action.shouldStop = False
  assert advance(detector, sm, 20) == [(False, True)]


def test_vehicle_must_move_before_the_next_stop_can_notify():
  sm, detector = Signals(), DepartureAlerts()
  for _ in range(2):
    sm['carState'].standstill = True
    sm['carState'].vEgo = 0.0
    sm['modelV2'].action.shouldStop = True
    assert not advance(detector, sm, 45)
    sm['modelV2'].action.shouldStop = False
    sm['modelV2'].action.desiredAcceleration = 0.5
    assert advance(detector, sm, 20) == [(False, True)]
    sm['carState'].standstill = False
    sm['carState'].vEgo = 1.0
    assert not advance(detector, sm, 10)


@pytest.mark.parametrize('field,value', [('gasPressed', True), ('gearShifter', 'reverse'), ('gearShifter', 'park'),
                                         ('parkingBrake', True), ('vEgo', 0.2), ('standstill', False), ('canValid', False)])
def test_ineligible_vehicle_state_cannot_notify(field, value):
  sm, detector = Signals(), DepartureAlerts()
  assert not advance(detector, sm, 45)
  setattr(sm['carState'], field, value)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert not advance(detector, sm, 50)


@pytest.mark.parametrize('service', ['carState', 'modelV2', 'radarState'])
@pytest.mark.parametrize('failure', ['invalid', 'stale'])
def test_missing_or_stale_inputs_discard_armed_history(service, failure):
  sm, detector = Signals(), DepartureAlerts()
  assert not advance(detector, sm, 45)
  getattr(sm, failure).add(service)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert not advance(detector, sm, 50)
  getattr(sm, failure).clear()
  assert not advance(detector, sm, 50)


def test_sampling_gap_and_backwards_timestamp_discard_armed_history():
  for frame_change in (-20, 20):
    sm, detector = Signals(), DepartureAlerts()
    assert not advance(detector, sm, 45)
    sm.frame += frame_change
    sm['modelV2'].action.shouldStop = False
    sm['modelV2'].action.desiredAcceleration = 0.5
    assert not advance(detector, sm, 50)


def test_data_loss_does_not_repeat_a_delivered_notification():
  sm, detector = Signals(), DepartureAlerts()
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert advance(detector, sm, 20) == [(False, True)]
  sm.invalid.add('modelV2')
  assert not advance(detector, sm, 20)
  sm.invalid.clear()
  sm['modelV2'].action.shouldStop = True
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  assert not advance(detector, sm, 20)


@pytest.mark.parametrize('failure', ['lost', 'track_changed', 'range_jump', 'nonfinite'])
def test_lost_or_switched_leads_do_not_masquerade_as_departure_or_green_light(failure):
  sm, detector = Signals(), DepartureAlerts()
  lead = sm['radarState'].leadOne
  lead.present = True
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  if failure == 'lost':
    lead.present = False
  elif failure == 'track_changed':
    lead.radarTrackId = 8
  elif failure == 'range_jump':
    lead.dRel += 5.0
  else:
    lead.dRel = float('nan')
  assert not advance(detector, sm, 80, lead_speed=2.0)


def test_a_moving_lead_cannot_arm_a_departure_notification():
  sm, detector = Signals(), DepartureAlerts()
  sm['radarState'].leadOne.present = True
  assert not advance(detector, sm, 100, lead_speed=2.0)


def test_losing_a_lead_cannot_rearm_traffic_ready_at_the_same_stop():
  sm, detector = Signals(), DepartureAlerts()
  sm['radarState'].leadOne.present = True
  assert not advance(detector, sm, 45)
  sm['radarState'].leadOne.present = False
  assert not advance(detector, sm, 45)
  sm['modelV2'].action.shouldStop = False
  sm['modelV2'].action.desiredAcceleration = 0.5
  assert not advance(detector, sm, 45)


def test_lead_range_noise_without_confirmed_motion_does_not_chime():
  sm, detector = Signals(), DepartureAlerts()
  lead = sm['radarState'].leadOne
  lead.present = True
  assert not advance(detector, sm, 45)
  for distance in (6.5, 7.0, 7.5, 8.0):
    lead.dRel = distance
    assert not advance(detector, sm, 20)


@pytest.mark.parametrize('lead_present', [False, True])
def test_detector_does_not_modify_vehicle_commands_or_model(lead_present):
  sm, detector = Signals(True), DepartureAlerts()
  sm['radarState'].leadOne.present = lead_present
  before = {name: sm[name].to_dict() for name in ('carState', 'carControl', 'modelV2', 'selfdriveState')}
  advance(detector, sm, 100)
  assert {name: sm[name].to_dict() for name in before} == before


@pytest.mark.parametrize('departure', [(True, False), (False, True)])
def test_plannerd_publishes_each_notification_without_settings(monkeypatch, departure):
  from openpilot.selfdrive.controls import plannerd

  sm = Signals()
  sm.tick()
  sm.update = Mock(side_effect=[None, StopIteration])
  pm = Mock()
  cp = car.CarParams.new_message(brand='honda')
  monkeypatch.setattr(plannerd, 'Params', lambda: SimpleNamespace(get=lambda *args, **kwargs: cp.to_bytes()))
  monkeypatch.setattr(plannerd, 'config_realtime_process', Mock())
  monkeypatch.setattr(plannerd.messaging, 'SubMaster', lambda *args, **kwargs: sm)
  monkeypatch.setattr(plannerd.messaging, 'PubMaster', lambda *args, **kwargs: pm)
  monkeypatch.setattr(plannerd, 'LongitudinalPlanner', Mock())
  monkeypatch.setattr(plannerd, 'DepartureAlerts', lambda: SimpleNamespace(update=lambda _: departure))
  with pytest.raises(StopIteration):
    plannerd.main()
  topic, message = pm.send.call_args.args
  assert topic == 'driverAssistance'
  assert message.valid
  assert (message.driverAssistance.leadDeparting, message.driverAssistance.trafficReady) == departure


@pytest.mark.parametrize('event,field', [(log.OnroadEvent.EventName.leadDeparting, 'leadDeparting'),
                                       (log.OnroadEvent.EventName.trafficReady, 'trafficReady')])
@pytest.mark.parametrize('engaged', [False, True])
def test_notification_reaches_audio_and_neutral_popup_without_control_effects(monkeypatch, event, field, engaged):
  import numpy as np

  from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
  from openpilot.selfdrive.selfdrived.events import Events, ET
  from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
  from openpilot.selfdrive.selfdrived.state import StateMachine
  from openpilot.selfdrive.ui.soundd import Soundd, sound_list

  daemon = SelfdriveD.__new__(SelfdriveD)
  daemon.sm = Signals(engaged)
  daemon.sm.tick()
  setattr(daemon.sm['driverAssistance'], field, True)
  daemon.events = Events()
  daemon.AM = AlertManager()
  daemon.state_machine = StateMachine()
  daemon.state_machine.state = log.SelfdriveState.OpenpilotState.enabled if engaged else log.SelfdriveState.OpenpilotState.disabled
  daemon.enabled, daemon.active = engaged, engaged
  daemon.CP = car.CarParams.new_message()
  daemon.personality, daemon.is_metric = 1, True
  daemon.eco_mode, daemon.initialized = False, True
  daemon.events_prev = []
  daemon.pm = Mock()
  daemon.data_sample = Mock(return_value=daemon.sm['carState'])
  daemon.update_events = Mock(side_effect=lambda _: daemon.events.clear())

  daemon.step()
  assert daemon.events.names == [event]
  assert (daemon.enabled, daemon.active) == (engaged, engaged)
  assert not any(daemon.events.contains(et) for et in (ET.ENABLE, ET.NO_ENTRY, ET.WARNING, ET.USER_DISABLE,
                                                       ET.SOFT_DISABLE, ET.IMMEDIATE_DISABLE, ET.OVERRIDE_LONGITUDINAL))
  alert = daemon.AM.current_alert
  assert alert.alert_size == log.SelfdriveState.AlertSize.small
  assert alert.alert_status == log.SelfdriveState.AlertStatus.normal
  assert alert.alert_text_1 and not alert.alert_text_2
  assert alert.visual_alert == car.CarControl.HUDControl.VisualAlert.none
  assert alert.audible_alert == log.SelfdriveState.AudibleAlert.prompt

  topic, message = daemon.pm.send.call_args_list[0].args
  assert topic == 'selfdriveState'
  assert message.selfdriveState.enabled == engaged
  assert message.selfdriveState.alertType == f'{field}/permanent'
  daemon.sm['selfdriveState'] = message.selfdriveState
  # Exercise playback with sample fixtures, independently of Git LFS and audio hardware.
  monkeypatch.setattr(Soundd, 'load_sounds', lambda self: setattr(self, 'loaded_sounds',
                      {key: np.ones(4800, dtype=np.float32) for key in sound_list}))
  sound = Soundd()
  sound.get_audible_alert(daemon.sm)
  assert sound.current_alert == log.SelfdriveState.AudibleAlert.prompt
  assert max(abs(sound.get_sound_data(48000))) > 0.0
  assert sound_list[alert.audible_alert][1] == 1
  assert max(abs(sound.get_sound_data(48000))) == 0.0

  # A safety alert owns the output even when a departure event arrives concurrently.
  daemon.events.add(log.OnroadEvent.EventName.fcw)
  daemon.update_alerts(daemon.sm['carState'])
  assert daemon.AM.current_alert.alert_type.startswith('fcw/')


@pytest.mark.parametrize('updated,valid', [(False, True), (True, False)])
def test_consumer_ignores_repeated_or_invalid_notification_messages(updated, valid):
  from openpilot.selfdrive.selfdrived.events import Events
  from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD

  daemon = SelfdriveD.__new__(SelfdriveD)
  daemon.sm, daemon.events = Signals(), Events()
  daemon.sm['driverAssistance'].leadDeparting = daemon.sm['driverAssistance'].trafficReady = True
  daemon.sm.updated['driverAssistance'] = updated
  if not valid:
    daemon.sm.invalid.add('driverAssistance')
  daemon._update_departure_alerts()
  assert not daemon.events.names
