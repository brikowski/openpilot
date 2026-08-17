#!/usr/bin/env python3
"""Decode and cache grid-aligned signals for exploratory route attribution.

    from extract import load
    d = load("00000003--f670928197")     # first call decodes; later calls hit the cache
    mph = d["vego"] * 2.23694

The cache is for exploration only; validate_log reads source logs independently. Continuous
signals are interpolated onto carControl time while discrete CAN and state signals use zero-order
hold. Upstream planner/model signals are included to locate the first attribution divergence.
"""
import argparse
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tuning_metrics import hold_last

from openpilot.common.hardware.hw import Paths
from openpilot.tools.lib.logreader import LogReader

# BUMP THIS whenever the extracted signal set changes, or a stale cache will silently answer a
# question with the wrong columns. It is part of the cache key, so old caches are simply ignored.
SCHEMA = 4
CACHE = os.environ.get("EXTRACT_CACHE", "/tmp/comma_extract_cache")
ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"   # MUST track validate_log.py

# capnp enums cannot go in an allow_pickle=False npz, so they are cached as their raw ints and
# these map them back. Keep in sync with log.capnp if it ever gains a source/personality.
PLAN_SOURCE = {0: "cruise", 1: "lead0", 2: "lead1", 3: "lead2", 4: "e2e"}
PERSONALITY = {0: "aggressive", 1: "standard", 2: "relaxed"}


def _enum(held):
  """A zero-order-held enum column as ints, with absent streams as -1 rather than a NaN cast."""
  return np.where(np.isnan(held), -1, held).astype(int)


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
  cc = {k: [] for k in ("t", "accel", "active", "pitch", "pid", "lat_active", "lat_torque")}
  cs = {k: [] for k in ("t", "vego", "aego", "gas_pressed", "brake_pressed", "vcruise",
                        "steer_angle", "steer_rate", "steering_torque", "steering_pressed",
                        "steer_fault_temp", "steer_fault_perm")}
  co = {k: [] for k in ("t", "accel", "gas_output", "brake_output", "torque", "torque_output_can")}
  ctl = {k: [] for k in ("t", "lat_active", "saturated", "actual_lat_accel", "desired_lat_accel")}
  lp = {k: [] for k in ("t", "atarget", "source", "allow_throttle", "has_lead", "should_stop")}
  sc = {k: [] for k in ("t", "gas", "accel", "brake_request")}
  rx = {k: [] for k in ("t", "computer_braking", "user_brake", "engine_torque", "rpm", "gear")}
  rs = {k: [] for k in ("t", "present", "drel", "vrel", "vlead", "prob", "radar")}
  md = {k: [] for k in ("t", "e2e_accel", "e2e_should_stop", "des_curvature", "gas_press_prob")}
  ss = {k: [] for k in ("t", "experimental", "enabled", "personality")}

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
      cc["lat_active"].append(float(m.carControl.latActive))
      cc["lat_torque"].append(a.torque)
    elif w == "carState":
      s = m.carState
      cs["t"].append(t)
      cs["vego"].append(s.vEgo)
      cs["aego"].append(s.aEgo)
      cs["gas_pressed"].append(float(s.gasPressed))
      cs["brake_pressed"].append(float(s.brakePressed))
      cs["vcruise"].append(s.vCruise)          # km/h, and 0 on cruiseState for Bosch+OP long
      cs["steer_angle"].append(s.steeringAngleDeg)
      cs["steer_rate"].append(s.steeringRateDeg)
      cs["steering_torque"].append(s.steeringTorque)
      cs["steering_pressed"].append(float(s.steeringPressed))
      cs["steer_fault_temp"].append(float(s.steerFaultTemporary))
      cs["steer_fault_perm"].append(float(s.steerFaultPermanent))
    elif w == "carOutput":
      a = m.carOutput.actuatorsOutput
      # carOutput.actuatorsOutput describes the actuator output. Learner state is not part of the
      # upstream CarOutput schema and is not reconstructed here; use raw sendcan for wire commands.
      co["t"].append(t)
      co["accel"].append(a.accel)
      co["gas_output"].append(a.gas)
      co["brake_output"].append(a.brake)
      co["torque"].append(a.torque)
      co["torque_output_can"].append(a.torqueOutputCan)
    elif w == "controlsState":
      state = m.controlsState.lateralControlState
      ctl["t"].append(t)
      ctl["lat_active"].append(float(state.torqueState.active) if state.which() == "torqueState" else np.nan)
      ctl["saturated"].append(float(state.torqueState.saturated) if state.which() == "torqueState" else np.nan)
      ctl["actual_lat_accel"].append(float(state.torqueState.actualLateralAccel) if state.which() == "torqueState" else np.nan)
      ctl["desired_lat_accel"].append(float(state.torqueState.desiredLateralAccel) if state.which() == "torqueState" else np.nan)
    elif w == "longitudinalPlan":
      p = m.longitudinalPlan
      lp["t"].append(t)
      lp["atarget"].append(p.aTarget)
      # Which candidate in longitudinal_planner won this frame. `cruise` while decelerating with no
      # lead means the a_cruise branch was clamped - see allow_throttle below.
      lp["source"].append(float(p.longitudinalPlanSource.raw))
      lp["allow_throttle"].append(float(p.allowThrottle))
      lp["has_lead"].append(float(p.hasLead))
      lp["should_stop"].append(float(p.shouldStop))
    elif w == "radarState":
      r = m.radarState
      rs["t"].append(t)
      rs["present"].append(float(r.leadOne.present))
      rs["drel"].append(float(r.leadOne.dRel))
      rs["vrel"].append(float(r.leadOne.vRel))
      rs["vlead"].append(float(r.leadOne.vLead))
      rs["prob"].append(float(r.leadOne.modelProb))
      rs["radar"].append(float(r.leadOne.radar))
    elif w == "modelV2":
      a = m.modelV2.action
      md["t"].append(t)
      md["e2e_accel"].append(float(a.desiredAcceleration))
      md["e2e_should_stop"].append(float(a.shouldStop))
      md["des_curvature"].append(float(a.desiredCurvature))
      # Index 1 with a 1.0 fallback reproduces longitudinal_planner exactly; any other index is a
      # different prediction horizon and will not match the allow_throttle the planner acted on.
      g = m.modelV2.meta.disengagePredictions.gasPressProbs
      md["gas_press_prob"].append(float(g[1]) if len(g) > 1 else 1.0)
    elif w == "selfdriveState":
      s = m.selfdriveState
      ss["t"].append(t)
      ss["experimental"].append(float(s.experimentalMode))
      ss["enabled"].append(float(s.enabled))
      ss["personality"].append(float(s.personality.raw))
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
  return cc, cs, co, ctl, lp, sc, rx, rs, md, ss


def _build(route):
  full, paths = _segments(route)
  cc, cs, co, ctl, lp, sc, rx, rs, md, ss = _decode(paths)
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
  out["lat_active"] = np.asarray(cc["lat_active"], dtype=float) > 0.5
  out["lat_request_torque"] = np.asarray(cc["lat_torque"], dtype=float)
  out["pitch"] = np.asarray(cc["pitch"], dtype=float)
  for k in ("vego", "aego", "vcruise", "steer_angle", "steer_rate", "steering_torque"):
    out[k] = lin(cs, k)
  for k in ("gas_pressed", "brake_pressed", "steering_pressed", "steer_fault_temp", "steer_fault_perm"):
    out[k] = lin(cs, k) > 0.5
  out["wire"] = lin(co, "accel")
  out["gas_output"] = lin(co, "gas_output")
  out["brake_output"] = lin(co, "brake_output")
  out["lat_output_torque"] = lin(co, "torque")
  out["lat_output_torque_can"] = lin(co, "torque_output_can")
  out["lat_state_active"] = zoh(ctl, "lat_active") > 0.5
  out["lat_saturated"] = zoh(ctl, "saturated") > 0.5
  out["actual_lat_accel"] = lin(ctl, "actual_lat_accel")
  out["desired_lat_accel"] = lin(ctl, "desired_lat_accel")
  out["atarget"] = lin(lp, "atarget") if len(lp["t"]) else out["request"].copy()
  # Discrete CAN: zero-order hold only.
  out["gas_command"] = zoh(sc, "gas")
  out["accel_command"] = zoh(sc, "accel")
  out["brake_request"] = zoh(sc, "brake_request") > 0.5
  for k in ("computer_braking", "user_brake", "gear"):
    out[k] = zoh(rx, k)
  for k in ("engine_torque", "rpm"):
    out[k] = lin(rx, k)

  # UPSTREAM. Same hold-vs-interpolate rule as the CAN block, for the same reason: every one of
  # these is a DECISION a service published at its own rate, and a service downstream of it acts on
  # the last message it received, not on a blend of two. Interpolating allow_throttle would invent
  # a half-off throttle gate; interpolating a lead's dRel across an appear/disappear transition
  # would invent a car closing from 0 m. So booleans, enums and lead geometry are all held.
  # Enums come back as raw ints; decode with PLAN_SOURCE / PERSONALITY. -1 means the stream was
  # absent, which is distinguishable from cruise(0) - NaN would not survive the int cast.
  out["plan_source"] = _enum(zoh(lp, "source"))
  out["personality"] = _enum(zoh(ss, "personality"))
  for k in ("allow_throttle", "has_lead", "should_stop"):
    out[k] = zoh(lp, k) > 0.5
  out["lead_present"] = zoh(rs, "present") > 0.5
  out["lead_radar"] = zoh(rs, "radar") > 0.5
  for k in ("drel", "vrel", "vlead", "prob"):
    out["lead_" + k] = zoh(rs, k)
  out["e2e_should_stop"] = zoh(md, "e2e_should_stop") > 0.5
  for k in ("experimental", "enabled"):
    out[k] = zoh(ss, k) > 0.5
  # Continuous upstream quantities. gas_press_prob is interpolated for readability - allow_throttle
  # above is the authoritative record of what the planner actually decided from it.
  for k in ("e2e_accel", "des_curvature", "gas_press_prob"):
    out[k] = lin(md, k)
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


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("routes", nargs="+", help="local route IDs or unique prefixes")
  parser.add_argument("--refresh", action="store_true", help="ignore an existing cache entry")
  args = parser.parse_args(argv)
  for route in args.routes:
    d = load(route, refresh=args.refresh)
    eng = d["active"].sum() * 0.01
    print(f"{d['route']}: {len(d['t'])} frames, {d['t'][-1] / 60:.1f} min logged, "
          f"{eng / 60:.1f} min engaged, {len(d) - 2} signals cached")


if __name__ == "__main__":
  main()
