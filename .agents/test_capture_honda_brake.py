"""Exercise parked-only diagnostic capture through the pinned CAN and UDS parsers."""
import io
import json
import subprocess

import pytest

import capture_honda_brake as m
from opendbc.can import CANPacker


class RecordedPanda:
  def __init__(self):
    self.packer = CANPacker(m.DBC_NAME)
    self.tick = 0
    self.values = {"ENGINE_DATA": {"XMISSION_SPEED": 0}, "WHEEL_SPEEDS": {},
                   "GEARBOX_AUTO": {"GEAR_SHIFTER": 1}}
    self.state = {"safety_mode": m.SAFETY.noOutput, "controls_allowed": False, "faults": 0,
                  "ignition_line": True, "ignition_can": False}
    self.sent, self.modes, self.pending = [], [], []
    self.response = bytes(range(56))
    self.interrupt = False

  def health(self):
    return dict(self.state)

  def set_safety_mode(self, mode, param=0):
    self.modes.append((mode, param))
    self.state['safety_mode'] = mode

  def can_recv(self):
    self.tick += 1
    frames = [self.packer.make_can_msg(name, 1, {**values, **({"COUNTER": self.tick % 4} if name != 'WHEEL_SPEEDS' else {})})
              for name, values in self.values.items()]
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
      self.rest = [(m.UdsClient(self, address).rx_addr,
                    (bytes([0x20 | (i % 16)]) + payload[start:start+7]).ljust(8, b'\0'), bus)
                   for i, start in enumerate(range(6, len(payload), 7), 1)]
      self.pending.append((m.UdsClient(self, address).rx_addr, first, bus))
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
  p.state['safety_mode'] = m.SAFETY.elm327
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
  with pytest.raises(TimeoutError, match='one second'):
    c.read(0x18DA28F1, 0x4005)
  assert 1_000_000_000 < clock[0] - started_ns <= 1_100_000_000
  assert c.read_deadline_ns == 0


def test_records_complete_diagnostic_response_and_raw_can_flags(parked):
  p, c, _ = parked
  p.state['safety_mode'] = m.SAFETY.elm327
  c.read(0x18DA28F1, 0x4005)
  p.pending = [(0xE7, bytes.fromhex('140500a08b'), 1), (0x1DF, bytes(8), 129), (0x1DF, bytes(8), 193)]
  c.can_recv()
  rows = [json.loads(line) for line in c.output.getvalue().splitlines()]
  response = next(r for r in rows if r['type'] == 'uds')
  assert response['data_hex'] == p.response.hex()
  assert response['started_ns'] <= response['mono_ns']
  assert rows[-1]['frames'][-3:] == [[0xE7, '140500a08b', 1], [0x1DF, '00'*8, 129], [0x1DF, '00'*8, 193]]
  assert [data[:4] for _, data, _ in p.sent] == [bytes.fromhex('03224005'), bytes.fromhex('30000000')]


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
  assert p.modes == [(m.SAFETY.elm327, 1), (m.SAFETY.noOutput, 0)]
  assert p.state['safety_mode'] == m.SAFETY.noOutput
  requests = [(a, int.from_bytes(d[2:4], 'big')) for a, d, _ in p.sent if d[0] == 3]
  assert requests[:2] == [(0x18DA28F1, 0xF181), (0x18DA2BF1, 0xF181)]
  assert all(r in m.READS for r in requests)
  if failure == 'length':
    assert any(json.loads(line).get('data_hex') == bytes(55).hex() for line in output.getvalue().splitlines())


def test_initial_unsafe_state_does_not_change_panda_mode(parked):
  p, _, _ = parked
  p.state['controls_allowed'] = True
  with pytest.raises(RuntimeError):
    m.capture(p, io.StringIO(), 1)
  assert not p.modes and not p.sent


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
