"""Read-only parked diagnostics: real DBC/ISO-TP and independent native TX checks."""
import bz2
import ctypes
import io
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opendbc.can import CANPacker, CANParser
from opendbc.car import Bus, structs
from opendbc.car.honda.values import CAR, DBC
from openpilot.cereal import log, messaging
from openpilot.selfdrive.pandad import can_capnp_to_list
from openpilot.tools.odyssey import radar_test as rt

ROOT = Path(__file__).resolve().parents[1]


class Store:
  def __init__(self):
    cp = structs.CarParams.new_message(carFingerprint=CAR.HONDA_ODYSSEY_5G_MMR)
    self.values = {rt.ACTIVE: True, rt.STOP: False, "CarParamsPersistent": cp.to_bytes()}

  def get(self, key):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.get(key))

  def put(self, key, value, **kwargs):
    self.values[key] = value

  put_bool = put


def state(now=100, ignition=True):
  ps = log.PandaState.new_message(pandaType="tres", harnessStatus="normal", safetyModel="elm327", safetyParam=1, ignitionLine=ignition)
  manager = log.ManagerState.new_message(processes=[{"name": n, "running": n == "pandad"} for n in (*rt.ROAD_PROCESSES, "pandad")])
  values = {"pandaStates": [ps], "deviceState": log.DeviceState.new_message(started=False), "managerState": manager}
  class State(dict):
    valid = dict.fromkeys(values, True)
    recv_time = dict.fromkeys(values, now)
    logMonoTime = dict.fromkeys(values, int(now * 1e9))
  return State(values)


def vehicle(now=100, changes=None):
  name = DBC[CAR.HONDA_ODYSSEY_5G_MMR][Bus.pt]
  parser = CANParser(name, list(rt.MESSAGES), 1)
  packer = CANPacker(name)
  frames = []
  for message, _ in rt.MESSAGES:
    values = {"GEAR_SHIFTER": 1} if message == "GEARBOX_AUTO" else {}
    if message == "SCM_FEEDBACK":
      values["PARKING_BRAKE_ON"] = 1
    if message == "WHEEL_SPEEDS":
      values = {f"WHEEL_SPEED_{corner}": 2 for corner in ("FL", "FR", "RL", "RR")}
    values.update((changes or {}).get(message, {}))
    frames.append(packer.make_can_msg(message, 1, values))
  parser.update([(int(now * 1e9), frames)])
  return parser, frames


def test_stationary_floor_and_required_stock_frames():
  cp, _ = vehicle()
  assert rt.parked_error(cp, 100) is None
  for message, _ in rt.MESSAGES:
    old = cp.ts_nanos[message].copy()
    cp.ts_nanos[message].update(dict.fromkeys(old, 0))
    assert rt.parked_error(cp, 100) is not None, message
    cp.ts_nanos[message].update(old)
  assert rt.parked_error(cp, 101) is not None
  cp.can_invalid_cnt = 5
  cp.message_states[0x1A3].counter_fail = 5
  assert rt.parked_error(cp, 100) is not None


@pytest.mark.parametrize("message,signal,value", [
  ("GEARBOX_AUTO", "GEAR_SHIFTER", 4), ("SCM_FEEDBACK", "PARKING_BRAKE_ON", 0),
  ("ENGINE_DATA", "XMISSION_SPEED", 0.01), ("WHEEL_SPEEDS", "WHEEL_SPEED_RR", 2.01),
  ("STANDSTILL", "BRAKE_ERROR_1", 1), ("STANDSTILL", "BRAKE_ERROR_2", 1),
  ("ACC_HUD", "ACC_PROBLEM", 1), ("ACC_HUD", "FCM_PROBLEM", 1),
])
def test_parked_guard_rejects_motion_domains_and_faults(message, signal, value):
  cp, _ = vehicle(changes={message: {signal: value}})
  assert rt.parked_error(cp, 100) is not None


def test_controller_and_panda_guard():
  sm = state()
  assert rt.control_error(sm, 100) is None
  for service in sm:
    sm.recv_time[service] = 90
    assert rt.control_error(sm, 100) is not None
    sm.recv_time[service] = 100
    sm.valid[service] = False
    assert rt.control_error(sm, 100) is not None
    sm.valid[service] = True
    sm.logMonoTime[service] = int(90e9)
    assert rt.control_error(sm, 100) is not None
    sm.logMonoTime[service] = int(100e9)
  for process in sm["managerState"].processes:
    process.running = not process.running
    assert rt.control_error(sm, 100) is not None
    process.running = not process.running
  for field, value in (("controlsAllowed", True), ("safetyModel", "hondaBosch"), ("safetyParam", 0),
                       ("heartbeatLost", True), ("rxBufferOverflow", 1), ("txBufferOverflow", 1), ("safetyTxBlocked", 1)):
    ps = sm["pandaStates"][0]
    old = getattr(ps, field)
    setattr(ps, field, value)
    assert rt.control_error(sm, 100) is not None, field
    setattr(ps, field, old)
  sm["deviceState"].started = True
  assert rt.control_error(sm, 100) is not None


def test_start_rechecks_ignition_identity_and_offroad(monkeypatch):
  monkeypatch.setattr(rt.time, "monotonic", lambda: 100)
  params, sm = Store(), state(ignition=False)
  params.put_bool(rt.ACTIVE, False)
  assert not rt.request_start(params, sm, False)
  sm["pandaStates"][0].ignitionLine = True
  assert not rt.request_start(params, sm, True)
  sm["pandaStates"][0].ignitionLine = False
  params.put("CarParamsPersistent", structs.CarParams.new_message(carFingerprint="other").to_bytes())
  assert not rt.request_start(params, sm, True)
  params.put("CarParamsPersistent", Store().get("CarParamsPersistent"))
  assert rt.request_start(params, sm, True)
  assert params.get_bool(rt.ACTIVE) and not params.get_bool(rt.STOP)
  assert params.get(rt.STATUS)["phase"] == "requested"
  assert not rt.request_start(params, sm, True)


@pytest.fixture(scope="module")
def native_tx(tmp_path_factory):
  folder = tmp_path_factory.mktemp("radar-native-tx")
  source = folder / "test.cc"
  source.write_text('#include "openpilot/selfdrive/pandad/odyssey_radar_test.h"\n'
                    'extern "C" bool check(unsigned int a, unsigned char b, const unsigned char *d, size_t n) {\n'
                    '  return odyssey_radar_test_tx(a, b, d, n);\n}\n')
  library = folder / "test.so"
  subprocess.run(["c++", "-std=c++17", "-shared", "-fPIC", "-I", str(ROOT), str(source), "-o", str(library)], check=True)
  check = ctypes.CDLL(str(library)).check
  check.argtypes = [ctypes.c_uint32, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_size_t]
  check.restype = ctypes.c_bool
  return lambda a, d, b: check(a, b, d, len(d))


def test_native_and_python_read_only_boundaries(native_tx):
  allowed = [bytes.fromhex(s) for s in ("0322f18100000000", "0322f11200000000", "0322f19100000000", "3000000000000000")]
  for address in (0x18DAB0F1, 0x18DAB5F1):
    for data in allowed:
      assert rt.frame_allowed(address, data, 1) and native_tx(address, data, 1)
      for bus in (0, 2, 128):
        assert not rt.frame_allowed(address, data, bus) and not native_tx(address, data, bus)
      for length in (0, 3, 7, 9):
        malformed = (data + b"\x00")[:length]
        assert not rt.frame_allowed(address, malformed, 1) and not native_tx(address, malformed, 1)
  for service in range(256):
    for identifier in (0xF181, 0xF112, 0xF191, 0xF190, 0xFFFF):
      data = bytes([3, service, identifier >> 8, identifier & 255, 0, 0, 0, 0])
      expected = service == 0x22 and identifier in (0xF181, 0xF112, 0xF191)
      assert rt.frame_allowed(0x18DAB0F1, data, 1) == expected
      assert native_tx(0x18DAB0F1, data, 1) == expected
  for address, data in ((0x1DF, allowed[0]), (0x18DA28F1, allowed[0]), (0x18DAB0F1, b"\x30\x00\x00\x00\x01\x00\x00\x00")):
    assert not rt.frame_allowed(address, data, 1) and not native_tx(address, data, 1)


@pytest.mark.parametrize("first_reply", ["positive", "negative", "timeout"])
def test_complete_capture_uses_real_uds_and_flow_control(monkeypatch, first_reply):
  clock = SimpleNamespace(now=100.0)
  monkeypatch.setattr(rt.time, "monotonic", lambda: clock.now)
  capture = rt.Capture.__new__(rt.Capture)
  capture.params, capture.folder, capture.frames = Store(), Path("/private/capture"), 0
  capture.log, capture.events = io.BytesIO(), io.StringIO()
  capture.status_value, capture.last_status = {}, 0
  capture.deadline, capture.query_deadline = 400, float("inf")
  pending, sent, replies = [], [], []

  def recv():
    clock.now += 0.1
    capture.sm = state(clock.now, ignition=capture.status_value.get("phase") != "ignition_off")
    changes = {"SCM_FEEDBACK": {"PARKING_BRAKE_ON": 0}} if capture.status_value.get("phase") == "ignition_on" and clock.now < 106.5 else None
    capture.cp, _ = vehicle(clock.now, changes)
    return [pending.pop(0)] if pending else []

  def send(raw):
    _, frames = can_capnp_to_list([raw], "sendcan")[0]
    for address, data, bus in frames:
      sent.append((address, data, bus))
      response_address = 0x18DAF100 | ((address >> 8) & 255)
      if data[0] == 3:
        if len(sent) == 1 and first_reply != "positive":
          if first_reply == "negative":
            pending.append((response_address, bytes.fromhex("037f223100000000"), 1))
          continue
        payload = b"\x62" + data[2:4] + b"hardware-or-software"
        pending.append((response_address, bytes([0x10, len(payload)]) + payload[:6], 1))
        replies[:] = [(response_address, (bytes([0x20 + n]) + payload[i:i+7]).ljust(8, b"\x00"), 1)
                      for n, i in enumerate(range(6, len(payload), 7), 1)]
      else:
        pending.extend(replies)

  capture.can_recv, capture.sendcan = recv, SimpleNamespace(send=send)
  capture.run()
  requests = [(a, data[1:4]) for a, data, _ in sent if data[0] == 3]
  assert requests == [(a, bytes([0x22, did >> 8, did & 255])) for _, a in rt.ECUS for did in rt.DIDS]
  expected_replies = 6 if first_reply == "positive" else 5
  assert sum(data[0] == 0x30 for _, data, _ in sent) == expected_replies
  events = [json.loads(line) for line in capture.events.getvalue().splitlines()]
  assert len([e for e in events if e.get("data_hex") == b"hardware-or-software".hex()]) == expected_replies
  assert len([e for e in events if e.get("error")]) == 6 - expected_replies
  assert events[-1]["phase"] == "complete"
  assert any(e["message"] == "Set the parking brake" for e in events)
  assert capture.params.get_bool(rt.ACTIVE), "Completion must not restart Alpha Long with ignition on"
  capture.params.put_bool(rt.STOP, True)
  with pytest.raises(rt.TestStopped):
    capture.can_send(0x18DAB0F1, bytes.fromhex("0322f18100000000"), 1)
  assert len(sent) == 6 + expected_replies


def test_capture_preserves_original_can_and_panda_timestamps(tmp_path):
  params = Store()
  capture = rt.Capture(params, tmp_path)
  _, frames = vehicle(time.monotonic())
  raw = rt.can_list_to_can_capnp(frames)
  sm = state()
  sm.services = list(sm)
  sm.updated = dict.fromkeys(sm.services, True)
  sm.update = lambda timeout: None
  capture.sm = sm
  with pytest.MonkeyPatch.context() as patch:
    patch.setattr(messaging, "drain_sock_raw", lambda *args, **kwargs: [raw])
    assert capture.can_recv() == frames
  capture.log.close()
  capture.events.close()
  data = bz2.decompress((tmp_path / "traffic.rlog.bz2").read_bytes())
  assert data.startswith(raw)
  events = list(log.Event.read_multiple_bytes(data))
  assert len(events) == 4
  for event in events[1:]:
    assert event.logMonoTime == int(100e9) and event.valid
    if event.which() == "pandaStates":
      assert event.pandaStates[0].to_dict() == sm["pandaStates"][0].to_dict()
  assert rt.parked_error(capture.cp, time.monotonic()) is None


def test_recovery_requires_live_continuous_ignition_off(monkeypatch):
  params, sm = Store(), state()
  params.put_bool(rt.STOP, True)
  clock = SimpleNamespace(now=100.0)
  monkeypatch.setattr(rt.time, "monotonic", lambda: clock.now)
  def update(timeout):
    clock.now += 0.1
    # Off for too short, then on, then stale off, finally continuously live off.
    sm["pandaStates"][0].ignitionLine = clock.now < 102 or 104 < clock.now < 105
    sm.recv_time["pandaStates"] = clock.now if clock.now < 106 or clock.now > 108 else 100
    sm.logMonoTime["pandaStates"] = int(sm.recv_time["pandaStates"] * 1e9)
    if clock.now < 113:
      assert params.get_bool(rt.ACTIVE)
  sm.update = update
  rt.recover(params, sm)
  assert clock.now >= 113
  assert not params.get_bool(rt.ACTIVE) and params.get_bool(rt.STOP)


@pytest.mark.parametrize("failure", ["stop", "inactive", "deadline", "query_deadline", "missing_can", "controller"])
def test_each_send_and_uds_receive_checks_live_guards(monkeypatch, failure):
  monkeypatch.setattr(rt.time, "monotonic", lambda: 100)
  capture = rt.Capture.__new__(rt.Capture)
  capture.params, capture.sm = Store(), state()
  capture.cp, _ = vehicle()
  capture.can_recv = list
  capture.deadline = capture.query_deadline = 200
  capture.log, capture.sendcan = io.BytesIO(), SimpleNamespace(send=lambda raw: pytest.fail("Unsafe send"))
  if failure == "stop":
    capture.params.put_bool(rt.STOP, True)
  elif failure == "inactive":
    capture.params.put_bool(rt.ACTIVE, False)
  elif failure in ("deadline", "query_deadline"):
    setattr(capture, failure, 99)
  elif failure == "missing_can":
    capture.cp.ts_nanos["GEARBOX_AUTO"].update(dict.fromkeys(capture.cp.ts_nanos["GEARBOX_AUTO"], 0))
  else:
    capture.sm["deviceState"].started = True
  with pytest.raises(rt.TestStopped):
    capture.can_send(0x18DAB0F1, bytes.fromhex("0322f18100000000"), 1)
  with pytest.raises(rt.TestStopped):
    capture.recv_guarded()


def test_runtime_hold_and_public_removal_are_independent():
  import publish_public as publisher
  for path in publisher.DIAGNOSTIC_INTEGRATIONS:
    cleaned = publisher.public_text(path, (ROOT / path).read_text())
    assert 'ODYSSEY PARKED DIAGNOSTICS' not in cleaned
    assert 'OdysseyRadarTest' not in cleaned
    assert 'odyssey_radar' not in cleaned
  source = (ROOT / "openpilot/system/manager/manager.py").read_text()
  assert 'started = started and not params.get_bool("OdysseyRadarTest")' in source
  source = (ROOT / "openpilot/system/hardware/hardwared.py").read_text()
  assert 'onroad_conditions["not_odyssey_radar_test"] = not params.get_bool("OdysseyRadarTest")' in source
  native = (ROOT / "openpilot/selfdrive/pandad/pandad.cc").read_text()
  assert 'allowed &= odyssey_radar_test_tx(frame.getAddress(), frame.getSrc(), data.begin(), data.size());' in native
  assert 'bool allowed = !diagnostic_params.getBool("OdysseyRadarTestStop");' in native
  assert 'is_onroad = false;\n        engaged = false;' in native
  assert 'diagnostic_params.getBool("OdysseyRadarTestStop") ? cereal::CarParams::SafetyModel::NO_OUTPUT : cereal::CarParams::SafetyModel::ELM327' in native
  from openpilot.system.manager.process_config import managed_processes
  params = Store()
  assert managed_processes["odyssey_radar_test"].should_run(False, params, None)
  assert not managed_processes["updated"].should_run(False, params, None)
  params.put_bool(rt.ACTIVE, False)
  assert not managed_processes["odyssey_radar_test"].should_run(False, params, None)
  assert managed_processes["updated"].should_run(False, params, None)


def test_ui_keeps_status_and_stop_visible(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  monkeypatch.setenv("SCALE", "1")
  import pyray as rl
  from openpilot.selfdrive.ui.layouts.settings import odyssey_radar as ui
  params = Store()
  params.put(rt.STATUS, {"message": "Recording baseline", "monotonic": time.monotonic()})
  monkeypatch.setattr(ui, "Params", lambda: params)
  monkeypatch.setattr(ui.gui_app, "font", lambda *a: rl.Font())
  monkeypatch.setattr(ui.gui_app, "texture", lambda *a, **kw: rl.Texture())
  item = ui.OdysseyRadarTestItem()
  item._set_description_visible = Mock()
  item.get_item_height = Mock(return_value=420)
  item._update_state()
  item._set_description_visible.assert_called_once_with(True)
  assert "Recording baseline" in item.description
  assert item.rect.height == 420
  params.put(rt.STATUS, {"message": "Longer status after a guard change", "monotonic": time.monotonic()})
  item.get_item_height.return_value = 520
  item._update_state()
  assert "Longer status" in item.description and item.rect.height == 520
  assert item.action_item.enabled and item.action_item.text == "STOP"
  params.put("CarParamsPersistent", b"invalid")
  assert item.is_visible, "Stop must remain reachable if saved identification is lost"
  item.action()
  assert params.get_bool(rt.STOP) and params.get_bool(rt.ACTIVE)


def test_parked_test_keeps_display_awake(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  monkeypatch.setenv("SCALE", "1")
  from openpilot.selfdrive.ui import ui_state as ui
  params, clock = Store(), SimpleNamespace(now=100.0)
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(started=False, ignition=False, screen_timeout_enabled=True, params=params))
  monkeypatch.setattr(ui, "gui_app", SimpleNamespace(target_fps=20, mouse_events=[]))
  monkeypatch.setattr(ui, "PC", False)
  monkeypatch.setattr(ui.time, "monotonic", lambda: clock.now)
  device = ui.Device()
  monkeypatch.setattr(device, "_set_awake", lambda awake: setattr(device, "_awake", awake))
  device._update_wakefulness()
  clock.now = 200
  device._update_wakefulness()
  assert device.awake
  params.put_bool(rt.ACTIVE, False)
  device._update_wakefulness()
  assert not device.awake
