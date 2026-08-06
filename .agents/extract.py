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

UPSTREAM signals (radarState / longitudinalPlan / modelV2 / selfdriveState) are cached too, even
though nothing upstream of carControl.actuators.accel is the car port's to fix. The reason is
triage, not tuning: when the driver reports a symptom, the FIRST question is whether the planner
even asked for it, and answering that used to cost a raw LogReader pass per question. The
2026-08-05 investigation of the 20:09 slowdown on 00000004 needed five such passes before it could
say "openpilot's allow_throttle coast clamp, not us". Those signals are exactly the ones that
settle attribution, so they belong in the cache with everything else.
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
SCHEMA = 2
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
  cc = {k: [] for k in ("t", "accel", "active", "pitch", "pid")}
  cs = {k: [] for k in ("t", "vego", "aego", "gas_pressed", "brake_pressed", "vcruise", "steer_angle")}
  co = {k: [] for k in ("t", "accel", "gasfactor", "windfactor")}
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
    elif w == "carState":
      s = m.carState
      cs["t"].append(t)
      cs["vego"].append(s.vEgo)
      cs["aego"].append(s.aEgo)
      cs["gas_pressed"].append(float(s.gasPressed))
      cs["brake_pressed"].append(float(s.brakePressed))
      cs["vcruise"].append(s.vCruise)          # km/h, and 0 on cruiseState for Bosch+OP long
      cs["steer_angle"].append(s.steeringAngleDeg)   # NOT a lateral metric - reads curve entry
    elif w == "carOutput":
      a = m.carOutput.actuatorsOutput
      # gas/brake on carOutput are REPURPOSED to the learned factors by the Odyssey carcontroller.
      co["t"].append(t)
      co["accel"].append(a.accel)
      co["gasfactor"].append(a.gas)
      co["windfactor"].append(a.brake)
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
  return cc, cs, co, lp, sc, rx, rs, md, ss


def _build(route):
  full, paths = _segments(route)
  cc, cs, co, lp, sc, rx, rs, md, ss = _decode(paths)
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
  for k in ("vego", "aego", "vcruise", "steer_angle"):
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
