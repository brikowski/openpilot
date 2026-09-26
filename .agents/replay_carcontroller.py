#!/usr/bin/env python3
"""Open-loop counterfactual replay of honda/carcontroller.py over a recorded route.

Drives CarController with the route's carControl request and recorded carState response on
logged card send cycles. Like card.py, each state publication uses the control sampled before
that state, not the next controlsd publication. This reconstructs subscription timing from log
timestamps; same-source wire agreement must verify it before interpreting internal state.

Because both inputs are recorded, they are byte-identical across opendbc branches: any difference
in the resulting wire command (ACCEL_COMMAND) is purely our carcontroller. That makes the replay
useful for command-fidelity regressions at zero driving risk.

For the Odyssey brake-release screen, replay also holds actual received bus-1 powertrain CAN
at the latest carState publication. --compare-no-release runs a same-input controller twin
with only the release helper ablated and checks every scheduled outgoing CAN payload.

LIMIT: open-loop. The car's response (aEgo) is the one the OLD controller produced, so this shows
what the new controller would COMMAND, not how the car would then behave. Command shape and
magnitude are valid. BRAKE_REQUEST transition counts are not closed-loop predictions: changing
the command would change aEgo and the planner's next request on-road, but both are frozen here.


Usage: replay_carcontroller.py <segment-range> <out.json>
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from openpilot.tools.lib.logreader import LogReader
from opendbc.car import Bus, gen_empty_fingerprint
from opendbc.car.values import PLATFORMS
from opendbc.car.honda.carcontroller import (ODYSSEY_LOW_SPEED_DOMAIN_VEGO, ODYSSEY_RESPONSE_DELAY_FRAMES,
                                             ODYSSEY_ROAD_BRAKE_ENTRY, CarController)
from opendbc.car.honda.interface import CarInterface

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tuning_metrics import causal_lpf, mild_negative_brake_release_events, windowed_jerk
from validate_log import GAS_INACTIVE, JERK_SMOOTH_TAU, JERK_WIN_S, _local_segment_names

ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"


def make_replay_controller(recorded_params):
  """Initialize candidate platform constants but retain the route's recorded CarParams.

  Honda's interface sets class-level gas maps outside the serialized CarParams. Constructing
  only CarController silently leaves the default map in place. The throwaway parameters below
  initialize those constants; they must not replace recorded flags, limits, or tuning.
  This calls parameter construction only, never the interface's ECU-disabling init method.
  """
  CarInterface.get_params(recorded_params.carFingerprint, gen_empty_fingerprint(),
                          list(recorded_params.carFw), recorded_params.openpilotLongitudinalControl,
                          False, False)
  dbc = PLATFORMS[recorded_params.carFingerprint].config.dbc_dict
  return CarController({Bus.pt: dbc[Bus.pt]}, recorded_params)


def gas_command_samples(mono, sends):
  """Keep physical Alpha Long ACC_CONTROL frames, including repeated transmitted values."""
  return [(mono / 1e9, int.from_bytes(dat[:2], "big", signed=True))
          for addr, dat, bus in sends if addr == 0x1DF and bus == 1]


def replay_inputs(messages):
  """Yield send cycles with the state and control card could have consumed.

  Input must be chronological. card samples carControl before publishing carState, and then
  actuates that snapshot; a newer carControl arriving before sendcan belongs to the next cycle.
  Honda sends STEERING_CONTROL every controller cycle. Exclude separate UDS/fingerprinting
  sends, which must not advance controller state or the 50 Hz longitudinal phase.
  """
  latest_control = control = state = None
  for message in messages:
    kind = message.which()
    if kind == "carControl":
      latest_control = message.carControl
    elif kind == "carState":
      state = message.carState
      control = latest_control
    elif (kind == "sendcan" and state is not None and control is not None and
          any(frame.address in (0xE4, 0x194) for frame in message.sendcan)):
      yield message, control, state


def gas_wire_comparison(recorded, replayed):
  """Compare actual TX cycles without shifting timestamps to maximize agreement."""
  rec, rep = dict(recorded), dict(replayed)
  if len(rec) != len(recorded) or len(rep) != len(replayed):
    raise ValueError("multiple ACC_CONTROL frames at one send timestamp")
  shared = rec.keys() & rep.keys()
  pairs = np.asarray([(rec[t], rep[t]) for t in sorted(shared)], dtype=float).reshape(-1, 2)
  error = np.abs(pairs[:, 0] - pairs[:, 1])
  gas = np.all(pairs > GAS_INACTIVE, axis=1)
  return {"paired": len(shared), "recorded_unpaired": len(rec.keys() - rep.keys()),
          "replayed_unpaired": len(rep.keys() - rec.keys()),
          "exact": int(np.sum(error == 0)),
          "max_abs_error": float(np.max(error)) if len(error) else None,
          "active_gas_paired": int(np.sum(gas)),
          "active_gas_exact": int(np.sum(gas & (error == 0))),
          "active_gas_max_abs_error": float(np.max(error[gas])) if gas.any() else None}


def same_domain_gas_steps(samples):
  if len(samples) < 2:
    return {"max": 0.0, "p99": 0.0, "over_100": 0, "pairs": 0}
  arr = np.asarray(samples, dtype=float)
  gaps = np.diff(arr[:, 0])
  valid = ((arr[1:, 1] > GAS_INACTIVE) & (arr[:-1, 1] > GAS_INACTIVE) &
           (gaps > 0.0) & (gaps < 0.04))
  steps = np.abs(np.diff(arr[:, 1]))[valid]
  return {"max": float(np.max(steps)) if len(steps) else 0.0,
          "p99": float(np.percentile(steps, 99)) if len(steps) else 0.0,
          "over_100": int(np.sum(steps > 100)), "pairs": len(steps)}


class _ZeroDict(dict):
  """Stock HUD signal dicts; missing keys read 0 so HUD packing can't crash the replay."""
  def __missing__(self, k):
    return 0


class _CSShim:
  """The controller reads CS.out.* plus a handful of CarState fields. Everything besides .out
  (is_metric, v_cruise_factor, acc_hud, lkas_hud, stock_brake) feeds only the HUD/UI CAN messages,
  never ACCEL_COMMAND or GAS_COMMAND, so stubbing them cannot affect the metrics measured here."""
  def __init__(self):
    self.out = None
    self.is_metric = False
    self.v_cruise_factor = 0.44704   # MPH_TO_MS
    self.acc_hud = _ZeroDict()
    self.lkas_hud = _ZeroDict()
    self.stock_brake = _ZeroDict()
    self.odyssey_engine_torque_estimate = np.nan
    self.odyssey_car_gas = np.nan
    self.odyssey_engine_torque_ts_nanos = 0
    self.odyssey_target_gear = 0


def odyssey_received_state(paths):
  """Only actual received powertrain updates may feed the candidate controller replay."""
  from opendbc.can.parser import CANParser
  parser = CANParser(ODYSSEY_PT_DBC, [('GAS_PEDAL_2', 0), ('GEARBOX_AUTO', 0)], 1)
  torque, gear = [], []
  for m in LogReader(paths):
    if m.which() != 'can':
      continue
    frames = [(c.address, c.dat, c.src) for c in m.can if c.src == 1 and c.address in (0x130, 0x1a3)]
    if not frames:
      continue
    parser.update([(m.logMonoTime, frames)])
    if any(addr == 0x130 for addr, _, _ in frames):
      signals = parser.vl['GAS_PEDAL_2']
      torque.append((m.logMonoTime, signals['ENGINE_TORQUE_ESTIMATE'], signals['CAR_GAS']))
    if any(addr == 0x1a3 for addr, _, _ in frames):
      gear.append((m.logMonoTime, parser.vl['GEARBOX_AUTO']['TRANS_TARGET_GEAR']))
  def pack(rows, width):
    return (np.asarray([row[0] for row in rows], dtype=np.int64),
            np.asarray([row[1:] for row in rows], dtype=float).reshape(-1, width))
  return pack(torque, 2), pack(gear, 1)


def received_at(time_nanos, updates):
  """Hold only updates at or before the carState publication that card consumed."""
  times, values = updates
  index = int(np.searchsorted(times, time_nanos, side='right') - 1)
  return (int(times[index]), *values[index]) if index >= 0 else None


def twin_can_difference(reference, candidate):
  """Compare exact same-cycle frames before interpreting a Honda-domain counterfactual."""
  if len(reference) != len(candidate):
    return {'schedule_mismatch': 1, 'acc_changed': 0, 'other_changed': 0}
  schedule_mismatch = acc_changed = other_changed = 0
  for (ref_addr, ref_data, ref_bus), (cand_addr, cand_data, cand_bus) in zip(reference, candidate, strict=True):
    if (ref_addr, ref_bus) != (cand_addr, cand_bus):
      schedule_mismatch += 1
    elif ref_data != cand_data:
      if cand_addr == 0x1df and cand_bus == 1:
        acc_changed += 1
      else:
        other_changed += 1
  return {'schedule_mismatch': schedule_mismatch, 'acc_changed': acc_changed, 'other_changed': other_changed}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("segments", help="local route ID or LogReader segment range")
  parser.add_argument("output", help="JSON output path")
  parser.add_argument("--disable-brake-release", action="store_true", help="Ablate only the Odyssey early-release helper")
  parser.add_argument("--compare-no-release", action="store_true", help="Twin replay against a no-release controller on identical inputs")
  args = parser.parse_args(argv)
  seg_range, out_path = args.segments, args.output
  # Accept a bare local route id as well as anything LogReader understands. Passing a
  # comma-joined path list hits the OS filename length limit on a 47-segment route.
  if "/" not in seg_range and "|" not in seg_range:
    import os
    from openpilot.common.hardware.hw import Paths
    root = Paths.log_root()
    segs = _local_segment_names(seg_range, root)
    src = [os.path.join(root, s, "rlog.zst") for s in segs]
    if not src:
      sys.exit(f"no local segments for {seg_range}")
  else:
    src = seg_range
  streams = {"carParams", "carControl", "carState", "carOutput", "sendcan"}
  msgs = sorted((m for m in LogReader(src) if m.which() in streams), key=lambda m: m.logMonoTime)

  CP = next(m.carParams for m in msgs if m.which() == "carParams")
  cc = make_replay_controller(CP)
  if args.disable_brake_release:
    cc.odyssey_brake_release.update = lambda *unused: False
  baseline = make_replay_controller(CP) if args.compare_no_release else None
  if baseline is not None:
    baseline.odyssey_brake_release.update = lambda *unused: False
  torque_updates, gear_updates = odyssey_received_state(src) if CP.carFingerprint == "HONDA_ODYSSEY_5G_MMR" else (None, None)
  state_times = np.asarray([m.logMonoTime for m in msgs if m.which() == 'carState'], dtype=np.int64)

  cs_shim = _CSShim()
  release_edges = []
  twin = {'schedule_mismatch': 0, 'acc_changed': 0, 'other_changed': 0,
          'brake_domain_different_cycles': 0, 'output_accel_different_cycles': 0}
  t, requested, wire, active, sendcans, gas_feedback, pitch, aego, feedback_age = [], [], [], [], [], [], [], [], []
  speed, pid, gas_pressed, brake_pressed = [], [], [], []
  rec_t, rec_wire, rec_gas, replay_gas = [], [], [], []
  for m in msgs:
    w = m.which()
    if w == "carOutput":
      # the wire the OLD controller actually put out on this drive (the baseline arm)
      rec_t.append(m.logMonoTime / 1e9)
      rec_wire.append(float(m.carOutput.actuatorsOutput.accel))
    elif w == "sendcan":
      rec_gas.extend(gas_command_samples(m.logMonoTime, [(f.address, f.dat, f.src) for f in m.sendcan]))
  for m, control, state in replay_inputs(msgs):
    cs_shim.out = state
    if torque_updates is not None:
      state_time = state_times[np.searchsorted(state_times, m.logMonoTime, side='right') - 1]
      received_torque = received_at(state_time, torque_updates)
      received_gear = received_at(state_time, gear_updates)
      cs_shim.odyssey_engine_torque_estimate = received_torque[1] if received_torque is not None else np.nan
      cs_shim.odyssey_car_gas = received_torque[2] if received_torque is not None else np.nan
      cs_shim.odyssey_engine_torque_ts_nanos = int(received_torque[0]) if received_torque is not None else 0
      cs_shim.odyssey_target_gear = received_gear[1] if received_gear is not None else 0
    # Seed only the initial longitudinal phase; do not hide missing cycles by reseeding later.
    if not t and CP.openpilotLongitudinalControl and CP.carFingerprint == "HONDA_ODYSSEY_5G_MMR":
      cc.frame = 0 if any(f.address == 0x1DF and f.src == 1 for f in m.sendcan) else 1
      if baseline is not None:
        baseline.frame = cc.frame
    previous_brake = cc.odyssey_brake_selected
    actuators, can_sends = cc.update(control, cs_shim, m.logMonoTime)
    if baseline is not None:
      base_actuators, base_sends = baseline.update(control, cs_shim, m.logMonoTime)
      diff = twin_can_difference(base_sends, can_sends)
      for key, count in diff.items():
        twin[key] += count
      twin['brake_domain_different_cycles'] += baseline.odyssey_brake_selected != cc.odyssey_brake_selected
      twin['output_accel_different_cycles'] += abs(base_actuators.accel - actuators.accel) > 1e-6
    if previous_brake and not cc.odyssey_brake_selected and control.longActive and control.actuators.accel < 0.:
      release_edges.append((m.logMonoTime / 1e9, float(control.actuators.accel), float(state.aEgo),
                            float(cs_shim.odyssey_engine_torque_estimate), float(cs_shim.odyssey_target_gear)))
    t.append(m.logMonoTime / 1e9)
    requested.append(float(control.actuators.accel))
    wire.append(float(actuators.accel))
    active.append(bool(control.longActive))
    sendcans.append((m.logMonoTime, can_sends))
    replay_gas.extend(gas_command_samples(m.logMonoTime, can_sends))
    gas_feedback.append(float(cc.odyssey_gas_response.correction))
    pitch.append(float(control.orientationNED[1]) if len(control.orientationNED) == 3 else np.nan)
    aego.append(float(cs_shim.out.aEgo))
    speed.append(float(state.vEgo))
    pid.append(str(control.actuators.longControlState) == "pid")
    gas_pressed.append(bool(state.gasPressed))
    brake_pressed.append(bool(state.brakePressed))
    feedback_age.append(len(cc.odyssey_gas_response.requests))

  t = np.array(t)
  requested = np.array(requested, dtype=float)
  wire = np.array(wire, dtype=float)
  act = np.array(active, dtype=bool)
  gas_feedback = np.array(gas_feedback, dtype=float)
  pitch = np.array(pitch, dtype=float)
  aego = np.array(aego, dtype=float)
  speed = np.array(speed, dtype=float)
  pid = np.array(pid, dtype=bool)
  gas_pressed = np.array(gas_pressed, dtype=bool)
  brake_pressed = np.array(brake_pressed, dtype=bool)
  feedback_age = np.array(feedback_age, dtype=int)
  if len(t) < 50:
    print(f"TOO FEW FRAMES ({len(t)}) - aborting")
    sys.exit(2)
  dt = float(np.median(np.diff(t)))

  def stats(w_sig, a):
    wj = windowed_jerk(causal_lpf(w_sig, dt, JERK_SMOOTH_TAU), dt, a, JERK_WIN_S)
    deep = a & (wj < -0.5)
    positive = a & (requested > 0.02)
    just_engaged = np.zeros_like(a)
    edge_window = max(1, int(round(0.5 / dt)))
    for edge in np.where(np.diff(a.astype(int), prepend=0) == 1)[0]:
      just_engaged[edge:edge + edge_window] = True
    reengage_positive = positive & just_engaged
    positive_idx = np.where(positive)[0]
    reengage_idx = np.where(reengage_positive)[0]
    worst_positive_idx = (positive_idx[np.argmin(w_sig[positive] - requested[positive])]
                          if len(positive_idx) else None)
    worst_reengage_idx = (reengage_idx[np.argmin(w_sig[reengage_positive] - requested[reengage_positive])]
                          if len(reengage_idx) else None)
    return {
      "wire_jerk_max": float(-np.min(wj)),
      "wire_jerk_p99": float(-np.percentile(wj, 1)),
      "wire_jerk_onset_mean": float(np.mean(wj[deep])) if deep.sum() > 10 else 0.0,
      "wire_jerk_onsets": int(np.sum(np.diff(deep.astype(int)) == 1)),
      "wire_min": float(np.min(w_sig)),
      "brake_frames": int((a & (w_sig < -0.3)).sum()),
      "request_error_rms": float(np.sqrt(np.mean((w_sig[a] - requested[a]) ** 2))),
      "positive_request_worst": float(np.min(w_sig[positive] - requested[positive])) if positive.any() else 0.0,
      "reengagement_positive_worst": (float(np.min(w_sig[reengage_positive] - requested[reengage_positive]))
                                      if reengage_positive.any() else 0.0),
      "positive_request_worst_time": float(t[worst_positive_idx] - t[0]) if worst_positive_idx is not None else None,
      "reengagement_positive_worst_time": (float(t[worst_reengage_idx] - t[0])
                                           if worst_reengage_idx is not None else None),
    }

  # recorded baseline, resampled onto the same grid so both arms are measured identically
  rec = np.interp(t, np.array(rec_t), np.array(rec_wire)) if rec_t else np.full_like(t, np.nan)
  steep_nearzero = act & (pitch >= 0.05) & (np.abs(requested) <= 0.15)
  steep_shortfall = steep_nearzero & ((requested - aego) >= 0.15)

  # true domain handoff, decoded from the CAN this controller would actually have sent
  flips = forceful = coast_entries = 0
  brake_domain_frames = gas_domain_frames = coast_domain_frames = 0
  negative_live_gas_frames = negative_live_gas_events = 0
  total_edges = []
  physical_cycles = []
  try:
    from opendbc.can.parser import CANParser
    cp = CANParser(ODYSSEY_PT_DBC, [("ACC_CONTROL", 0)], 1)
    prev = prev_domain = None
    previous_negative_live = False
    for i, (mono, sends) in enumerate(sendcans):
      cp.update([(mono, [(addr, dat, src) for addr, dat, src in sends])])
      if cp.can_valid:
        br = int(cp.vl["ACC_CONTROL"]["BRAKE_REQUEST"])
        ac = float(cp.vl["ACC_CONTROL"]["ACCEL_COMMAND"])
        gas = float(cp.vl["ACC_CONTROL"]["GAS_COMMAND"])
        if any(addr == 0x1DF and src == 1 for addr, _, src in sends):
          physical_cycles.append((mono / 1e9, requested[i], aego[i], speed[i], pitch[i], act[i], pid[i],
                                  gas_pressed[i], brake_pressed[i], br, gas))
        if act[i]:
          domain = "brake" if br else ("gas" if gas > GAS_INACTIVE else "coast")
          negative_live = domain == "gas" and gas < 0
          negative_live_gas_frames += negative_live
          negative_live_gas_events += negative_live and not previous_negative_live
          previous_negative_live = negative_live
          brake_domain_frames += domain == "brake"
          gas_domain_frames += domain == "gas"
          coast_domain_frames += domain == "coast"
          if domain == "coast" and prev_domain != "coast":
            coast_entries += 1
          prev_domain = domain
        else:
          prev_domain = None
          previous_negative_live = False
        if prev is not None and br != prev:
          flips += 1
          total_edges.append(mono)
          if abs(ac) > 0.3:
            forceful += 1
        prev = br
  except Exception as e:
    print(f"  (sendcan decode failed: {e})")

  physical_releases = []
  if len(physical_cycles) >= 2:
    cycle = np.asarray(physical_cycles, dtype=float)
    entry = np.where(cycle[:, 3] < ODYSSEY_LOW_SPEED_DOMAIN_VEGO, 0., ODYSSEY_ROAD_BRAKE_ENTRY)
    physical_releases = mild_negative_brake_release_events(
      cycle[:, 0], cycle[:, 1], cycle[:, 2], cycle[:, 3], cycle[:, 4],
      cycle[:, 5], cycle[:, 6], cycle[:, 7], cycle[:, 8], cycle[:, 9], cycle[:, 10],
      gas_inactive=GAS_INACTIVE, entry_threshold=entry)

  res = {
    "seg_range": seg_range,
    "replay_clock": "recorded_sendcan_with_pre_state_control_snapshot",
    "gas_lookup_values": list(cc.params.BOSCH_GAS_LOOKUP_V),
    "brake_release_ablation": args.disable_brake_release,
    "early_release_edges": [{"route_time_s": round(edge[0] - t[0], 3), "request": edge[1],
                             "aego": edge[2], "engine_torque_estimate": edge[3], "target_gear": edge[4]}
                            for edge in release_edges],
    "early_release_physical_events_open_loop_only": physical_releases,
    "same_input_no_release_twin": twin if baseline is not None else None,
    "frames": int(len(t)), "engaged_frames": int(act.sum()),
    "replayed": {**stats(wire, act), "domain_flips_open_loop_only": flips,
                 "domain_forceful_open_loop_only": forceful,
                 "brake_domain_frames_open_loop_only": brake_domain_frames,
                 "gas_domain_frames_open_loop_only": gas_domain_frames,
                 "coast_domain_frames_open_loop_only": coast_domain_frames,
                 "coast_entries_open_loop_only": coast_entries,
                 "negative_live_gas_frames_open_loop_only": negative_live_gas_frames,
                 "negative_live_gas_events_open_loop_only": negative_live_gas_events},
    "recorded": stats(rec, act),
    # fidelity: on the SAME branch that produced the log this must be ~0. If it is not, the
    # replay is not reproducing the drive and no A/B conclusion drawn from it is trustworthy.
    "replay_vs_recorded_rms": float(np.sqrt(np.nanmean((wire[act] - rec[act]) ** 2))) if act.sum() else None,
    "same_domain_gas_steps": {"replayed": same_domain_gas_steps(replay_gas),
                              "recorded": same_domain_gas_steps(rec_gas)},
    "same_cycle_gas_wire_comparison": gas_wire_comparison(rec_gas, replay_gas),
    "gas_feedback": {
      "positive_seconds": float(np.sum(gas_feedback > 0) * dt),
      "negative_seconds": float(np.sum(gas_feedback < 0) * dt),
      "positive_max_counts": float(np.max(gas_feedback)),
      "negative_max_counts": float(np.min(gas_feedback)),
      "max_step_counts": float(np.max(np.abs(np.diff(gas_feedback)))),
      "steep_nearzero_seconds": float(np.sum(steep_nearzero) * dt),
      "steep_nearzero_positive_seconds": float(np.sum(steep_nearzero & (gas_feedback > 0)) * dt),
      "steep_nearzero_median_counts": float(np.median(gas_feedback[steep_nearzero])) if steep_nearzero.any() else None,
      "steep_shortfall_seconds": float(np.sum(steep_shortfall) * dt),
      "steep_shortfall_delay_aligned_seconds": float(np.sum(steep_shortfall & (feedback_age > ODYSSEY_RESPONSE_DELAY_FRAMES)) * dt),
      "steep_shortfall_positive_seconds": float(np.sum(steep_shortfall & (gas_feedback > 0)) * dt),
    },
  }
  with open(out_path, "w") as f:
    json.dump(res, f, indent=2)
  print(json.dumps(res, indent=2))


if __name__ == "__main__":
  main()
