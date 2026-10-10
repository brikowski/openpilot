import json
import numpy as np
import pytest
from types import SimpleNamespace

import replay_carcontroller as replay
from replay_carcontroller import (gas_command_samples, gas_wire_comparison, make_replay_controller, received_at,
                                  replay_inputs, same_domain_gas_steps, twin_can_difference)
from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, CarControllerParams


def test_replay_initializes_odyssey_gas_map_without_replacing_recorded_params(monkeypatch):
  monkeypatch.setattr(CarControllerParams, 'BOSCH_GAS_LOOKUP_V', [0, 1600])
  recorded = CarInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
  recorded.steerActuatorDelay = .123
  recorded.mass = 2345.
  snapshot = recorded.to_dict()
  # Simulate a fresh replay process, which has not run Honda parameter initialization.
  CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 1600]
  controller = make_replay_controller(recorded)
  assert controller.params.BOSCH_GAS_LOOKUP_V == [0, 2000]
  assert controller.CP is recorded
  assert recorded.to_dict() == snapshot


def test_replay_copies_logged_params_without_exhausting_reader_budget():
  params = CarInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
  raw = params.to_bytes()
  with structs.CarParams.from_bytes(raw, traversal_limit_in_words=2048) as reader:
    snapshot = reader.to_dict()
    controller = make_replay_controller(reader)
    assert controller.CP.to_dict() == snapshot
    for _ in range(10000):
      assert controller.CP.carFingerprint == CAR.HONDA_ODYSSEY_5G_MMR


def test_replay_uses_card_snapshot_and_send_clock():
  def event(kind, value):
    if kind == "sendcan":
      return SimpleNamespace(which=lambda: kind, tag=value,
                             sendcan=[SimpleNamespace(address=0x18DAB0F1 if value == "diagnostic" else 0xE4)])
    return SimpleNamespace(which=lambda: kind, **{kind: value})

  messages = [event("sendcan", "before inputs"), event("carState", "s0"),
              event("carControl", "c0"), event("sendcan", "before sampled control"),
              event("carState", "s1"), event("carControl", "c1"), event("sendcan", "tx1"),
              event("sendcan", "diagnostic"),
              event("carState", "s2"), event("sendcan", "tx2"),
              event("carState", "s3"), event("sendcan", "tx3")]
  assert [(tx.tag, control, state) for tx, control, state in replay_inputs(messages)] == [
    ("tx1", "c0", "s1"), ("tx2", "c1", "s2"), ("tx3", "c1", "s3")]


def test_received_powertrain_snapshot_never_uses_future_can_and_preserves_nanoseconds():
  base = 1_790_380_243_664_559_620
  updates = (np.asarray([base, base + 20_000_000], dtype=np.int64),
             np.asarray([[-130., 0.], [-180., 0.]]))
  assert received_at(base - 1, updates) is None
  assert received_at(base, updates) == (base, -130., 0.)
  assert received_at(base + 19_999_999, updates) == (base, -130., 0.)
  assert received_at(base + 20_000_000, updates) == (base + 20_000_000, -180., 0.)


def test_received_braking_uses_powertrain_bus_and_independent_timestamp(monkeypatch):
  from opendbc.can import CANPacker
  packer = CANPacker(replay.ODYSSEY_PT_DBC)
  base = 1_790_380_243_664_559_620

  def event(time, frames, kind='can'):
    return SimpleNamespace(which=lambda: kind, logMonoTime=time,
                           can=[SimpleNamespace(address=a, dat=d, src=b) for a, d, b in frames])

  brake = packer.make_can_msg('VSA_STATUS', 1, {'COMPUTER_BRAKING': 1, 'USER_BRAKE': .125})
  coast = packer.make_can_msg('VSA_STATUS', 1, {'COMPUTER_BRAKING': 0, 'USER_BRAKE': .015625})
  messages = [event(base, [brake]), event(base + 10_000_000, [coast], 'sendcan'),
              event(base + 20_000_000, [(coast[0], coast[1], 0)]),
              event(base + 30_000_000, [packer.make_can_msg('GAS_PEDAL_2', 1, {'ENGINE_TORQUE_ESTIMATE': -120})]),
              event(base + 40_000_000, [coast]),
              event(base + 50_000_000, [packer.make_can_msg('GEARBOX_AUTO', 1,
                                                         {'TRANS_TARGET_GEAR': 7, 'TRANS_SHIFT_ACTIVITY': 119, 'COUNTER': 1})])]
  monkeypatch.setattr(replay, 'LogReader', lambda _: messages)
  torque, gear, braking = replay.odyssey_received_state(['synthetic'])
  assert received_at(base - 1, braking) is None
  assert received_at(base + 39_999_999, braking) == (base, 1., .125)
  assert received_at(base + 40_000_000, braking) == (base + 40_000_000, 0., .015625)
  assert received_at(base + 39_999_999, torque) == (base + 30_000_000, -120., 0.)
  assert received_at(base + 40_000_000, gear) is None
  assert received_at(base + 50_000_000, gear) == (base + 50_000_000, 7., 119.)


@pytest.mark.parametrize('bound', ['carState', 'sendcan'])
@pytest.mark.parametrize('disable_release', [False, True])
def test_replay_applies_timing_bound_to_both_controllers_and_reports_it(monkeypatch, tmp_path, bound, disable_release):
  params = CarInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
  control = structs.CarControl.new_message()
  control.longActive = True
  control.actuators.accel = 0.1
  control.actuators.longControlState = structs.CarControl.Actuators.LongControlState.pid
  control = control.as_reader()
  state = structs.CarState.new_message()
  state.vEgo = 10.

  def event(kind, time, value):
    return SimpleNamespace(which=lambda: kind, logMonoTime=time, **{kind: value})

  start = 1_000_000_000
  messages = [event('carParams', start, params), event('carControl', start + 1, control)]
  state_times, send_times = [], []
  for tick in range(60):
    state_time = start + 10_000_000 * (tick + 1)
    # A publication delay can cross freshness thresholds without changing the sampled inputs.
    send_time = state_time + (70_000_000 if tick == 59 else 1_000_000)
    state_times.append(state_time)
    send_times.append(send_time)
    frames = [SimpleNamespace(address=0xE4, src=1, dat=bytes(5))]
    if tick % 2 == 0:
      frames.append(SimpleNamespace(address=0x1DF, src=1, dat=bytes(8)))
    messages.extend([event('carOutput', state_time - 1, SimpleNamespace(actuatorsOutput=SimpleNamespace(accel=.1))),
                     event('carState', state_time, state), event('sendcan', send_time, frames)])

  monkeypatch.setattr(replay, 'LogReader', lambda _: messages)
  calls = []
  real_update = replay.CarController.update

  def capture_time(self, control, state, now):
    calls.append(now)
    return real_update(self, control, state, now)

  monkeypatch.setattr(replay.CarController, 'update', capture_time)
  from opendbc.car.honda import carcontroller as honda
  release_calls = []
  real_release = honda.odyssey_brake_release

  def capture_release(*args, **kwargs):
    release_calls.append(args[0])
    return real_release(*args, **kwargs)

  monkeypatch.setattr(honda, 'odyssey_brake_release', capture_release)
  output = tmp_path / 'timing.json'
  options = ['--disable-brake-release'] if disable_release else []
  replay.main(['synthetic/rlog.zst', str(output), '--controller-time-bound', bound, '--compare-no-release', *options])
  result = json.loads(output.read_text())
  expected_times = state_times if bound == 'carState' else send_times
  assert calls == [time for time in expected_times for _ in range(2)]
  assert release_calls == ([] if disable_release else expected_times[::2])
  assert result['controller_time_bound'] == bound
  assert result['controller_time_gap_max_ms'] == 70.
  assert result['same_cycle_gas_wire_comparison']['paired'] == 30
  assert result['same_cycle_gas_wire_comparison']['recorded_unpaired'] == 0
  assert result['same_cycle_gas_wire_comparison']['replayed_unpaired'] == 0


def test_twin_difference_separates_acc_payload_from_schedule_and_other_can():
  reference = [(0x1DF, b'old', 1), (0xE4, b'steer', 1)]
  assert twin_can_difference(reference, [(0x1DF, b'new', 1), (0xE4, b'steer', 1)]) == {
    'schedule_mismatch': 0, 'acc_changed': 1, 'other_changed': 0}
  assert twin_can_difference(reference, [(0x1DF, b'old', 1), (0xE4, b'changed', 1)]) == {
    'schedule_mismatch': 0, 'acc_changed': 0, 'other_changed': 1}
  assert twin_can_difference(reference, [(0x1DF, b'old', 1)])['schedule_mismatch'] == 1


def test_gas_steps_use_transmitted_frames_not_held_controller_ticks():
  samples = []
  for tick in range(200):
    gas = 150 if tick == 198 else 0
    sends = [(0x1DF, gas.to_bytes(2, "big", signed=True) + bytes(6), 1)] if tick % 2 == 0 else []
    samples.extend(gas_command_samples(tick * 10_000_000, sends))
  assert len(samples) == 100
  result = same_domain_gas_steps(samples)
  assert result["pairs"] == 99
  assert result["max"] == 150
  assert result["over_100"] == 1
  assert np.isclose(result["p99"], 3.0)
  assert gas_command_samples(0, [(0x1DF, bytes(8), 0), (0xE4, bytes(8), 1)]) == []


def test_wire_comparison_keeps_unpaired_cycles_and_domain_disagreements():
  rec = [(0., 100), (.02, 200), (.04, -30000), (.06, 200)]
  rep = [(0., 100), (.02, 180), (.04, 100), (.08, 200)]
  assert gas_wire_comparison(rec, rep) == {
    "paired": 3, "recorded_unpaired": 1, "replayed_unpaired": 1, "exact": 1,
    "max_abs_error": 30100., "active_gas_paired": 2, "active_gas_exact": 1,
    "active_gas_max_abs_error": 20.}
  assert gas_wire_comparison([], [])['max_abs_error'] is None
  with pytest.raises(ValueError, match="multiple ACC_CONTROL"):
    gas_wire_comparison(rec + [rec[0]], rep)


def test_gas_steps_exclude_domain_edges_gaps_and_nonmonotonic_time():
  samples = [(0.00, 100), (0.02, 110), (0.04, -30000), (0.06, 1000),
             (0.20, 0), (0.20, 999), (0.19, 500)]
  assert same_domain_gas_steps(samples) == {"max": 10.0, "p99": 10.0, "over_100": 0, "pairs": 1}
