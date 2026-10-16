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
    assert message.selfdriveState.personality == 1
