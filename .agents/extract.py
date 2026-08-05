#!/usr/bin/env python3
"""Decode a route's control signals once and cache them, so repeat analysis is instant.

    from extract import load
    d = load("00000003--f670928197")     # first call decodes; later calls hit the cache
    mph = d["vego"] * 2.23694

Why this exists: a single analysis session on 2026-08-05 re-decoded the same 32-39 segment route
about ten times - once per ad-hoc question plus once per validate_log run - at 1-3 minutes each.
The bytes never changed; only the question did. Everything here is a pure function of the rlog, so
it is cached on disk keyed by route and SCHEMA, and answering a follow-up question costs a few
milliseconds instead of minutes.

This is deliberately NOT part of validate_log.py. That tool is the deterministic gate and must read
the log itself so a cache bug can never silently change a ledger row. This is for exploration: the
ad-hoc "what happened at t=1936?" work that precedes a finding.

Everything is resampled onto the 100 Hz carControl grid, because that is the control timebase and
the one every downstream metric already assumes:
  * continuous signals (speed, accel, pitch) are linearly interpolated
  * discrete CAN commands are ZERO-ORDER HELD, never interpolated - interpolating GAS_COMMAND
    invents values that were never on the wire, and half-on BRAKE_REQUEST bits
TODO: delete excessive comments before trying to submit a PR.
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tuning_metrics import hold_last

from openpilot.common.hardware.hw import Paths
from openpilot.tools.lib.logreader import LogReader

# BUMP THIS whenever the extracted signal set changes, or a stale cache will silently answer a
# question with the wrong columns. It is part of the cache key, so old caches are simply ignored.
SCHEMA = 1
CACHE = os.environ.get("EXTRACT_CACHE", "/tmp/comma_extract_cache")
ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"   # MUST track validate_log.py


def _segments(route):
  segs = sorted((s for s in os.listdir(Paths.log_root()) if route in s),
                key=lambda s: int(s.rsplit("--", 1)[-1]))
  if not segs:
    raise SystemExit(f"no local segments matching '{route}' under {Paths.log_root()}\n"
                     f"pull it first: uv run python .agents/pull_logs.py --route {route}")
  full = {s.rsplit("--", 1)[0] for s in segs}
  if len(full) != 1:
    raise SystemExit(f"'{route}' matches {len(full)} routes: {sorted(full)}")
  return full.pop(), [os.path.join(Paths.log_root(), s, "rlog.zst") for s in segs]


def _decode(paths):
  from opendbc.can.parser import CANParser
  sent = CANParser(ODYSSEY_PT_DBC, [("ACC_CONTROL", 0)], 1)
  recv = CANParser(ODYSSEY_PT_DBC, [("VSA_STATUS", 0), ("GAS_PEDAL_2", 0),
                                    ("POWERTRAIN_DATA", 0), ("GEARBOX_AUTO", 0)], 1)
  cc = {k: [] for k in ("t", "accel", "active", "pitch", "pid")}
  cs = {k: [] for k in ("t", "vego", "aego", "gas_pressed", "brake_pressed", "vcruise")}
  co = {k: [] for k in ("t", "accel", "gasfactor", "windfactor")}
  lp = {k: [] for k in ("t", "atarget")}
  sc = {k: [] for k in ("t", "gas", "accel", "brake_request")}
  rx = {k: [] for k in ("t", "computer_braking", "user_brake", "engine_torque", "rpm", "gear")}

  for m in LogReader(paths):
    w = m.which()
    t = m.logMonoTime / 1e9
    if w == "carControl":
      a = m.carControl.actuators
      o = m.carControl.orientationNED
      cc["t"].append(t)
      cc["accel"].append(a.accel)
      cc["active"].append(float(m.carControl.longActive))
      cc["pitch"].append(o[1] if len(o) == 3 else 0.0)
      cc["pid"].append(float(str(a.longControlState) == "pid"))
    elif w == "carState":
      s = m.carState
      cs["t"].append(t)
      cs["vego"].append(s.vEgo)
      cs["aego"].append(s.aEgo)
      cs["gas_pressed"].append(float(s.gasPressed))
      cs["brake_pressed"].append(float(s.brakePressed))
      cs["vcruise"].append(s.vCruise)          # km/h, and 0 on cruiseState for Bosch+OP long
    elif w == "carOutput":
      a = m.carOutput.actuatorsOutput
      # gas/brake on carOutput are REPURPOSED to the learned factors by the Odyssey carcontroller.
      co["t"].append(t)
      co["accel"].append(a.accel)
      co["gasfactor"].append(a.gas)
      co["windfactor"].append(a.brake)
    elif w == "longitudinalPlan":
      lp["t"].append(t)
      lp["atarget"].append(m.longitudinalPlan.aTarget)
    elif w == "sendcan":
      sent.update([(m.logMonoTime, [(c.address, c.dat, c.src) for c in m.sendcan])])
      if sent.can_valid:
        v = sent.vl["ACC_CONTROL"]
        sc["t"].append(t)
        sc["gas"].append(float(v["GAS_COMMAND"]))
        sc["accel"].append(float(v["ACCEL_COMMAND"]))
        sc["brake_request"].append(float(v["BRAKE_REQUEST"]))
    elif w == "can":
      recv.update([(m.logMonoTime, [(c.address, c.dat, c.src) for c in m.can])])
      if recv.can_valid:
        rx["t"].append(t)
        rx["computer_braking"].append(float(recv.vl["VSA_STATUS"]["COMPUTER_BRAKING"]))
        rx["user_brake"].append(float(recv.vl["VSA_STATUS"]["USER_BRAKE"]))
        rx["engine_torque"].append(float(recv.vl["GAS_PEDAL_2"]["ENGINE_TORQUE_ESTIMATE"]))
        rx["rpm"].append(float(recv.vl["POWERTRAIN_DATA"]["ENGINE_RPM"]))
        rx["gear"].append(float(recv.vl["GEARBOX_AUTO"]["TRANS_TARGET_GEAR"]))
  return cc, cs, co, lp, sc, rx


def _build(route):
  full, paths = _segments(route)
  cc, cs, co, lp, sc, rx = _decode(paths)
  if len(cc["t"]) < 100:
    raise SystemExit(f"{full}: only {len(cc['t'])} carControl frames - not a usable route")

  t0 = cc["t"][0]
  grid = np.asarray(cc["t"]) - t0
  out = {"route": full, "t0": t0, "t": grid}

  def lin(src, key):
    if not len(src["t"]):
      return np.full(len(grid), np.nan)
    return np.interp(grid, np.asarray(src["t"]) - t0, np.asarray(src[key], dtype=float))

  def zoh(src, key):
    if not len(src["t"]):
      return np.full(len(grid), np.nan)
    return hold_last(grid, np.asarray(src["t"]) - t0, np.asarray(src[key], dtype=float))

  # CarController input - the car-port boundary. See AGENTS.md.
  out["request"] = np.asarray(cc["accel"], dtype=float)
  out["active"] = np.asarray(cc["active"], dtype=float) > 0.5
  out["pid"] = (np.asarray(cc["pid"], dtype=float) > 0.5) & out["active"]
  out["pitch"] = np.asarray(cc["pitch"], dtype=float)
  for k in ("vego", "aego", "vcruise"):
    out[k] = lin(cs, k)
  for k in ("gas_pressed", "brake_pressed"):
    out[k] = lin(cs, k) > 0.5
  out["wire"] = lin(co, "accel")
  out["gasfactor"] = lin(co, "gasfactor")
  out["windfactor"] = lin(co, "windfactor")
  out["atarget"] = lin(lp, "atarget") if len(lp["t"]) else out["request"].copy()
  # Discrete CAN: zero-order hold only.
  out["gas_command"] = zoh(sc, "gas")
  out["accel_command"] = zoh(sc, "accel")
  out["brake_request"] = zoh(sc, "brake_request") > 0.5
  for k in ("computer_braking", "user_brake", "gear"):
    out[k] = zoh(rx, k)
  for k in ("engine_torque", "rpm"):
    out[k] = lin(rx, k)
  return out


def load(route, refresh=False):
  """Decoded, grid-aligned signals for a route. Cached on disk after the first call."""
  full, _ = _segments(route)
  os.makedirs(CACHE, exist_ok=True)
  path = os.path.join(CACHE, f"{full}.v{SCHEMA}.npz")
  if os.path.exists(path) and not refresh:
    with np.load(path, allow_pickle=False) as z:
      d = {k: z[k] for k in z.files}
    d["route"] = full
    d["t0"] = float(d["t0"])
    return d
  d = _build(full)
  np.savez_compressed(path, **{k: v for k, v in d.items() if k != "route"})
  return d


def main():
  if len(sys.argv) < 2:
    raise SystemExit(__doc__)
  refresh = "--refresh" in sys.argv
  for route in [a for a in sys.argv[1:] if not a.startswith("--")]:
    d = load(route, refresh=refresh)
    eng = d["active"].sum() * 0.01
    print(f"{d['route']}: {len(d['t'])} frames, {d['t'][-1] / 60:.1f} min logged, "
          f"{eng / 60:.1f} min engaged, {len(d) - 2} signals cached")


if __name__ == "__main__":
  main()
