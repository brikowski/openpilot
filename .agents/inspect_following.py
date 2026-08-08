#!/usr/bin/env python3
"""Inspect command-fidelity failures in locally cached full-rate Odyssey rlogs.

Unlike the aggregate ledger check, this prints the individual intervals and compares both possible
"requested acceleration" signals:

* ``carControl.actuators.accel`` is the command actually passed into ``CarController.update``.
* ``longitudinalPlan.aTarget`` is an upstream planner output that still passes through longcontrol.

That distinction matters when deciding whether a deviation belongs to the car port.
"""
import argparse
import os

import numpy as np

from openpilot.common.hardware.hw import Paths
from openpilot.tools.lib.logreader import LogReader
from opendbc.can.parser import CANParser

from validate_log import FOLLOW_MIN_VEGO, ODYSSEY_PT_DBC, SIGN_DISAGREE_REQUEST, _rate, _series


def _local_reader(route):
  def segment_index(name):
    try:
      return int(name.rsplit("--", 1)[-1])
    except ValueError:
      return -1

  segments = sorted((name for name in os.listdir(Paths.log_root()) if route in name), key=segment_index)
  if not segments:
    raise SystemExit(f"no local segments matching {route!r} under {Paths.log_root()}")
  return LogReader([os.path.join(Paths.log_root(), name, "rlog.zst") for name in segments])


def _runs(mask):
  padded = np.pad(mask.astype(np.int8), (1, 1))
  edges = np.diff(padded)
  return zip(np.where(edges == 1)[0], np.where(edges == -1)[0], strict=True)


def inspect(route):
  msgs = list(_local_reader(route))
  t_cc, cc_accel = _series(msgs, "carControl", lambda m: m.carControl.actuators.accel)
  _, active_raw = _series(msgs, "carControl", lambda m: float(m.carControl.longActive))
  _, pitch = _series(msgs, "carControl",
                     lambda m: m.carControl.orientationNED[1] if len(m.carControl.orientationNED) == 3 else 0.0)
  t_lp, plan_accel = _series(msgs, "longitudinalPlan", lambda m: m.longitudinalPlan.aTarget)
  t_cs, vego_raw = _series(msgs, "carState", lambda m: m.carState.vEgo)
  _, aego_raw = _series(msgs, "carState", lambda m: m.carState.aEgo)
  _, brake_raw = _series(msgs, "carState", lambda m: float(m.carState.brakePressed))

  cp = CANParser(ODYSSEY_PT_DBC, [("ACC_CONTROL", 0)], 1)
  t_can, brake_request, wire_accel = [], [], []
  for msg in msgs:
    if msg.which() != "sendcan":
      continue
    cp.update([(msg.logMonoTime, [(can.address, can.dat, can.src) for can in msg.sendcan])])
    if cp.can_valid:
      t_can.append(msg.logMonoTime / 1e9)
      brake_request.append(float(cp.vl["ACC_CONTROL"]["BRAKE_REQUEST"]))
      wire_accel.append(float(cp.vl["ACC_CONTROL"]["ACCEL_COMMAND"]))

  t_can = np.asarray(t_can)
  if _rate(t_can) < 20.0:
    raise SystemExit("sendcan is not full-rate; event inspection would be misleading")

  def onto(t, values):
    return np.interp(t_cc, t, np.asarray(values, dtype=float))

  plan = onto(t_lp, plan_accel)
  vego = onto(t_cs, vego_raw)
  aego = onto(t_cs, aego_raw)
  brake_pressed = onto(t_cs, brake_raw) > 0.5
  br = onto(t_can, brake_request) > 0.5
  wire = onto(t_can, wire_accel)
  active = (active_raw > 0.5) & (vego > FOLLOW_MIN_VEGO) & ~brake_pressed
  brake_domain = active & br

  print(f"\n=== {route} ===")
  print(f"carControl { _rate(t_cc):.1f} Hz, longitudinalPlan {_rate(t_lp):.1f} Hz, sendcan {_rate(t_can):.1f} Hz")
  print(f"RMS carControl - plan: {np.sqrt(np.mean((cc_accel[active] - plan[active]) ** 2)):.4f} m/s^2")
  for label, requested in (("carControl", cc_accel), ("plan", plan)):
    err = wire - requested
    disagree = brake_domain & (requested > SIGN_DISAGREE_REQUEST)
    print(f"{label:>10}: brake RMS {np.sqrt(np.mean(err[brake_domain] ** 2)):.4f}, "
          f"mean {np.mean(err[brake_domain]):+.4f}, sign-disagree {np.mean(disagree[active])*100:.2f}%, "
          f"worst {np.min(err[disagree]) if disagree.any() else 0.0:+.3f}")

  # Rank contiguous intervals by their most-negative deviation from the actual CarController input.
  # This shows whether a headline aggregate comes from sustained behavior or one transition.
  disagreement = brake_domain & (cc_accel > SIGN_DISAGREE_REQUEST)
  active_edges = np.where(np.diff(active.astype(np.int8), prepend=0) == 1)[0]
  intervals = []
  for start, end in _runs(disagreement):
    err = wire[start:end] - cc_accel[start:end]
    intervals.append((float(np.min(err)), start, end))

  print("\nWorst BRAKE_REQUEST intervals while CarController input asks acceleration:")
  for worst, start, end in sorted(intervals)[:12]:
    sl = slice(start, end)
    recent_engages = active_edges[active_edges <= start]
    engaged_for = t_cc[start] - t_cc[recent_engages[-1]] if len(recent_engages) else float("nan")
    pre = slice(max(0, start - int(round(2.0 * _rate(t_cc)))), start)
    print(f"  t={t_cc[start]-t_cc[0]:8.2f}s  duration={t_cc[end-1]-t_cc[start]:5.2f}s  "
          f"engaged_for={engaged_for:6.1f}s  v={np.mean(vego[sl])*2.237:5.1f} mph  "
          f"pitch={np.mean(pitch[sl]):+.4f} rad  "
          f"CC={np.min(cc_accel[sl]):+.2f}..{np.max(cc_accel[sl]):+.2f}  "
          f"plan={np.min(plan[sl]):+.2f}..{np.max(plan[sl]):+.2f}  "
          f"wire={np.min(wire[sl]):+.2f}..{np.max(wire[sl]):+.2f}  "
          f"aEgo={np.min(aego[sl]):+.2f}..{np.max(aego[sl]):+.2f}  worst={worst:+.2f}  "
          f"prior2s(CC/wire/aEgo)={np.min(cc_accel[pre]):+.2f}/"
          f"{np.min(wire[pre]):+.2f}/{np.min(aego[pre]):+.2f}")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("routes", nargs="+")
  args = parser.parse_args()
  for route in args.routes:
    inspect(route)


if __name__ == "__main__":
  main()
