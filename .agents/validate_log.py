#!/usr/bin/env python3
"""
validate_log.py - deterministic per-log validation for the ody-op-long tune.

Runs every uploaded route through the SAME set of checks so tune convergence
and the cross-brand watchlist (see .agents/agents.md "Cross-Brand Longitudinal
Patterns") are evaluated identically each time, and appends the result to an
evidence ledger so status transitions (watch -> candidate, parked -> revisit)
become evidence-driven instead of re-derived by hand.

Usage:
    uv run python .agents/validate_log.py <route> ['description']
    # route form matches generate_report.py, e.g. 805f87f5e96d128c/0000000d
    # append /a to force the qlog fallback when full rlogs aren't uploaded.

It PRINTS a verdict, APPENDS a row to the ledger (.jsonl authoritative +
.md human view), and SUGGESTS status changes from accumulated evidence. It
never edits agents.md itself - a human curates that prose from the suggestions.

The watchlist checks only carry their full meaning on HONDA_ODYSSEY_5G_MMR,
because the tune repurposes carOutput.actuatorsOutput.gas -> effective gasfactor
and .brake -> windfactor there (see honda/carcontroller.py L417-425). On other
platforms only the convergence + crash checks are meaningful.

TODO: delete excessive comments before trying to submit a PR.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from openpilot.tools.lib.logreader import LogReader
from openpilot.common.hardware.hw import Paths

LEDGER_DIR = Path(__file__).resolve().parent
LEDGER_JSONL = LEDGER_DIR / "log-validation-ledger.jsonl"
LEDGER_MD = LEDGER_DIR / "log-validation-ledger.md"
ODYSSEY = "HONDA_ODYSSEY_5G_MMR"

# ---- thresholds (grounded in the converged baselines recorded in agents.md) ----
# Convergence regression guards. Baselines: track RMS ~0.22, passthrough RMS ~0.11
# on route 00000013 (agents.md "Tune status" / ody-op-long2 notes).
TRACK_RMS_LIMIT = 0.35        # RMS(aEgo - aTarget) over active pid frames
PASSTHROUGH_RMS_LIMIT = 0.25  # RMS(wire accel - planner accel) over gas-domain frames
GASF_EFF_LO, GASF_EFF_HI = 0.05, 1.5   # effective gasfactor sane band (base 0.35-0.9 * trim)
GASF_DRIFT_LIMIT = 0.30       # within-drive drift (last10% mean - first10% mean); instability
WINDF_CLIP = 3.0              # windfactor upper clip rail (pinned = learner starved)

# Watchlist symptom thresholds. Each maps to a candidate tweak in agents.md.
OVERSHOOT_MARGIN = 0.30       # m/s^2: aEgo below command during brake recovery = overshoot
OVERSHOOT_FRAC_FLAG = 0.02    # >2% of braking frames overshooting -> Toyota future-error
PITCH_RATE_THRESH = 0.02      # rad/s: "grade transition" window
PITCH_LAG_RATIO = 2.0         # window track-error / overall > this -> Toyota high-pass pitch
CREEP_VEGO = 2.0              # m/s: below this is the hold-at-stop window
CREEP_AEGO = 0.15             # m/s^2 forward while planner asks <=0 -> creep
CREEP_MIN_FRAMES = 50         # ~0.5s at 100Hz sustained
BRAKE_ONSET_JERK = 2.0        # m/s^3: the parked ody-op-long2 cap; count would-be binds
JERK_SMOOTH_TAU = 0.20        # s: causal LPF before differentiating. Heavy on purpose - the
                              # command updates at 50Hz (carcontroller frame%2) but carControl
                              # logs at 100Hz, so frame-to-frame diff aliases (the artifact
                              # agents.md flagged that faked earlier "clipped live" claims).
JERK_WIN_S = 0.10             # s: differentiate over this window (central slope), not 1 frame
JERK_BIND_MIN_RUN = 5         # consecutive frames (~50ms) sustained over cap = a real bind


def _series(msgs, which, extract):
  out_t, out_v = [], []
  for m in msgs:
    if m.which() == which:
      out_t.append(m.logMonoTime / 1e9)
      out_v.append(extract(m))
  return np.array(out_t), np.array(out_v, dtype=float)


def _causal_lpf(x, dt, tau):
  if len(x) == 0:
    return x
  alpha = dt / (tau + dt)
  y = np.empty_like(x)
  y[0] = x[0]
  for i in range(1, len(x)):
    y[i] = y[i - 1] + alpha * (x[i] - y[i - 1])
  return y


def analyze(msgs, platform):
  r = {"platform": platform, "notes": []}

  # --- gather series on their native timebases ---
  t_cc, cc_accel = _series(msgs, "carControl", lambda m: m.carControl.actuators.accel)
  _, cc_pitch = _series(msgs, "carControl", lambda m: m.carControl.orientationNED[1]
                        if len(m.carControl.orientationNED) == 3 else 0.0)
  _, cc_active = _series(msgs, "carControl", lambda m: 1.0 if m.carControl.longActive else 0.0)
  _, cc_pid = _series(msgs, "carControl",
                      lambda m: 1.0 if str(m.carControl.actuators.longControlState) == "pid" else 0.0)
  t_co, co_accel = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.accel)
  _, co_gasf = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.gas)
  _, co_windf = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.brake)
  t_cs, cs_aego = _series(msgs, "carState", lambda m: m.carState.aEgo)
  _, cs_vego = _series(msgs, "carState", lambda m: m.carState.vEgo)
  t_lp, lp_atarget = _series(msgs, "longitudinalPlan", lambda m: m.longitudinalPlan.aTarget)

  if len(t_cc) < 100 or len(t_co) < 50 or len(t_cs) < 50:
    r["notes"].append("SPARSE LOG: too few carControl/carOutput/carState frames "
                      "(qlog fallback decimates carOutput - the repurposed factor fields "
                      "may be unreliable). Convergence numbers are indicative only.")

  # everything onto the carControl timebase (the 100Hz control grid)
  grid = t_cc
  def onto(t, v):
    return np.interp(grid, t, v) if len(t) else np.full_like(grid, np.nan)
  aego = onto(t_cs, cs_aego)
  vego = onto(t_cs, cs_vego)
  wire = onto(t_co, co_accel)
  gasf = onto(t_co, co_gasf)
  windf = onto(t_co, co_windf)
  atarget = onto(t_lp, lp_atarget) if len(t_lp) else cc_accel.copy()
  dt = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.01

  active = cc_active > 0.5
  pid = (cc_pid > 0.5) & active

  # === convergence ===
  if pid.sum() > 10:
    r["track_rms"] = float(np.sqrt(np.nanmean((aego[pid] - atarget[pid]) ** 2)))
  else:
    r["track_rms"] = None

  # passthrough: wire should equal planner command in the GAS domain (brake_pid
  # intentionally diverges the wire in the brake domain, so exclude those frames)
  brake_added = wire < (cc_accel - 0.02)   # empirical brake-domain (brake_pid acted)
  gas_dom = active & ~brake_added
  if gas_dom.sum() > 10:
    r["passthrough_rms"] = float(np.sqrt(np.nanmean((wire[gas_dom] - cc_accel[gas_dom]) ** 2)))
  else:
    r["passthrough_rms"] = None

  is_ody = platform == ODYSSEY
  if is_ody and active.sum() > 10:
    g = gasf[active]
    r["gasf_eff_mean"] = float(np.nanmean(g))
    r["gasf_eff_min"] = float(np.nanmin(g))
    r["gasf_eff_max"] = float(np.nanmax(g))
    n = max(1, len(g) // 10)
    r["gasf_drift"] = float(np.nanmean(g[-n:]) - np.nanmean(g[:n]))
    w = windf[active]
    r["windf_mean"] = float(np.nanmean(w))
    r["windf_max"] = float(np.nanmax(w))
  else:
    for k in ("gasf_eff_mean", "gasf_eff_min", "gasf_eff_max", "gasf_drift", "windf_mean", "windf_max"):
      r[k] = None

  # crashes (agents.md: read errorLogMessage; controlsd death -> relayMalfunction three layers down)
  crashes = 0
  for m in msgs:
    if m.which() == "errorLogMessage":
      txt = m.errorLogMessage or ""
      if "crash" in txt.lower() or "exc_info" in txt.lower():
        crashes += 1
  r["crashes"] = crashes

  # === watchlist symptoms (Odyssey telemetry semantics) ===
  # 1. brake_pid overshoot -> Toyota future-error winddown. Overshoot = the car
  #    decelerating HARDER than commanded (aEgo more negative than cc_accel by a
  #    margin well beyond tracking lag) during a braking event - exactly what
  #    Toyota's error_future winddown suppresses.
  cmd_smooth = _causal_lpf(cc_accel, dt, JERK_SMOOTH_TAU)
  braking = pid & (cc_accel < -0.3)
  overshoot = braking & (aego < cc_accel - OVERSHOOT_MARGIN)
  r["overshoot_frac"] = float(overshoot.sum() / braking.sum()) if braking.sum() > 20 else 0.0

  # 2. pitch-transition lag -> Toyota high-pass pitch (brake side only)
  pitch_smooth = _causal_lpf(cc_pitch, dt, 0.3)
  pitch_rate = np.gradient(pitch_smooth) / dt
  hi = active & (np.abs(pitch_rate) > PITCH_RATE_THRESH)
  err = np.abs(aego - atarget)
  if hi.sum() > 20 and active.sum() > 100:
    r["pitch_lag_ratio"] = float(np.nanmean(err[hi]) / max(1e-3, np.nanmean(err[active])))
  else:
    r["pitch_lag_ratio"] = 0.0

  # 3. creep at stop -> creep comp (but NOT Ford-style subtraction on Bosch; see agents.md)
  creep = active & (vego < CREEP_VEGO) & (cc_accel <= 0.0) & (aego > CREEP_AEGO)
  # longest sustained run
  run, best = 0, 0
  for c in creep:
    run = run + 1 if c else 0
    best = max(best, run)
  r["creep_frames"] = int(best)

  # 4. brake-onset jerk -> revisit parked ody-op-long2 if the 2.0 cap would actually bind.
  #    Differentiate over a ~0.1s window (central slope) rather than adjacent frames, so a
  #    50Hz command sampled at 100Hz doesn't manufacture jerk (the aliasing agents.md warned
  #    about). A bind must be sustained JERK_BIND_MIN_RUN frames to count.
  win = max(1, int(round(JERK_WIN_S / dt)))
  jerk = np.zeros_like(cmd_smooth)
  jerk[win:-win] = (cmd_smooth[2 * win:] - cmd_smooth[:-2 * win]) / (2 * win * dt)
  over_cap = jerk < -BRAKE_ONSET_JERK
  binds, run = 0, 0
  for o in over_cap:
    run = run + 1 if o else 0
    if run == JERK_BIND_MIN_RUN:
      binds += 1
  onset = jerk < -0.5
  onsets = int(np.sum(np.diff(onset.astype(int)) == 1))
  r["jerk_binds"] = int(binds)
  r["jerk_onsets"] = onsets
  r["jerk_max"] = float(-np.min(jerk)) if len(jerk) else 0.0   # peak sustained -jerk, for context

  return r


def verdicts(r):
  """Map metrics -> per-check PASS/FLAG and the watchlist status each implies."""
  v = []
  def add(name, ok, detail, status=None):
    v.append({"check": name, "ok": bool(ok), "detail": detail, "status": status})

  add("controlsd crashes", r["crashes"] == 0, f"{r['crashes']}")
  if r["track_rms"] is not None:
    add("track RMS |aEgo-aTarget|", r["track_rms"] <= TRACK_RMS_LIMIT, f"{r['track_rms']:.3f} (<= {TRACK_RMS_LIMIT})")
  if r["passthrough_rms"] is not None:
    add("passthrough RMS", r["passthrough_rms"] <= PASSTHROUGH_RMS_LIMIT, f"{r['passthrough_rms']:.3f} (<= {PASSTHROUGH_RMS_LIMIT})")
  if r["gasf_eff_mean"] is not None:
    ok = GASF_EFF_LO <= r["gasf_eff_min"] and r["gasf_eff_max"] <= GASF_EFF_HI and abs(r["gasf_drift"]) <= GASF_DRIFT_LIMIT
    add("gasfactor stability", ok, f"mean {r['gasf_eff_mean']:.2f} [{r['gasf_eff_min']:.2f},{r['gasf_eff_max']:.2f}] drift {r['gasf_drift']:+.2f}")
  if r["windf_mean"] is not None:
    add("windfactor not pinned", r["windf_max"] < WINDF_CLIP, f"mean {r['windf_mean']:.2f} max {r['windf_max']:.2f}")

  # watchlist -> each FLAG names its candidate tweak + status implication
  add("brake_pid overshoot", r["overshoot_frac"] <= OVERSHOOT_FRAC_FLAG,
      f"{r['overshoot_frac']*100:.1f}% of braking frames",
      status="Toyota future-error winddown" if r["overshoot_frac"] > OVERSHOOT_FRAC_FLAG else None)
  add("pitch-transition lag", r["pitch_lag_ratio"] <= PITCH_LAG_RATIO,
      f"{r['pitch_lag_ratio']:.2f}x overall error in grade windows",
      status="Toyota high-pass pitch (brake side)" if r["pitch_lag_ratio"] > PITCH_LAG_RATIO else None)
  add("creep at stop", r["creep_frames"] < CREEP_MIN_FRAMES,
      f"{r['creep_frames']} frames sustained",
      status="creep comp (NOT Ford subtraction - see agents.md)" if r["creep_frames"] >= CREEP_MIN_FRAMES else None)
  # Only a SUBSTANTIAL bind justifies un-parking: the planner's onset jerk normally sits
  # right at the 2.0 cap (holdback negligible - agents.md), so a lone marginal peak ~2.1
  # is noise. Flag on >=3 sustained binds or a peak well over the cap.
  jerk_bad = r["jerk_binds"] >= 3 or r.get("jerk_max", 0) > 2.5
  add("brake-onset jerk bind", not jerk_bad,
      f"{r['jerk_binds']} binds / {r['jerk_onsets']} onsets, peak {r.get('jerk_max', 0):.1f} m/s^3 (cap 2.0)",
      status="revisit PARKED ody-op-long2" if jerk_bad else None)
  return v


def suggest_status(route):
  """Read accumulated ledger and suggest watch->candidate / parked->revisit transitions."""
  if not LEDGER_JSONL.exists():
    return []
  rows = [json.loads(l) for l in LEDGER_JSONL.read_text().splitlines() if l.strip()]
  ody = [r for r in rows if r.get("platform") == ODYSSEY]
  recent = ody[-5:]
  out = []
  # a symptom flagged in >=2 of the last 5 Odyssey logs -> promote from watch to candidate
  from collections import Counter
  flagged = Counter()
  for r in recent:
    for c in r.get("verdicts", []):
      if not c["ok"] and c.get("status"):
        flagged[(c["check"], c["status"])] += 1
  for (check, status), n in flagged.items():
    if "PARKED" in status and n >= 1:
      out.append(f"{check}: seen {n}x recently -> {status} (any real bind justifies un-parking)")
    elif n >= 2:
      out.append(f"{check}: flagged in {n}/{len(recent)} recent logs -> promote watch->CANDIDATE ({status})")
  if not out and len(ody) >= 5:
    out.append(f"No watchlist symptom flagged across last {len(recent)} Odyssey logs - "
               "statuses stay 'watch only' with growing confidence.")
  return out


def append_ledger(route, description, r, v):
  ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
  row = {"date": ts, "route": route, "description": description or "",
         "platform": r["platform"], **{k: r[k] for k in r if k != "notes"},
         "verdicts": v}
  with LEDGER_JSONL.open("a") as f:
    f.write(json.dumps(row) + "\n")

  if not LEDGER_MD.exists():
    LEDGER_MD.write_text(
      "# Log Validation Ledger\n\n"
      "Auto-appended by `.agents/validate_log.py`. One row per validated route. "
      "FLAGged watchlist symptoms name the candidate tweak; see `.agents/agents.md` "
      "\"Cross-Brand Longitudinal Patterns\" for status. Authoritative data is the "
      "sibling `.jsonl`; this table is the human view.\n\n"
      "| date | route | platform | crashes | track RMS | passthru RMS | gasf mean | windf mean | FLAGS |\n"
      "|---|---|---|---|---|---|---|---|---|\n")
  flags = [c["check"] for c in v if not c["ok"]]
  def fmt(x):
    return f"{x:.3f}" if isinstance(x, float) else ("-" if x is None else str(x))
  line = (f"| {ts} | {route} | {r['platform']} | {r['crashes']} | {fmt(r['track_rms'])} | "
          f"{fmt(r['passthrough_rms'])} | {fmt(r['gasf_eff_mean'])} | {fmt(r['windf_mean'])} | "
          f"{', '.join(flags) if flags else 'none'} |\n")
  with LEDGER_MD.open("a") as f:
    f.write(line)


def main():
  ap = argparse.ArgumentParser(description="Validate a route against the ody-op-long tune watchlist")
  ap.add_argument("route")
  ap.add_argument("description", nargs="?")
  ap.add_argument("--no-ledger", action="store_true", help="print only, don't append to the ledger")
  args = ap.parse_args()

  if "/" in args.route or "|" in args.route:
    lr = LogReader(args.route)
  else:
    segs = [s for s in os.listdir(Paths.log_root()) if args.route in s]
    lr = LogReader([os.path.join(Paths.log_root(), s, "rlog.zst") for s in segs])

  msgs = list(lr)
  cp = None
  for m in msgs:
    if m.which() == "carParams":
      cp = m.carParams
      break
  platform = cp.carFingerprint if cp else "UNKNOWN"

  r = analyze(msgs, platform)
  v = verdicts(r)

  print(f"\n=== validate_log: {args.route}  [{platform}] ===")
  if platform != ODYSSEY:
    print("  (not the Odyssey - watchlist telemetry semantics N/A; convergence + crashes only)")
  for note in r["notes"]:
    print(f"  ! {note}")
  print("\n  CONVERGENCE / SAFETY")
  for c in v[:5]:
    print(f"    [{'OK  ' if c['ok'] else 'FLAG'}] {c['check']:<26} {c['detail']}")
  print("\n  WATCHLIST")
  for c in v[5:]:
    tag = f"  -> {c['status']}" if (not c["ok"] and c.get("status")) else ""
    print(f"    [{'OK  ' if c['ok'] else 'FLAG'}] {c['check']:<26} {c['detail']}{tag}")

  if not args.no_ledger:
    append_ledger(args.route, args.description, r, v)
    print(f"\n  ledger: appended to {LEDGER_MD.name} / {LEDGER_JSONL.name}")
    sugg = suggest_status(args.route)
    if sugg:
      print("\n  STATUS SUGGESTIONS (human applies to agents.md):")
      for s in sugg:
        print(f"    * {s}")


if __name__ == "__main__":
  main()
