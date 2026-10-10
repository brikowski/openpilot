"""Exercise parked-only diagnostic capture through the pinned CAN and UDS parsers."""
import io
import json
import subprocess

import pytest

from openpilot.tools import honda_brake_capture as m
from opendbc.can import CANPacker


class RecordedPanda:
  def __init__(self):
    self.packer = CANPacker(m.DBC_NAME)
    self.tick = 0
    self.values = {"ENGINE_DATA": {"XMISSION_SPEED": 0}, "WHEEL_SPEEDS": {},
                   "GEARBOX_AUTO": {"GEAR_SHIFTER": 1},
                   "SCM_FEEDBACK": {"PARKING_BRAKE_ON": 1}, "POWERTRAIN_DATA": {"BRAKE_PRESSED": 0}}
    self.state = {"safety_mode": m.SAFETY.noOutput, "controls_allowed": False, "faults": 0,
                  "ignition_line": True, "ignition_can": False, "voltage": 14000, "current": 0}
    self.sent, self.modes, self.pending = [], [], []
    self.response = bytes(range(56))
    self.interrupt = False

  def health(self):
    return dict(self.state)

  def set_safety_mode(self, mode, param=0):
    self.modes.append((mode, param))
    self.state['safety_mode'] = mode

  def can_clear(self, bus):
    self.pending = []

  def can_recv(self):
    self.tick += 1
    frames = [self.packer.make_can_msg(name, 1, {**values, **({"COUNTER": self.tick % 4} if name != 'WHEEL_SPEEDS' else {})})
              for name, values in self.values.items()]
    if self.modes and self.modes[-1] == (m.SAFETY.elm327, 0):
      frames = []  # The actual hardware mux cannot supply native state on OBD.
    frames += self.pending
    self.pending = []
    return frames

  def can_send(self, address, data, bus, **kwargs):
    self.sent.append((address, bytes(data), bus))
    if data[0] == 3:
      did = int.from_bytes(data[2:4], 'big')
      if self.interrupt and did == 0x4005:
        raise KeyboardInterrupt
      body = self.response if did == 0x4005 else (b'46114-THR-A530\0\0' if address == 0x18DA2BF1 else b'57114-THR-A240\0\0')
      payload = bytes([0x62]) + data[2:4] + body
      first = (bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:6]).ljust(8, b'\0')
      self.rest = [(m.get_rx_addr_for_tx_addr(address),
                    (bytes([0x20 | (i % 16)]) + payload[start:start+7]).ljust(8, b'\0'), bus)
                   for i, start in enumerate(range(6, len(payload), 7), 1)]
      self.pending.append((m.get_rx_addr_for_tx_addr(address), first, bus))
    elif data[0] == 0x30:
      self.pending.extend(self.rest)


@pytest.fixture
def parked(monkeypatch):
  clock = [1_000_000_000]
  monkeypatch.setattr(m.time, "monotonic_ns", lambda: clock[0])
  monkeypatch.setattr(m.time, "monotonic", lambda: clock[0] / 1e9)
  monkeypatch.setattr(m.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + int(seconds * 1e9)))
  monkeypatch.setattr(m, "require_exclusive_panda", lambda: None)
  p = RecordedPanda()
  c = m.Capture(p, io.StringIO())
  c.can_recv()
  assert c.parked()
  return p, c, clock


@pytest.mark.parametrize("message,signal,value", [
  ("ENGINE_DATA", "XMISSION_SPEED", 0.01),
  ("SCM_FEEDBACK", "PARKING_BRAKE_ON", 0),
  *(("WHEEL_SPEEDS", f"WHEEL_SPEED_{wheel}", 0.01) for wheel in ("FL", "FR", "RL", "RR")),
  *(("GEARBOX_AUTO", "GEAR_SHIFTER", gear) for gear in (0, 2, 3, 4)),
])
def test_rejects_motion_or_unparked_state(parked, message, signal, value):
  p, c, _ = parked
  p.values[message][signal] = value
  c.active = True
  with pytest.raises(RuntimeError, match="Park"):
    c.can_recv()
  assert not p.sent


def test_missing_stale_invalid_or_wrong_bus_state_cannot_authorize_queries(parked):
  p, c, clock = parked
  clock[0] += 250_000_001
  assert not c.parked()
  for bad in ("missing", "checksum", "foreign_bus", "returned_tx", "rejected_tx"):
    c = m.Capture(p, io.StringIO())
    frames = p.can_recv()
    if bad == "missing":
      frames = [f for f in frames if f[0] != 419]
    elif bad == "checksum":
      frames = [(addr, data[:-1] + bytes([data[-1] ^ 1]), bus) for addr, data, bus in frames]
    else:
      bus = {"foreign_bus": 0, "returned_tx": 129, "rejected_tx": 193}[bad]
      frames = [(addr, data, bus) for addr, data, _ in frames]
    c.panda = type('Frames', (), {'can_recv': lambda self, frames=frames: frames})()
    c.can_recv()
    assert not c.parked(), bad


def test_buffered_park_before_capture_cannot_authorize_queries(parked, monkeypatch):
  p, _, _ = parked
  queued = [p.can_recv()]
  p.values['GEARBOX_AUTO']['GEAR_SHIFTER'] = 4
  receive = p.can_recv
  monkeypatch.setattr(p, 'can_recv', lambda: queued.pop(0) if queued else receive())
  monkeypatch.setattr(p, 'can_clear', lambda bus: queued.clear() if bus == 0xFFFF else None)
  with pytest.raises(RuntimeError, match='Park'):
    m.capture(p, io.StringIO(), 1)
  assert not p.sent


@pytest.mark.parametrize('during_receive', [False, True])
def test_buffered_park_after_reception_stall_cannot_refresh_active_guard(parked, monkeypatch, during_receive):
  p, c, clock = parked
  c.active = True
  def stall():
    clock[0] += 250_000_001
  if during_receive:
    receive = p.can_recv
    def slow_receive():
      stall()
      return receive()
    monkeypatch.setattr(p, 'can_recv', slow_receive)
  else:
    stall()
  with pytest.raises(RuntimeError, match='Park'):
    c.can_recv()
  assert not p.sent


@pytest.mark.parametrize("key,value", [("controls_allowed", True), ("faults", 1),
                                       ("ignition_line", False), ("safety_mode", m.SAFETY.noOutput)])
def test_unsafe_health_blocks_transmission(parked, key, value):
  p, c, _ = parked
  p.state['safety_mode'] = m.SAFETY.elm327
  p.state[key] = value
  with pytest.raises(RuntimeError):
    c.can_send(0x18DA28F1, bytes.fromhex('0322400500000000'), 1)
  assert not p.sent


@pytest.mark.parametrize("address,data,bus", [
  (0x18DA28F1, '032E400500000000', 1),  # WriteDataByIdentifier
  (0x18DA28F1, '0210030000000000', 1),  # DiagnosticSessionControl
  (0x18DA28F1, '0322400600000000', 1),
  (0x18DA2BF1, '0322400500000000', 1),
  (0x18DAB0F1, '0322F18100000000', 1),
  (0x18DA28F1, '0322400500000000', 0),
  (0x18DA28F1, '03224005', 1),
  (0x18DA28F1, '3000000000000001', 1),
])
def test_only_named_reads_and_flow_control_can_be_sent(parked, address, data, bus):
  p, c, _ = parked
  p.state['safety_mode'] = m.SAFETY.elm327
  with pytest.raises(RuntimeError, match="permitted"):
    c.can_send(address, bytes.fromhex(data), bus)
  assert not p.sent


@pytest.mark.parametrize("during", ['initial', 'tx'])
def test_daemon_restart_prevents_mode_change_or_transmission(parked, monkeypatch, during):
  p, c, _ = parked
  def busy():
    raise RuntimeError('pandad is running')
  monkeypatch.setattr(m, 'require_exclusive_panda', busy)
  with pytest.raises(RuntimeError, match='pandad'):
    if during == 'initial':
      m.capture(p, io.StringIO(), 1)
    else:
      p.state['safety_mode'] = m.SAFETY.elm327
      c.can_send(0x18DA28F1, bytes.fromhex('0322400500000000'), 1)
  assert not p.modes and not p.sent


def test_malformed_state_frame_is_rejected_before_queries(parked):
  p, c, _ = parked
  p.pending = [(464, b'\0', 1)]
  with pytest.raises(RuntimeError, match='length'):
    c.can_recv()
  assert not p.sent


def test_repeated_pending_responses_cannot_extend_the_read_indefinitely(parked, monkeypatch):
  p, c, clock = parked
  receive = p.can_recv
  def pending():
    clock[0] += 100_000_000
    frames = receive()
    if p.sent:
      frames = [f for f in frames if f[0] < 0x800]
      frames.append((0x18DAF128, bytes.fromhex('037F227800000000'), 1))
    return frames
  monkeypatch.setattr(p, 'can_recv', pending)
  started_ns = clock[0]
  with pytest.raises(TimeoutError, match='freshness'):
    c.read(0x18DA28F1, 0x4005)
  assert 250_000_000 < clock[0] - started_ns <= 400_000_000
  assert c.read_deadline_ns == 0


def test_records_complete_diagnostic_response_and_raw_can_flags(parked):
  p, c, _ = parked
  c.read(0x18DA28F1, 0x4005)
  p.pending = [(0xE7, bytes.fromhex('140500a08b'), 1), (0x1DF, bytes(8), 129), (0x1DF, bytes(8), 193)]
  c.can_recv()
  rows = [json.loads(line) for line in c.output.getvalue().splitlines()]
  response = next(r for r in rows if r['type'] == 'uds')
  assert response['data_hex'] == p.response.hex()
  assert response['started_ns'] <= response['mono_ns']
  assert rows[-1]['frames'][-3:] == [[0xE7, '140500a08b', 1], [0x1DF, '00'*8, 129], [0x1DF, '00'*8, 193]]
  assert [data[:4] for _, data, _ in p.sent] == [bytes.fromhex('03224005'), bytes.fromhex('30000a00')]


@pytest.mark.parametrize("failure", [None, "length", "interrupt"])
def test_capture_restores_nooutput_after_success_or_failure(parked, failure):
  p, _, _ = parked
  output = io.StringIO()
  if failure == 'length':
    p.response = bytes(55)
  p.interrupt = failure == 'interrupt'
  if failure:
    with pytest.raises(RuntimeError if failure == 'length' else KeyboardInterrupt):
      m.capture(p, output, 1)
  else:
    m.capture(p, output, 1)
  assert p.modes[-1] == (m.SAFETY.noOutput, 0)
  assert all(mode in (m.SAFETY.elm327, m.SAFETY.noOutput) for mode, _ in p.modes)
  assert p.state['safety_mode'] == m.SAFETY.noOutput
  requests = [(a, int.from_bytes(d[2:4], 'big')) for a, d, _ in p.sent if d[0] == 3]
  assert requests[:2] == [(0x18DA28F1, 0xF181), (0x18DA2BF1, 0xF181)]
  assert all(r in m.READS for r in requests)
  if failure == 'length':
    assert any(json.loads(line).get('data_hex') == bytes(55).hex() for line in output.getvalue().splitlines())


def test_capture_reaches_ecus_on_the_obd_connection(parked, monkeypatch):
  p, _, clock = parked
  receive = p.can_recv
  def tick():
    clock[0] += 1_000_000
    return receive()
  monkeypatch.setattr(p, 'can_recv', tick)
  send = p.can_send
  def obd_only(address, data, bus, **kwargs):
    if p.modes[-1] == (m.SAFETY.elm327, 0):
      send(address, data, bus, **kwargs)
    else:
      p.sent.append((address, bytes(data), bus))
  monkeypatch.setattr(p, 'can_send', obd_only)
  output = io.StringIO()
  m.capture(p, output, 1)
  responses = [json.loads(line) for line in output.getvalue().splitlines() if json.loads(line)['type'] == 'uds']
  assert {(r['address'], r['did']) for r in responses} == m.READS


def test_initial_unsafe_state_does_not_change_panda_mode(parked):
  p, _, _ = parked
  p.state['controls_allowed'] = True
  with pytest.raises(RuntimeError):
    m.capture(p, io.StringIO(), 1)
  assert not p.modes and not p.sent


def test_silent_panda_can_receive_state_before_diagnostic_reads(parked):
  p, _, _ = parked
  p.state['safety_mode'] = m.SAFETY.silent
  m.capture(p, io.StringIO(), 1)
  assert p.modes[0] == p.modes[-1] == (m.SAFETY.noOutput, 0)
  assert (m.SAFETY.elm327, 0) in p.modes
  assert p.sent


def test_silent_panda_without_park_state_remains_in_nooutput(parked):
  p, _, _ = parked
  p.state['safety_mode'] = m.SAFETY.silent
  p.values['GEARBOX_AUTO']['GEAR_SHIFTER'] = 4
  with pytest.raises(RuntimeError, match='Park'):
    m.capture(p, io.StringIO(), 1)
  assert p.modes == [(m.SAFETY.noOutput, 0)]
  assert not p.sent


@pytest.mark.parametrize("status", [0, 1, 2])
def test_exclusive_access_fails_closed(monkeypatch, status):
  monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, status))
  if status == 1:
    m.require_exclusive_panda()
  else:
    with pytest.raises(RuntimeError):
      m.require_exclusive_panda()


@pytest.mark.parametrize('seconds', ['0', '121'])
def test_cli_refuses_unbounded_capture(tmp_path, seconds):
  out = tmp_path/'capture.jsonl'
  with pytest.raises(SystemExit):
    m.main([str(out), '--seconds', seconds])
  assert not out.exists()


def test_cli_refuses_private_output_in_checkout():
  with pytest.raises(SystemExit):
    m.main([str(m.ROOT/'capture.jsonl')])


def test_obd_broadcasts_cannot_refresh_native_state(parked, monkeypatch):
  p, c, clock = parked
  p.set_safety_mode(m.SAFETY.elm327)
  c.obd = c.active = True
  frames = [p.packer.make_can_msg(name, 1, values) for name, values in p.values.items()]
  monkeypatch.setattr(p, 'can_recv', lambda: frames)
  clock[0] += 200_000_000
  c.can_recv()
  clock[0] += 100_000_000
  with pytest.raises(RuntimeError, match='Park'):
    c.can_recv()


def test_completed_reply_needs_fresh_native_state_after_mux_switch(parked, monkeypatch):
  p, c, _ = parked
  send = p.can_send
  def shift_after_reply(address, data, bus, **kw):
    send(address, data, bus, **kw)
    if data[0] == 0x30:
      p.values['GEARBOX_AUTO']['GEAR_SHIFTER'] = 4
  monkeypatch.setattr(p, 'can_send', shift_after_reply)
  with pytest.raises(RuntimeError, match='Park'):
    c.read(0x18DA28F1, 0x4005)
  rows = [json.loads(line) for line in c.output.getvalue().splitlines()]
  assert any(r['type'] == 'uds' for r in rows)
  assert not any(r['type'] == 'qualified' for r in rows)
  assert p.modes[-1] == (m.SAFETY.noOutput, 0)


from types import SimpleNamespace
from unittest.mock import Mock
from openpilot.cereal import messaging
from openpilot.tools import honda_brake_test as guided


class TestParams:
  __test__ = False
  def __init__(self, **values):
    self.values = values
  def get(self, key):
    return self.values.get(key)
  def get_bool(self, key):
    return bool(self.get(key))
  def put(self, key, value, **_):
    self.values[key] = value
  def remove(self, key):
    self.values.pop(key, None)


class StateSnapshot:
  def __init__(self, now, ignition=False):
    ps = messaging.new_message('pandaStates', 1)
    ps.pandaStates[0] = {'pandaType': 9, 'ignitionLine': ignition, 'controlsAllowed': False}
    cp = m.structs.CarParams.new_message(carFingerprint=guided.CAR.HONDA_ODYSSEY_5G_MMR)
    cs = m.structs.CarState.new_message(gearShifter='park', vEgo=0, vEgoRaw=0, parkingBrake=True, canValid=True)
    self.data = {'pandaStates': ps.pandaStates, 'deviceState': SimpleNamespace(started=ignition, fanSpeedPercentDesired=0),
                 'carParams': cp, 'carState': cs, 'carControl': m.structs.CarControl.new_message(enabled=False)}
    self.valid = dict.fromkeys(self.data, True)
    self.alive = dict.fromkeys(self.data, True)
    self.logMonoTime = dict.fromkeys(self.data, now)
  def __getitem__(self, key):
    return self.data[key]
  def update(self, *_):
    pass


@pytest.mark.parametrize('mode', ['requested', 'active', 'cancel', 'restore'])
@pytest.mark.parametrize('ignition', [False, True])
def test_panda_owner_switch_requires_ignition_off(parked, mode, ignition):
  _, _, clock = parked
  params = TestParams(HondaBrakeTest=mode)
  sm = StateSnapshot(clock[0], ignition)
  procs = {'pandad': Mock(), 'honda_brake_test': Mock()}
  active = guided.manage_brake_test(params, sm, procs)
  assert active == (mode in ('active', 'cancel') or (mode == 'restore' and ignition) or (mode == 'requested' and not ignition))
  assert procs['pandad'].stop.called == (mode == 'requested' and not ignition)
  assert procs['honda_brake_test'].stop.called == (mode == 'restore' and not ignition)
  assert (params.get(guided.MODE) is None) == (mode == 'restore' and not ignition)


@pytest.mark.parametrize('bad', ['stale', 'future', 'invalid', 'missing', 'unknown', 'controls', 'started', 'ignition'])
@pytest.mark.parametrize('mode', ['requested', 'restore'])
def test_unqualified_off_state_cannot_transfer_panda(parked, bad, mode):
  _, _, clock = parked
  params = TestParams(HondaBrakeTest=mode)
  sm = StateSnapshot(clock[0])
  if bad in ('stale', 'future'):
    sm.logMonoTime['pandaStates'] += -1_000_000_001 if bad == 'stale' else 1
  elif bad == 'invalid':
    sm.valid['pandaStates'] = False
  elif bad == 'missing':
    sm.data['pandaStates'] = []
  elif bad == 'unknown':
    sm.data['pandaStates'][0].pandaType = 0
  elif bad == 'controls':
    sm.data['pandaStates'][0].controlsAllowed = True
  elif bad == 'ignition':
    sm.data['pandaStates'][0].ignitionLine = True
  else:
    sm.data['deviceState'].started = True
  procs = {'pandad': Mock(), 'honda_brake_test': Mock()}
  guided.manage_brake_test(params, sm, procs)
  assert params.get(guided.MODE) == mode
  assert not any(p.stop.called for p in procs.values())


@pytest.mark.parametrize('bad', [None, 'other_car', 'moving', 'gear', 'parking_brake', 'controls', 'stale', 'can_invalid', 'gas', 'fault'])
def test_only_stationary_odyssey_can_arm_from_live_state(parked, bad):
  _, _, clock = parked
  sm = StateSnapshot(clock[0], True)
  cp = sm['carParams']
  if bad == 'other_car':
    cp.carFingerprint = 'other'
  if bad == 'moving':
    sm['carState'].vEgoRaw = 0.1
  if bad == 'gear':
    sm['carState'].gearShifter = 'drive'
  if bad == 'parking_brake':
    sm['carState'].parkingBrake = False
  if bad == 'controls':
    sm['carControl'].enabled = True
  if bad == 'stale':
    sm.logMonoTime['carState'] = clock[0] - 1_000_000_001
  if bad == 'can_invalid':
    sm['carState'].canValid = False
  if bad == 'gas':
    sm['carState'].gasPressed = True
  if bad == 'fault':
    sm['pandaStates'][0].faults = ['relayMalfunction']
  assert guided.can_request_test(cp, sm) == (bad is None)


def test_manager_blocks_control_and_waits_for_panda_exit_before_handoff(parked, monkeypatch):
  from openpilot.system.manager import manager
  from openpilot.system.manager.process_config import managed_processes
  _, _, clock = parked
  events = []
  procs = {}
  for name in ('pandad', 'honda_brake_test', 'card', 'controlsd', 'selfdrived', 'plannerd', 'modeld', 'ui', 'hardwared', 'updated'):
    actual = managed_processes[name]
    procs[name] = SimpleNamespace(name=name, enabled=True, should_run=actual.should_run,
                                 start=lambda name=name: events.append(('start', name)),
                                 stop=lambda name=name, **kw: events.append(('stop', name, kw.get('block'))))
  monkeypatch.setattr(manager, 'managed_processes', procs)
  sm = StateSnapshot(clock[0])
  params = TestParams(HondaBrakeTest='requested')
  manager.ensure_manager_processes(sm, params, [], False)
  assert events.index(('stop', 'pandad', True)) < events.index(('start', 'honda_brake_test'))
  events.clear()
  sm['deviceState'].started = True
  sm['pandaStates'][0].ignitionLine = True
  manager.ensure_manager_processes(sm, params, [], True)
  assert {e[1] for e in events if e[0] == 'start'} == {'honda_brake_test', 'ui', 'hardwared'}
  events.clear()
  params.put(guided.MODE, 'restore')
  sm['deviceState'].started = False
  sm['pandaStates'][0].ignitionLine = False
  manager.ensure_manager_processes(sm, params, [], False)
  assert events.index(('stop', 'honda_brake_test', True)) < events.index(('start', 'pandad'))
  assert params.get(guided.MODE) is None


@pytest.mark.parametrize('failure', [None, 'length', 'pedal', 'restart', 'cancel'])
def test_guided_sequence_saves_result_and_waits_for_off_before_restore(parked, monkeypatch, failure):
  p, _, clock = parked
  p.state.update(ignition_line=failure == 'restart', car_harness_status=2)
  monkeypatch.setattr(p, 'get_type', lambda: b'\x09', raising=False)
  monkeypatch.setattr(p, 'set_fan_power', lambda _: None, raising=False)
  sm = StateSnapshot(clock[0])
  monkeypatch.setattr(guided.messaging, 'PubMaster', lambda _: Mock())
  monkeypatch.setattr(guided.messaging, 'SubMaster', lambda _: sm)
  cp = m.structs.CarParams.new_message(carFingerprint=guided.CAR.HONDA_ODYSSEY_5G_MMR)
  params = TestParams(HondaBrakeTest='cancel' if failure == 'cancel' else 'active', CarParamsPersistent=cp.to_bytes())
  if failure == 'length':
    p.response = bytes(55)
  output = io.StringIO()
  test = guided.GuidedTest(p, output, params)
  prompts = []
  prompt = test.prompt
  def operator(title, instruction):
    prompts.append((title, instruction))
    prompt(title, instruction)
    if title == 'Ready for the brake test':
      p.state['ignition_line'] = True
    if title.startswith('Step') and failure != 'pedal':
      p.values['POWERTRAIN_DATA']['BRAKE_PRESSED'] = int(instruction.startswith('Press'))
    if title.startswith(('Brake test complete', 'Brake test stopped')):
      assert params.get(guided.MODE) != 'restore'
      p.state['ignition_line'] = False
  monkeypatch.setattr(test, 'prompt', operator)
  receive = p.can_recv
  def stop_after_handshake():
    if params.get(guided.MODE) == 'restore':
      raise KeyboardInterrupt
    return receive()
  monkeypatch.setattr(p, 'can_recv', stop_after_handshake)
  started = clock[0]
  with pytest.raises(KeyboardInterrupt):
    test.run()
  assert params.get(guided.MODE) == 'restore'
  assert p.modes[-1] == (m.SAFETY.noOutput, 0)
  assert not p.state['ignition_line']
  rows = [json.loads(line) for line in output.getvalue().splitlines()]
  if failure is None:
    assert clock[0] - started >= 25_000_000_000
    assert any(t.startswith('Brake test complete') for t, _ in prompts)
    assert len([r for r in rows if r['type'] == 'qualified' and r['did'] == 0x4005]) >= 21
    steps = [t for t, _ in prompts if t.startswith('Step') and 'hold' not in t]
    assert steps == [f'Step {i} of 5' for i in range(1, 6)]
  else:
    assert any(t.startswith('Brake test stopped') for t, _ in prompts)
    assert not any(t.startswith('Brake test complete') for t, _ in prompts)
    if failure in ('restart', 'cancel'):
      assert not p.sent
  assert all((a, int.from_bytes(d[2:4], 'big')) in m.READS if d[0] == 3 else d.hex() == '30000a0000000000'
             for a, d, _ in p.sent)


def test_failed_capture_stays_in_test_mode_while_ignition_on(parked, monkeypatch):
  p, _, clock = parked
  p.state.update(car_harness_status=2)
  monkeypatch.setattr(p, 'get_type', lambda: b'\x09', raising=False)
  monkeypatch.setattr(p, 'set_fan_power', lambda _: None, raising=False)
  monkeypatch.setattr(guided.messaging, 'PubMaster', lambda _: Mock())
  monkeypatch.setattr(guided.messaging, 'SubMaster', lambda _: StateSnapshot(clock[0]))
  params = TestParams(HondaBrakeTest='active')
  test = guided.GuidedTest(p, io.StringIO(), params)
  def failed():
    raise RuntimeError('unsupported diagnostic')
  monkeypatch.setattr(test, 'sequence', failed)
  polls = []
  def stop_after_polling():
    polls.append(True)
    if len(polls) == 3:
      raise KeyboardInterrupt
    return []
  monkeypatch.setattr(p, 'can_recv', stop_after_polling)
  with pytest.raises(KeyboardInterrupt):
    test.run()
  assert params.get(guided.MODE) == 'active'
  assert 'stopped' in params.get(guided.STATUS)['title']
  assert p.state['safety_mode'] == m.SAFETY.noOutput
  assert not p.sent


def test_ownership_survives_manager_and_ignition_param_clears(tmp_path):
  from openpilot.common.params import Params, ParamKeyFlag
  params = Params(str(tmp_path))
  guided.request_test(params)
  for mode in ('requested', 'active', 'cancel', 'restore'):
    params.put(guided.MODE, mode, block=True)
    for flag in (ParamKeyFlag.CLEAR_ON_MANAGER_START, ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION,
                 ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION, ParamKeyFlag.CLEAR_ON_IGNITION_ON):
      params.clear_all(flag)
      assert params.get(guided.MODE) == mode


def test_cancel_request_does_not_change_alpha_long_or_other_vehicle_settings():
  params = TestParams(AlphaLongitudinalEnabled=True, ExperimentalMode=True)
  guided.request_test(params)
  guided.cancel_test(params)
  assert params.get(guided.MODE) is None
  assert params.get_bool('AlphaLongitudinalEnabled') and params.get_bool('ExperimentalMode')
  params.put(guided.MODE, 'active')
  guided.cancel_test(params)
  assert params.get(guided.MODE) == 'cancel'
  assert params.get_bool('AlphaLongitudinalEnabled')


@pytest.mark.parametrize('response', ['wrong_did', 'negative'])
def test_unrelated_or_negative_ecu_reply_is_not_pressure_data(parked, monkeypatch, response):
  p, c, _ = parked
  send = p.can_send
  def unrelated(address, data, bus, **kwargs):
    send(address, data, bus, **kwargs)
    if data[0] == 3:
      if response == 'negative':
        p.pending = [(m.get_rx_addr_for_tx_addr(address), bytes.fromhex('037f223100000000'), bus)]
      else:
        addr, frame, src = p.pending[-1]
        p.pending[-1] = (addr, frame[:4] + bytes([frame[4] ^ 1]) + frame[5:], src)
  monkeypatch.setattr(p, 'can_send', unrelated)
  with pytest.raises(RuntimeError, match='requested diagnostic'):
    c.read(0x18DA28F1, 0x4005)
  assert p.modes[-1] == (m.SAFETY.noOutput, 0)
  assert not any(json.loads(line)['type'] == 'qualified' for line in c.output.getvalue().splitlines())


def test_gear_warning_cannot_clear_itself_during_requalification(parked, monkeypatch):
  p, c, _ = parked
  receive = p.can_recv
  p.values['GEARBOX_AUTO']['GEAR_SHIFTER'] = 0
  def briefly_unknown():
    frames = receive()
    p.values['GEARBOX_AUTO']['GEAR_SHIFTER'] = 1
    return frames
  monkeypatch.setattr(p, 'can_recv', briefly_unknown)
  with pytest.raises(RuntimeError, match='Park'):
    c.qualify()
  assert not p.sent
