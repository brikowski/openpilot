#!/usr/bin/env python3
"""Open-loop counterfactual replay of honda/carcontroller.py over a recorded route.

Drives CarController directly with the route's own carControl (the planner command) and carState
(the car's recorded response), exactly as card.py does -- card passes the capnp readers straight
into CI.apply, so the controller duck-types on them and no openpilot native build is needed.

Because both inputs are recorded, they are byte-identical across opendbc branches: any difference
in the resulting wire command (ACCEL_COMMAND) is purely our carcontroller. That makes the replay
useful for command-fidelity regressions at zero driving risk.

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
from opendbc.car import Bus
from opendbc.car.values import PLATFORMS
from opendbc.car.honda.carcontroller import CarController

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tuning_metrics import causal_lpf, windowed_jerk
from validate_log import GAS_INACTIVE, JERK_SMOOTH_TAU, JERK_WIN_S, _local_segment_names

ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"


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


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("segments", help="local route ID or LogReader segment range")
  parser.add_argument("output", help="JSON output path")
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
  msgs = list(LogReader(src))

  CP = next(m.carParams for m in msgs if m.which() == "carParams")
  dbc = PLATFORMS[CP.carFingerprint].config.dbc_dict
  cc = CarController({Bus.pt: dbc[Bus.pt]}, CP)

  cs_shim = _CSShim()
  t, requested, wire, active, sendcans = [], [], [], [], []
  rec_t, rec_wire = [], []
  for m in msgs:
    w = m.which()
    if w == "carState":
      cs_shim.out = m.carState
    elif w == "carOutput":
      # the wire the OLD controller actually put out on this drive (the baseline arm)
      rec_t.append(m.logMonoTime / 1e9)
      rec_wire.append(float(m.carOutput.actuatorsOutput.accel))
    elif w == "carControl" and cs_shim.out is not None:
      actuators, can_sends = cc.update(m.carControl, cs_shim, m.logMonoTime)
      t.append(m.logMonoTime / 1e9)
      requested.append(float(m.carControl.actuators.accel))
      wire.append(float(actuators.accel))
      active.append(bool(m.carControl.longActive))
      sendcans.append((m.logMonoTime, can_sends))

  t = np.array(t)
  requested = np.array(requested, dtype=float)
  wire = np.array(wire, dtype=float)
  act = np.array(active, dtype=bool)
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

  # true domain handoff, decoded from the CAN this controller would actually have sent
  flips = forceful = coast_entries = 0
  brake_domain_frames = gas_domain_frames = coast_domain_frames = 0
  total_edges = []
  try:
    from opendbc.can.parser import CANParser
    cp = CANParser(ODYSSEY_PT_DBC, [("ACC_CONTROL", 0)], 1)
    prev = prev_domain = None
    for i, (mono, sends) in enumerate(sendcans):
      cp.update([(mono, [(addr, dat, src) for addr, dat, src in sends])])
      if cp.can_valid:
        br = int(cp.vl["ACC_CONTROL"]["BRAKE_REQUEST"])
        ac = float(cp.vl["ACC_CONTROL"]["ACCEL_COMMAND"])
        gas = float(cp.vl["ACC_CONTROL"]["GAS_COMMAND"])
        if act[i]:
          domain = "brake" if br else ("gas" if gas > GAS_INACTIVE else "coast")
          brake_domain_frames += domain == "brake"
          gas_domain_frames += domain == "gas"
          coast_domain_frames += domain == "coast"
          if domain == "coast" and prev_domain != "coast":
            coast_entries += 1
          prev_domain = domain
        else:
          prev_domain = None
        if prev is not None and br != prev:
          flips += 1
          total_edges.append(mono)
          if abs(ac) > 0.3:
            forceful += 1
        prev = br
  except Exception as e:
    print(f"  (sendcan decode failed: {e})")

  res = {
    "seg_range": seg_range,
    "frames": int(len(t)), "engaged_frames": int(act.sum()),
    "replayed": {**stats(wire, act), "domain_flips_open_loop_only": flips,
                 "domain_forceful_open_loop_only": forceful,
                 "brake_domain_frames_open_loop_only": brake_domain_frames,
                 "gas_domain_frames_open_loop_only": gas_domain_frames,
                 "coast_domain_frames_open_loop_only": coast_domain_frames,
                 "coast_entries_open_loop_only": coast_entries},
    "recorded": stats(rec, act),
    # fidelity: on the SAME branch that produced the log this must be ~0. If it is not, the
    # replay is not reproducing the drive and no A/B conclusion drawn from it is trustworthy.
    "replay_vs_recorded_rms": float(np.sqrt(np.nanmean((wire[act] - rec[act]) ** 2))) if act.sum() else None,
  }
  with open(out_path, "w") as f:
    json.dump(res, f, indent=2)
  print(json.dumps(res, indent=2))


if __name__ == "__main__":
  main()
