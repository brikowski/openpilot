import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opendbc.car.structs import car
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
from openpilot.selfdrive.selfdrived.state import StateMachine


def test_eco_setting_defaults_off_and_survives_drive_transitions(tmp_path):
  params = Params(str(tmp_path))
  assert params.get_default_value('EcoModeEnabled') is False
  assert params.get_bool('EcoModeEnabled') is False
  for selected in (True, False):
    params.put_bool('EcoModeEnabled', selected, block=True)
    params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START | ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION |
                     ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
    assert Params(str(tmp_path)).get_bool('EcoModeEnabled') is selected


@pytest.mark.parametrize('longitudinal,passive', [(True, False), (False, False), (True, True)])
def test_live_eco_setting_reaches_published_state(monkeypatch, tmp_path, longitudinal, passive):
  daemon = SelfdriveD.__new__(SelfdriveD)
  daemon.params = Params(str(tmp_path))
  daemon.CP = car.CarParams.new_message(openpilotLongitudinalControl=longitudinal, passive=passive)
  daemon.eco_mode = False
  daemon.enabled = daemon.active = False
  daemon.state_machine = StateMachine()
  daemon.events = Events()
  daemon.events_prev = []
  daemon.AM = AlertManager()
  daemon.sm = SimpleNamespace(frame=1)
  daemon.pm = Mock()

  for selected in (True, False):
    daemon.params.put_bool('EcoModeEnabled', selected, block=True)
    done = threading.Event()
    monkeypatch.setattr('openpilot.selfdrive.selfdrived.selfdrived.time.sleep', lambda _, done=done: done.set())
    daemon.params_thread(done)
    daemon.publish_selfdriveState(car.CarState.new_message())
    message = daemon.pm.send.call_args.args[1]
    assert message.selfdriveState.ecoMode == (selected and longitudinal and not passive)
    assert message.selfdriveState.personality == (2 if selected else 1)


def test_distance_button_saves_each_mode_independently(monkeypatch, tmp_path):
  daemon = SelfdriveD.__new__(SelfdriveD)
  daemon.params = Params(str(tmp_path))
  daemon.CP = car.CarParams.new_message(openpilotLongitudinalControl=True)
  daemon.events = Events()
  assert daemon.params.get('EcoLongitudinalPersonality', return_default=True) == 2
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  monkeypatch.setattr(daemon.params, 'put', lambda key, value: Params.put(daemon.params, key, value, block=True))
  CS = car.CarState.new_message()
  CS.buttonEvents = [{'type': 'gapAdjustCruise', 'pressed': False}]

  for eco, initial, changed in ((True, 2, 1), (False, 0, 2), (True, 1, 0), (False, 2, 1)):
    daemon.params.put_bool('EcoModeEnabled', eco, block=True)
    done = threading.Event()
    monkeypatch.setattr('openpilot.selfdrive.selfdrived.selfdrived.time.sleep', lambda _, done=done: done.set())
    daemon.params_thread(done)
    assert daemon.personality == initial
    daemon._update_personality(CS)
    assert daemon.personality == changed
    key = 'EcoLongitudinalPersonality' if eco else 'LongitudinalPersonality'
    assert daemon.params.get(key) == changed


@pytest.mark.parametrize('previous_eco', [False, True])
def test_mode_switch_waits_for_matching_following_preference(monkeypatch, tmp_path, previous_eco):
  daemon = SelfdriveD.__new__(SelfdriveD)
  daemon.params = Params(str(tmp_path))
  daemon.CP = car.CarParams.new_message(openpilotLongitudinalControl=True)
  daemon.eco_mode = previous_eco
  daemon.personality = 2 if previous_eco else 0
  daemon.params.put('LongitudinalPersonality', 0, block=True)
  daemon.params.put_bool('EcoModeEnabled', not previous_eco, block=True)
  daemon.enabled = daemon.active = False
  daemon.state_machine = StateMachine()
  daemon.events = Events()
  daemon.events_prev = []
  daemon.AM = AlertManager()
  daemon.sm = SimpleNamespace(frame=1)
  daemon.pm = Mock()
  get = daemon.params.get

  def read_with_publication(key, **kwargs):
    if key in ('LongitudinalPersonality', 'EcoLongitudinalPersonality'):
      # The native Params read releases the GIL; publication may run while it is pending.
      daemon.publish_selfdriveState(car.CarState.new_message())
    return get(key, **kwargs)

  monkeypatch.setattr(daemon.params, 'get', read_with_publication)
  done = threading.Event()
  monkeypatch.setattr('openpilot.selfdrive.selfdrived.selfdrived.time.sleep', lambda _: done.set())
  daemon.params_thread(done)
  pending = daemon.pm.send.call_args.args[1].selfdriveState
  assert pending.ecoMode == previous_eco
  assert pending.personality == (2 if previous_eco else 0)
  daemon.publish_selfdriveState(car.CarState.new_message())
  applied = daemon.pm.send.call_args.args[1].selfdriveState
  assert applied.ecoMode == (not previous_eco)
  assert applied.personality == (0 if previous_eco else 2)
