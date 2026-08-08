#!/usr/bin/env python3
"""
validate_log.py - deterministic per-log validation for the ody-op-long tune.

Runs every uploaded route through the SAME set of checks so tune convergence
and the cross-brand watchlist (see .agents/tune-evidence.md "Cross-Brand Longitudinal
Patterns") are evaluated identically each time, and appends the result to an
evidence ledger so status transitions (watch -> candidate, parked -> revisit)
become evidence-driven instead of re-derived by hand.

Usage:
    uv run python .agents/validate_log.py <route> ['description']
    # route form matches generate_report.py, e.g. 805f87f5e96d128c/0000000d
    # Default read mode is RLOG (rlogs only, error if absent). Append /a for ReadMode.AUTO, which
    # PREFERS rlogs and only falls back to qlogs if none are uploaded - it does NOT force qlog.
    # (An earlier version of this docstring said /a "forces the qlog fallback", which is wrong and
    # led to three ledger rows being wrongly suspected of holding decimated data. If a route does
    # come back decimated, qlog_fallback below detects it by rate and suppresses what it invalidates.)

It PRINTS a verdict, APPENDS a row to the ledger (.jsonl authoritative +
.md human view), and SUGGESTS status changes from accumulated evidence. It
never edits tune-evidence.md itself - a human curates that prose from the suggestions.

The watchlist checks only carry their full meaning on HONDA_ODYSSEY_5G_MMR,
because the tune repurposes carOutput.actuatorsOutput.gas -> effective gasfactor
and .brake -> windfactor there (see honda/carcontroller.py L417-425). On other
platforms only the convergence + crash checks are meaningful.
"""
import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from opendbc.car import ACCELERATION_DUE_TO_GRAVITY
from openpilot.tools.lib.logreader import LogReader
from openpilot.common.hardware.hw import Paths
# Compare learned gas factors against the LIVE seed table, so if the seed is retuned this
# metric automatically measures against the new values instead of a stale copy.
from opendbc.car.honda.carcontroller import BRAKE_DOMAIN_ENTRY, GAS_FACTOR_SPEED_BP, GAS_FACTOR_SPEED_V
# Same reason: read the interface accel rails from the live params, not a copied number.
from opendbc.car.honda.values import CarControllerParams as HondaParams

# CUSTOM TOOLING: keep behavior-changing array math independent from route I/O and ledger policy,
# so synthetic traces can prove each metric both passes and fails before it grades a road drive.
from tuning_metrics import (
  brake_release_hold_metrics,
  causal_lpf as _causal_lpf,
  command_transition_metrics,
  descent_hold_metrics,
  hold_last as _hold_last,
  max_edges_in_window as _max_edges_in_window,
  physical_edges as _physical_edges,
  sample_rate as _rate,
  shadow_windfactor_metrics,
  sign_disagreement_metrics,
  stop_lurch_metrics,
  windowed_jerk,
)

LEDGER_DIR = Path(__file__).resolve().parent
LEDGER_JSONL = LEDGER_DIR / "log-validation-ledger.jsonl"
LEDGER_MD = LEDGER_DIR / "log-validation-ledger.md"
ODYSSEY = "HONDA_ODYSSEY_5G_MMR"
ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"   # GEARBOX_AUTO/TRANS_TARGET_GEAR on bus 1

# ---- thresholds (grounded in the converged baselines recorded in tune-evidence.md) ----
# Convergence regression guards. Baselines: track RMS ~0.22, passthrough RMS ~0.11
# on route 00000013 (tune-evidence.md "Tune status" / ody-op-long2 notes).
TRACK_RMS_LIMIT = 0.35        # RMS(aEgo - aTarget) over active pid frames
PASSTHROUGH_RMS_LIMIT = 0.25  # RMS(wire accel - CarController input) over gas-domain frames
GASF_EFF_LO, GASF_EFF_HI = 0.05, 1.5   # effective gasfactor sane band (base 0.35-0.9 * trim)
GASF_DRIFT_LIMIT = 0.30       # within-drive drift (last10% mean - first10% mean); instability
WINDF_CLIP = 3.0              # windfactor upper clip rail (pinned = learner starved)
WINDF_FLOOR = 0.1             # lower clip rail; evaluate only at highway speed where aero matters
WINDF_FLOOR_EPS = 0.005
WINDF_FLOOR_FRAC_FLAG = 0.50  # majority of highway frames on the rail = base/learner mismatch

# Watchlist symptom thresholds. Each maps to a candidate tweak in tune-evidence.md.
OVERSHOOT_MARGIN = 0.30       # m/s^2: aEgo below command during brake recovery = overshoot
OVERSHOOT_FRAC_FLAG = 0.02    # >2% of braking frames overshooting -> Toyota future-error
CREEP_VEGO = 2.0              # m/s: below this is the hold-at-stop window
CREEP_AEGO = 0.15             # m/s^2 forward while planner asks <=0 -> creep
CREEP_MIN_FRAMES = 50         # ~0.5s at 100Hz sustained
BRAKE_ONSET_JERK = 2.0        # m/s^3: the parked ody-op-long2 cap; count would-be binds
JERK_SMOOTH_TAU = 0.20        # s: causal LPF before differentiating. Heavy on purpose - the
                              # command updates at 50Hz (carcontroller frame%2) but carControl
                              # logs at 100Hz, so frame-to-frame diff aliases (the artifact
                              # tune-evidence.md flagged that faked earlier "clipped live" claims).
JERK_WIN_S = 0.10             # s: differentiate over this window (central slope), not 1 frame
JERK_BIND_MIN_RUN = 5         # consecutive frames (~50ms) sustained over cap = a real bind

# --- added tuning-quality tests (session 2026-07-24) ---
# --- model-following fidelity (2026-07-29): the car port's ONE accountability ---
# controlsd passes carControl.actuators.accel into CarController.update, and the car port puts
# ACCEL_COMMAND on the wire. Everything here measures that exact boundary and nothing else - no
# aEgo, no car response, nothing the model or Honda's ECU owns. longitudinalPlan.aTarget is one
# stage upstream and is deliberately not substituted for the CarController input.
FOLLOW_GAS_RMS_LIMIT = 0.05   # RMS(ACCEL_COMMAND - carControl accel) in gas domain (measured ~0.011)
FOLLOW_BRAKE_RMS_REGRESSION = 0.15  # brake domain diverges BY DESIGN (brake_pid supplements Honda's
                              # mushy brake), so this is a regression bound, not a target. Measured
                              # 0.041-0.109 across 12 drives; the mean is the number to watch.
SIGN_DISAGREE_REQUEST = 0.02  # m/s^2 above which the controller input genuinely asks acceleration
SIGN_DISAGREE_NON_GRADE_FLAG = 0.01  # >1% sustained away from descents = unexplained domain hold
SIGN_DISAGREE_MAG_FLAG = 0.50  # m/s^2: route 34 stale-state failure was -2.04; healthy grade holds
                              # are near -0.1 and the designed hysteresis itself is 0.50.
BRAKE_TOGGLE_BURST_WINDOW_S = 10.0  # direct symptom window: route 2f's felt tapping had 18 physical
BRAKE_TOGGLE_BURST_FLAG = 4         # edges/10s; 0.50 routes measured 2-4, failed hold measured 10
FOLLOW_MIN_VEGO = 3.0         # m/s: below this the standstill hold dominates and the
                              # question is the planner's, not ours
LOW_SPEED_CONFLICT_SEC_FLAG = 0.10  # positive request with BRAKE_REQUEST still live
CAN_COMMAND_PERIOD_S = 0.02   # ACC_CONTROL is emitted at 50 Hz while carControl logs at 100 Hz
LOW_SPEED_SKEW_S = CAN_COMMAND_PERIOD_S  # tolerate one complete command period at a request edge
GAS_INACTIVE = -30000        # MUST track honda/hondacan.py create_acc_commands.
GAS_RAMP_STEP = 60           # MUST track the Odyssey ramp in honda/carcontroller.py.
REENGAGE_WINDOW_S = 0.50      # route 34 leaked stale brake for 0.20s after longitudinal re-entry
REENGAGE_STALE_SEC_FLAG = 0.10
LOW_SPEED_DOMAIN_VEGO = 5.0   # m/s: MUST track the carcontroller's low-speed domain boundary
                              # (`switch_accel = accel if CS.out.vEgo < 5.0`, and the lower knee of
                              # both the min_gas_accel and DOMAIN_HYST_EXIT interps). Deliberately
                              # NOT FOLLOW_MIN_VEGO - that one is a "is following a meaningful
                              # question" gate at 3.0, and using it here silently blinded the check
                              # to the 3-5 m/s part of the very region the bug lived in.
STOP_LURCH_EXCESS_FLAG = 0.30  # m/s^2 achieved beyond the controller input below 2 m/s. Absolute
                               # deceleration only says the plan asked for braking; excess separates
                               # car-port contribution from Honda actuator bite. STILL REPORTED,
                               # no longer graded - see STOP_LURCH_PORT_FLAG.
STOP_LURCH_PORT_FLAG = 0.15    # m/s^2 of the stop lurch owned by the CAR PORT
                               # (`stop_lurch_wire_extra`), which is the only part we could fix.
                               # Calibrated 2026-08-05 over the 9 ledger drives that reached a
                               # stop: port contribution maxed at 0.057 (median 0.014) while the
                               # Honda actuator reached 2.744, so 0.15 is ~2.6x the observed
                               # port maximum and fires on 0 of 9. Grading the TOTAL instead fired
                               # on 17 of 24 drives for a symptom tune-evidence.md says not to tune
                               # against. Re-derive if brake_pid's authority ever changes.
STOP_LURCH_MIN_VEGO = 0.25     # m/s: below longcontrol's stopping threshold, standstill velocity/
                               # IMU noise can report a decel while the van is already stationary.
HARSH_FELT_JERK_RMS = 0.35    # m/s^3: RMS jerk of ACHIEVED accel while engaged. This is what the
                              # BODY feels, and it is NOT a following metric - it is the symptom
                              # readout. Measured 0.25-0.39 across drives while commanded jerk was
                              # only 0.12-0.24, i.e. the car amplifies our command ~2x. Reported
                              # with that ratio so harshness can be attributed rather than guessed.
DOWNHILL_PITCH = -0.012       # rad (~-0.7 deg / -1.2% grade, -0.12 m/s^2 of hill_brake): the grade
                              # breakout, where the defect concentrates (10-66 toggles/min vs 2.4 overall)
DESCENT_HOLD_MIN_S = 0.5      # gate unit (restated 2026-08-06): a hold-episode is >=0.5 s of
                              # longActive & request > 0.02 & BRAKE_REQUEST & pitch < DOWNHILL_PITCH
DOMAIN_PITCH_FILTER_TAU = 0.5  # MUST track the Odyssey FirstOrderFilter in carcontroller.py.
DOMAIN_WIND_SPEED_BP = [0.0, 13.4, 22.4, 31.3, 40.2]
DOMAIN_WIND_BRAKE_V = [0.000, 0.049, 0.136, 0.267, 0.441]

# --- gas-active-only shadow windfactor (read-only; never changes recorded commands) ---
# These mirror the inline production drag/learner constants in honda/carcontroller.py. Keeping the
# shadow here is deliberate: it must earn a stable result on frozen logs before any production gate
# is considered. The steady-state gates make wind drag identifiable instead of letting the learner
# trade against braking, pedal input, saturation, a speed transient, or a grade transition.
# First readout: four substantial current-logic routes (`3c`, `3e`, `44`, `49`) supplied 110
# eligible minutes; every shadow moved 0.50 -> 0.10-0.14 while observed mean error stayed negative
# (-0.007 to -0.033 m/s^2). The narrower gate therefore does not rescue the existing drag scale;
# this is evidence to revisit identifiability/base drag, not permission to promote the shadow.
SHADOW_WIND_SPEED_BP = [0.0, 13.4, 22.4, 31.3, 40.2]
SHADOW_WIND_DRAG_V = [0.000, 0.049, 0.136, 0.267, 0.441]
SHADOW_WIND_INITIAL = 0.5
SHADOW_WIND_LEARN_DIVISOR = 500.0
SHADOW_WIND_UPDATE_PERIOD_S = 0.02
SHADOW_WIND_MIN_VEGO = 15.0
SHADOW_WIND_STEADY_AEGO = 0.30
SHADOW_WIND_STEADY_PITCH_RATE = 0.003
SHADOW_WIND_ACCEL_RAIL_MARGIN = 0.20
SHADOW_WIND_GAS_MAX = 2000.0  # Odyssey-specific BOSCH_GAS_LOOKUP_V upper value
SHADOW_WIND_GAS_RAIL_MARGIN = 100.0

# --- coverage / driver interventions (session 2026-07-26) ---
# Coverage first: until this was recorded the ledger could not tell a clean row earned over 40
# engaged minutes from one earned over 30 seconds, so every cross-drive aggregate weighted them
# equally. It never flags - it decides how much a row is worth.
# Raised 3.0 -> 10.0 on 2026-07-27: route 0000001f had exactly 3.0 engaged minutes, so `< 3.0` was
# False and it was graded - 2 brake taps became "6.6 per 10 min" and flagged. A per-10-minute rate
# needs at least a 10 minute window to mean anything.
THIN_ENGAGED_MIN = 10.0       # min engaged: below this the drive is context, not evidence
# ...and a rate alone is still not enough: require a real count of events too, so one or two taps
# can never flag however the arithmetic is scaled.
INTERVENTION_MIN_EVENTS = 3
# Interventions are the only checks graded by what the DRIVER did rather than by telemetry we
# derive ourselves - the one signal that can't be explained away by a modeling choice. Rates are
# per 10 engaged minutes so a long drive isn't penalized for having more opportunities.
OVERRIDE_RATE_FLAG = 3.0      # gas-pedal overrides / 10 min engaged -> tune under-delivering
TAKEOVER_RATE_FLAG = 2.0      # brake-pedal takeouts / 10 min engaged -> braking late or too weak
TAKEOVER_LOOKBACK_S = 0.5     # s: Honda drops longActive the same frame the brake switch closes,
                              # so attribute a brake press to OP if OP was engaged just before it.

# --- interface accel rail saturation ---
# The wire command is clipped to BOSCH_ACCEL_MIN/MAX. Sitting on the upper rail means the planner
# wants more than the interface can deliver (reads as sluggish, and the carcontroller's own
# saturation guard freezes the learner - carcontroller.py "at accel max the signal is saturated"),
# which no other check here would surface.
RAIL_EPS = 0.02               # m/s^2 within the rail counts as pinned
RAIL_FRAC_FLAG = 0.02         # >2% of engaged frames pinned = we're asking past the interface

# --- device thermal (2026-07-26) ---
# Mirrors hardwared.py for deviceType "tizi" (comma 3X - confirmed from initData on this car).
# NOT imported from hardwared: that module calls HARDWARE.get_device_type() at import time and
# pulls in the alert stack, so it is not safe to import off-device. If you change device type,
# re-check hardwared.THERMAL_BANDS - the mici branch uses different numbers (96/100 and 85).
TEMP_CRITICAL = 94.0          # C: hardwared ThermalStatus.critical for tizi -> refuses to go onroad
TEMP_OVERHEATED = 88.0        # C: lower edge of the overheated band; real headroom is gone here
TEMP_OFFROAD_DANGER = 75.0    # C: OFFROAD_DANGER_TEMP (tizi). Above this while parked, openpilot
                              # calls the device too hot to take on any additional load.
# The SOAK check is the actionable one for "should I pull the device out of the car". loggerd is
# onroad-only (process_config `logging` = started and run), so a parked device logs NOTHING and the
# soak itself is invisible. The first deviceState sample of a drive is the closest available proxy:
# it is the temperature the device came up at, before load and fan have done anything, i.e. how hot
# the car left it. Above the offroad-danger line means it started with no thermal headroom.
TEMP_SOAK_FLAG = TEMP_OFFROAD_DANGER
# A hot start only means SOLAR SOAK if the device had time to cool first. Routes 00000015/00000016
# are back-to-back (15 ran ~08:44-09:43, 16 started ~09:45) and 16 came up at 73C purely as
# residual heat from the previous drive - reading that as "the car baked it" would be wrong. Only
# drives that started after a real park count toward the advisory.
COLD_START_GAP_H = 2.0        # h parked before temp_start reflects soak rather than leftover heat
SOAK_ADVISORY_C = 70.0        # C: cold-start silicon at/above this = the parked car is cooking it

# --- qlog-fallback detection (2026-07-26) ---
# carControl/carOutput/carState are 100Hz native; qlog keeps 1 in 10 (cereal/services.py), so 50Hz
# separates a real rlog from a decimated one with a wide margin either side.
NATIVE_RATE_MIN = 50.0        # Hz: below this on the control services, treat the route as qlog
SENDCAN_RATE_MIN = 20.0       # Hz: sendcan is 100Hz native, 1-in-139 on qlog (~0.7Hz)
CAN_RATE_MIN = 20.0           # Hz: can is 100Hz native, 1-in-2053 on qlog (~3 msgs/segment)

def _series(msgs, which, extract):
  out_t, out_v = [], []
  for m in msgs:
    if m.which() == which:
      out_t.append(m.logMonoTime / 1e9)
      out_v.append(extract(m))
  return np.array(out_t), np.array(out_v, dtype=float)


def _jerk(smoothed, dt, active):
  """Windowed central-slope derivative of an already-smoothed accel signal, gated to engaged
  frames. Differentiate over ~JERK_WIN_S rather than adjacent frames: the command updates at 50Hz
  (carcontroller frame%2) but logs at 100Hz, and a naive np.gradient aliases that into phantom jerk
  (the artifact that faked the earlier "clipped live" claims - see tune-evidence.md). Also drops a window
  either side of every engage/disengage edge, where the signal steps for reasons no jerk limiter
  would ever see."""
  return windowed_jerk(smoothed, dt, active, JERK_WIN_S)


def _opendbc_pointer(parent_commit, dirty):
  """The opendbc commit that parent_commit pins - i.e. the code that actually contains the tune.

  initData only carries the PARENT commit, but every tuned constant lives in the submodule, so
  grouping ledger rows by `git_commit` alone does not tell you what was on the wire. That is not
  hypothetical: the 2026-07-30 DOMAIN_HYST_EXIT=0.50 analysis pooled routes 32/33 as "baseline"
  when their pointers were BRAKE_RELEASE_HOLD and 0.20 - both already known worse than no
  hysteresis - and reached the wrong conclusion. Resolve it once here instead of by hand per row.

  Returns None when the parent commit is not in the local object store (never fetched, or the
  branch was rewritten). A dirty parent means the pointer is what was COMMITTED, not necessarily
  what was flashed, so it is not recorded - the deploy task in tasks.json refuses dirty trees for
  this reason, but old rows predate that guard.
  """
  if not parent_commit or dirty:
    return None
  repo = Path(__file__).resolve().parents[1]
  try:
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", parent_commit, "opendbc_repo"],
                         capture_output=True, text=True, timeout=10)
  except (OSError, subprocess.SubprocessError):
    return None
  if out.returncode != 0:
    return None
  parts = out.stdout.split()
  return parts[2][:12] if len(parts) >= 3 and parts[0] == "160000" else None


def _provenance(msgs):
  """Which code actually drove the car, read from the log's own initData - NOT from the local
  checkout, which says nothing about what the device was running. Without this an A/B between
  branches produces ledger rows that are indistinguishable after the fact."""
  for m in msgs:
    if m.which() == "initData":
      d = m.initData
      commit, dirty = str(d.gitCommit)[:12], bool(d.dirty)
      return {"git_branch": str(d.gitBranch), "git_commit": commit,
              "opendbc_commit": _opendbc_pointer(commit, dirty),
              "git_dirty": dirty, "op_version": str(d.version)}
  return {"git_branch": None, "git_commit": None, "opendbc_commit": None,
          "git_dirty": None, "op_version": None}


def analyze(msgs, platform):
  r = {"platform": platform, "notes": []}

  # --- gather series on their native timebases ---
  t_cc, cc_accel = _series(msgs, "carControl", lambda m: m.carControl.actuators.accel)
  _, cc_pitch = _series(msgs, "carControl", lambda m: m.carControl.orientationNED[1]
                        if len(m.carControl.orientationNED) == 3 else 0.0)
  _, cc_active = _series(msgs, "carControl", lambda m: 1.0 if m.carControl.longActive else 0.0)
  _, cc_pid = _series(msgs, "carControl",
                      lambda m: 1.0 if str(m.carControl.actuators.longControlState) == "pid" else 0.0)
  _, cc_stopping = _series(msgs, "carControl",
                           lambda m: 1.0 if str(m.carControl.actuators.longControlState) == "stopping" else 0.0)
  t_co, co_accel = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.accel)
  _, co_gasf = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.gas)
  _, co_windf = _series(msgs, "carOutput", lambda m: m.carOutput.actuatorsOutput.brake)
  t_cs, cs_aego = _series(msgs, "carState", lambda m: m.carState.aEgo)
  _, cs_vego = _series(msgs, "carState", lambda m: m.carState.vEgo)
  _, cs_gaspressed = _series(msgs, "carState", lambda m: 1.0 if m.carState.gasPressed else 0.0)
  _, cs_brakepressed = _series(msgs, "carState", lambda m: 1.0 if m.carState.brakePressed else 0.0)
  t_lp, lp_atarget = _series(msgs, "longitudinalPlan", lambda m: m.longitudinalPlan.aTarget)

  # Detect a qlog-decimated route by SAMPLE RATE, not frame count. The old count-based check
  # (len(t_cc) < 100) never fired on a real qlog route: qlog keeps 1 carControl in 10, so an hour
  # of driving still has ~36000 frames and sailed past the threshold. Routes 00000005/06/0b were
  # validated through the /a fallback and silently recorded jerk, domain-chatter and kickdown
  # numbers computed from 10Hz/0.7Hz data, with no warning at all. Rate cleanly separates them:
  # native is 100Hz, qlog is 10Hz.
  r["cc_rate_hz"] = _rate(t_cc)
  r["co_rate_hz"] = _rate(t_co)
  r["qlog_fallback"] = bool(min(r["cc_rate_hz"], r["co_rate_hz"]) < NATIVE_RATE_MIN)
  if len(t_cc) < 100 or len(t_co) < 50 or len(t_cs) < 50:
    r["notes"].append("SPARSE LOG: too few carControl/carOutput/carState frames. "
                      "Convergence numbers are indicative only.")
  if r["qlog_fallback"]:
    r["notes"].append(
      f"QLOG FALLBACK ({r['cc_rate_hz']:.0f}Hz carControl, {r['co_rate_hz']:.0f}Hz carOutput vs "
      f"100Hz native). Rate-dependent checks are SUPPRESSED, not merely flagged: jerk needs a "
      f"{JERK_WIN_S}s window (one sample at 10Hz), domain chatter needs 100Hz sendcan (qlog keeps "
      f"1 in 139) and kickdown needs raw can (~3 msgs/segment). Convergence, coverage and "
      f"intervention numbers remain valid.")

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
  gaspressed = onto(t_cs, cs_gaspressed) > 0.5
  brakepressed = onto(t_cs, cs_brakepressed) > 0.5
  dt = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.01

  active = cc_active > 0.5
  pid = (cc_pid > 0.5) & active

  # === coverage ===
  # How much drive is behind every number below. Never flags - it sets how much this row is worth.
  r["log_min"] = float((grid[-1] - grid[0]) / 60.0) if len(grid) > 1 else 0.0
  r["engaged_min"] = float(active.sum() * dt / 60.0)
  r["engaged_frac"] = float(active.mean()) if len(active) else 0.0
  r["engaged_mi"] = float(np.nansum(vego[active]) * dt / 1609.34) if active.sum() else 0.0
  r["vego_max"] = float(np.nanmax(vego)) if len(vego) else 0.0
  thin = r["engaged_min"] < THIN_ENGAGED_MIN
  if thin:
    r["notes"].append(f"THIN SAMPLE: only {r['engaged_min']:.1f} min engaged - treat this row as "
                      f"context, not evidence (rate-based checks are reported but not graded).")

  # === convergence ===
  # ANCHOR THIS TO THE CAR-PORT INPUT, not to longitudinalPlan.aTarget. Per the model-following
  # rule, `carControl.actuators.accel` is what CarController was actually asked for; `aTarget` is
  # one stage upstream and `longcontrol` legitimately overrides it (accel limits, the
  # stopping/starting state machine). Referencing aTarget silently credits or blames us for
  # longcontrol's work. `passthrough_rms` and the following checks were corrected on 2026-07-29;
  # this one was missed and still read aTarget until 2026-08-05.
  #
  # Both are recorded because they answer different questions and the ledger has 51 rows of the
  # old one: `track_rms` is achieved-vs-commanded (car port + Honda ECU + vehicle) and is the
  # attributable number; `track_rms_plan` keeps the old planner-referenced value so historical
  # rows stay comparable. `plan_override_rms` is the gap between them - if it is large, longcontrol
  # is doing something aTarget does not show and neither number should be read as the car's.
  if pid.sum() > 10:
    r["track_rms"] = float(np.sqrt(np.nanmean((aego[pid] - cc_accel[pid]) ** 2)))
    r["track_rms_plan"] = float(np.sqrt(np.nanmean((aego[pid] - atarget[pid]) ** 2)))
    r["plan_override_rms"] = float(np.sqrt(np.nanmean((atarget[pid] - cc_accel[pid]) ** 2)))
  else:
    r["track_rms"] = None
    r["track_rms_plan"] = None
    r["plan_override_rms"] = None

  # passthrough: wire should equal the CarController input in the GAS domain (brake_pid
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
    highway = active & (vego > 20.0)
    r["windf_floor_frac_highway"] = (float(np.nanmean(windf[highway] <= WINDF_FLOOR + WINDF_FLOOR_EPS))
                                     if highway.sum() > 50 else None)
  else:
    for k in ("gasf_eff_mean", "gasf_eff_min", "gasf_eff_max", "gasf_drift", "windf_mean", "windf_max",
              "windf_floor_frac_highway"):
      r[k] = None

  # crashes: a managed DRIVING process dying (tune-evidence.md: controlsd death -> relayMalfunction,
  # three layers down). The specific signal is an errorLogMessage whose JSON `msg == "crash"`
  # (the manager's crash report). Do NOT substring-match "crash"/"exc_info": that false-flags
  # any caught exception a background daemon logs - e.g. route 00000005 logged
  # athenad.ws_recv.exception (WebSocketConnectionClosedException, the LTE flapping in the
  # ody-modem-not-ours memory note), a networking event with zero bearing on driving. Verified
  # msg=='crash' count on that route was 0. We also record WHICH process, so a real hit says
  # what died rather than just a count.
  crashes = 0
  crashed_procs = []
  for m in msgs:
    if m.which() == "errorLogMessage":
      txt = m.errorLogMessage or ""
      try:
        d = json.loads(txt)
      except Exception:
        continue
      if d.get("msg") == "crash":
        crashes += 1
        proc = d.get("ctx", {}).get("daemon") or d.get("name") or d.get("filename") or "?"
        crashed_procs.append(str(proc))
  r["crashes"] = crashes
  r["crashed_procs"] = crashed_procs

  # === driver interventions ===
  # Every other check grades the tune with telemetry we chose how to interpret; these count the
  # times the driver overruled it. Gas override: on Bosch, gasPressed does NOT drop ACC, so
  # engaged-and-gas-pressed is directly "OP wasn't giving me enough". Brake takeover: the brake
  # switch DOES drop longActive on the same frame, so counting `active & brakePressed` would
  # read ~0 on every drive - attribute a brake press to OP if OP was engaged in the preceding
  # TAKEOVER_LOOKBACK_S instead.
  ovr = active & gaspressed
  r["override_events"] = int(np.sum(np.diff(ovr.astype(int)) == 1))
  r["override_frac"] = float(ovr.sum() / active.sum()) if active.sum() else 0.0
  look = max(1, int(round(TAKEOVER_LOOKBACK_S / dt)))
  bp_edges = np.where(np.diff(brakepressed.astype(int)) == 1)[0]
  r["takeover_events"] = int(sum(1 for i in bp_edges if active[max(0, i - look):i + 1].any()))
  # Total brake presses (engaged or not) makes the takeover count self-validating: 0 takeovers out
  # of 80 presses means the driver never braked out of OP, while 0 out of 0 means brakePressed
  # never arrived and the metric proved nothing.
  r["brake_presses"] = int(len(bp_edges))
  per10 = r["engaged_min"] / 10.0
  r["override_rate"] = float(r["override_events"] / per10) if per10 > 0 else 0.0
  r["takeover_rate"] = float(r["takeover_events"] / per10) if per10 > 0 else 0.0
  r["thin_sample"] = bool(thin)

  # === interface accel rail saturation ===
  # wire is already clipped to the Bosch rails, so equality with a rail means the planner asked
  # for more authority than the interface has. Distinct from every convergence metric: tracking
  # error can look fine while we sit pinned, because aTarget itself was never deliverable.
  # The rails are Honda Bosch values, so this check is meaningless off-platform.
  if is_ody and active.sum() > 10:
    r["rail_hi_frac"] = float((active & (wire >= HondaParams.BOSCH_ACCEL_MAX - RAIL_EPS)).sum() / active.sum())
    r["rail_lo_frac"] = float((active & (wire <= HondaParams.BOSCH_ACCEL_MIN + RAIL_EPS)).sum() / active.sum())

  # === watchlist symptoms (Odyssey telemetry semantics) ===
  # 1. brake_pid overshoot -> Toyota future-error winddown.
  #    CAREFUL - this must measure OUR controller, not the car's actuator. Naively comparing
  #    aEgo to the planner command flags "Honda's friction-brake actuator biting past our
  #    ACCEL_COMMAND setpoint", which is documented as NOT ours and NOT fixable (we have no
  #    brake-pressure authority; a bidirectional loop would fight Honda's own PID = opendbc
  #    #2347 oscillation). Measured on route 00000001: that naive form flagged 7.1% of braking
  #    frames, but 4.6% were aEgo below the *wire* (pure actuator bite) and the mean
  #    (aEgo - planner) was +0.003, i.e. no systematic overshoot at all.
  #    The actionable symptom is our integral-only brake_pid STILL ADDING brake while the car
  #    is already decelerating past target - integral lag, exactly what Toyota's error_future
  #    projection winds down sooner.
  cmd_smooth = _causal_lpf(cc_accel, dt, JERK_SMOOTH_TAU)
  braking = pid & (cc_accel < -0.3)
  brake_addon = wire - cc_accel                       # <0 = our brake_pid is adding brake
  adding = brake_addon < -0.05
  already_past = aego < cc_accel - OVERSHOOT_MARGIN    # car already beyond commanded decel
  overshoot = braking & adding & already_past
  r["overshoot_frac"] = float(overshoot.sum() / braking.sum()) if braking.sum() > 20 else 0.0
  r["addon_mean"] = float(brake_addon[braking].mean()) if braking.sum() > 20 else 0.0
  # Informational only, never flags: how hard Honda's actuator bites past OUR wire command.
  # Kept separate so a future session cannot re-conflate it with the controller symptom.
  r["honda_bite_frac"] = float(((aego - wire) < -0.3)[braking].mean()) if braking.sum() > 20 else 0.0

  # (2. pitch-transition lag REMOVED 2026-07-29. It measured aEgo vs aTarget through grade
  #  changes - a closed-loop outcome with Honda's ECU inside it, not our command fidelity. It
  #  flagged 0 of 5 substantial drives and could not have caught the real grade defect, which is
  #  on the command side and now lives in _following's downhill breakout.)

  # 3. creep at stop -> creep comp (but NOT Ford-style subtraction on Bosch; see tune-evidence.md)
  creep = active & (vego < CREEP_VEGO) & (cc_accel <= 0.0) & (aego > CREEP_AEGO)
  # longest sustained run
  run, best = 0, 0
  for c in creep:
    run = run + 1 if c else 0
    best = max(best, run)
  r["creep_frames"] = int(best)

  # 4. brake-onset jerk -> revisit parked ody-op-long2 if the 2.0 cap would actually bind.
  #    Differentiate over a ~0.1s window (central slope) rather than adjacent frames, so a
  #    50Hz command sampled at 100Hz doesn't manufacture jerk (the aliasing tune-evidence.md warned
  #    about). A bind must be sustained JERK_BIND_MIN_RUN frames to count.
  if r["qlog_fallback"]:
    # One sample per JERK_WIN_S at 10Hz - there is no window to differentiate over. Record None
    # rather than a number, so the ledger cannot present decimated data as a measurement.
    r["jerk_binds"] = r["jerk_onsets"] = r["jerk_max"] = None
  else:
    jerk = _jerk(cmd_smooth, dt, active)
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

  # 4b. WIRE jerk - the A/B metric for brake-onset smoothing (added 2026-07-26).
  #     The check above differentiates cc_accel, which is the CarController's input and therefore an
  #     INPUT to the car controller: it answers "would a jerk cap bind?", and it reads identically
  #     no matter what our carcontroller does. The brake-onset experiment rate-limits ACCEL_COMMAND,
  #     i.e. the WIRE - so only this metric can show whether the experiment did anything. Same
  #     smoothing/window/edge-gating so the two are directly comparable, and the difference between
  #     them is exactly the shaping our controller applied.
  if r["qlog_fallback"]:
    r["wire_jerk_max"] = r["wire_jerk_p99"] = r["wire_jerk_onset_mean"] = r["wire_jerk_onsets"] = None
  else:
    wire_smooth = _causal_lpf(wire, dt, JERK_SMOOTH_TAU)
    wjerk = _jerk(wire_smooth, dt, active)
    r["wire_jerk_max"] = float(-np.min(wjerk)) if len(wjerk) else 0.0
    r["wire_jerk_p99"] = float(-np.percentile(wjerk, 1)) if len(wjerk) else 0.0
    # Onset-only mean: average commanded jerk over frames where the wire is actually deepening
    # brake. This is the number the ody-op-long2 commit quoted (-0.78 -> -0.40 m/s^3 in replay).
    deepening = active & (wjerk < -0.5)
    r["wire_jerk_onset_mean"] = float(np.mean(wjerk[deepening])) if deepening.sum() > 10 else 0.0
    r["wire_jerk_onsets"] = int(np.sum(np.diff(deepening.astype(int)) == 1))

  # === tuning-quality tests (2026-07-24) ===
  if is_ody:
    # 5. gasfactor convergence by speed. Bin the learned effective gasfactor by the seed-table
    #    speed breakpoints and store per drive; the cross-drive aggregate (report_gasf_seed)
    #    tells us whether GAS_FACTOR_SPEED_V is right. Only frames where OP holds the gas
    #    (learner-eligible: pid, not gas-pressed) so it reflects what the learner actually saw.
    learn_frames = pid & (~gaspressed)
    gasf_bins = {}
    for i, bp in enumerate(GAS_FACTOR_SPEED_BP):
      lo = 0.0 if i == 0 else (GAS_FACTOR_SPEED_BP[i - 1] + bp) / 2
      hi_b = 1e9 if i == len(GAS_FACTOR_SPEED_BP) - 1 else (bp + GAS_FACTOR_SPEED_BP[i + 1]) / 2
      m = learn_frames & (vego >= lo) & (vego < hi_b)
      gasf_bins[str(bp)] = float(np.nanmean(gasf[m])) if m.sum() > 20 else None
    r["gasf_by_speed"] = gasf_bins

    # 6. MODEL-FOLLOWING FIDELITY. Replaced the old whole-drive `domain chatter` count
    #    2026-07-29. That metric asked "how often did the domain flip?", which conflates flips the
    #    plan asked for with flips we invented, and averaged the answer over a whole drive - so a
    #    defect concentrated on descents (10-66 toggles/min) vanished into a 2.4/min average.
    #    These ask the only question the car port is accountable for: did the wire carry what the
    #    CarController was asked? See _following.
    r.update(_following(msgs, grid, cc_accel, active, pid, cc_pitch, vego, gaspressed,
                        brakepressed, aego, windf, dt, (cc_stopping > 0.5) & active))

  # device thermal - platform-independent, and survives qlog (deviceState is undecimated)
  r.update(_thermal(msgs))
  # real wall-clock start, so the cross-drive advisory can tell a park from a pit stop
  r.update(_wall_start(msgs))
  # which code drove this row (branch/commit) - required for any A/B to be readable later
  r.update(_provenance(msgs))

  return r


def _wall_start(msgs):
  """Unix time the drive started, in seconds. Needed to tell a solar soak from leftover heat.

  Do NOT use initData.wallTimeNanos: the device boots with an unsynced RTC, so routes 00000015 and
  00000016 - which are actually an hour apart - both report 2026-06-05 10:37:02 there, 0.7s apart.
  The `clocks` stream carries the same field but keeps publishing after NTP corrects it, so anchor
  on the LAST clocks sample and back-compute the start from elapsed monotonic time."""
  first_mono = None
  last_mono = last_wall = None
  for m in msgs:
    if first_mono is None:
      first_mono = m.logMonoTime
    if m.which() == "clocks" and m.clocks.wallTimeNanos:
      last_mono, last_wall = m.logMonoTime, m.clocks.wallTimeNanos
  if last_wall is None or first_mono is None:
    return {"start_wall": None}
  return {"start_wall": float((last_wall - (last_mono - first_mono)) / 1e9)}


def _thermal(msgs):
  """Device thermal health from deviceState. Platform-independent. deviceState is 2Hz with qlog
  decimation 1, so this survives a qlog route intact - unlike the rate-dependent control metrics.
  Empty dict if no deviceState."""
  mx, offroad_equiv = [], []
  for m in msgs:
    if m.which() == "deviceState":
      d = m.deviceState
      if d.maxTempC:
        mx.append(float(d.maxTempC))
      # openpilot's own offroad gate uses max(memory, cpu, gpu) and deliberately EXCLUDES pmic,
      # so reproduce that exactly rather than reusing maxTempC (which includes pmic).
      parts = [float(d.memoryTempC or 0.0)]
      parts += [float(x) for x in (d.cpuTempC or [])]
      parts += [float(x) for x in (d.gpuTempC or [])]
      p = max(parts) if parts else 0.0
      if p > 0:
        offroad_equiv.append(p)
  if len(mx) < 10:
    return {}
  a = np.array(mx)
  r = {"temp_present": True,
       "temp_max": float(a.max()),
       "temp_median": float(np.median(a)),
       "temp_p95": float(np.percentile(a, 95)),
       # Soak proxy: the device's temperature at power-on, before load/fan have acted. A parked
       # device logs nothing (loggerd is onroad-only), so this is the only window onto how hot the
       # car left it.
       "temp_start": float(a[0]),
       "temp_frac_over_danger": float(np.mean(a > TEMP_OFFROAD_DANGER)),
       "temp_headroom": float(TEMP_CRITICAL - a.max())}
  if offroad_equiv:
    g = np.array(offroad_equiv)
    r["temp_offroad_equiv_max"] = float(g.max())    # what the 75C offroad gate would have seen
    r["temp_offroad_equiv_start"] = float(g[0])
  return r


def _following(msgs, grid, requested, active, pid, pitch, vego, gaspressed, brakepressed,
               aego, windfactor, dt, stop_state):
  """DID THE CAR PORT FOLLOW ITS INPUT? - the question it is directly accountable for.

  controlsd passes carControl.actuators.accel into CarController.update; we put ACCEL_COMMAND on
  the wire. Any gap between those exact handoff signals is ours and nothing upstream can explain
  it. The wire is decoded from sent ACC_CONTROL on bus 1, not proxied off carOutput.

  Deliberately measures the BRAKE domain, which `passthrough_rms` excludes. That exclusion was
  justified as "brake_pid intentionally diverges the wire" - but intentional divergence is still
  divergence, and it removed from measurement the only place we ever leave the model. It hid a
  real defect for weeks: on descents the wire toggles BRAKE_REQUEST at up to 66/min against a
  perfectly smooth request (driver-reported "tapping", routes 0000002f @ 07:50:57 and 08:18:53).

  Returns brake-domain following error, sign disagreement, lifecycle regressions, and physical
  BRAKE_REQUEST burst metrics. A raw request-sign test cannot decide whether a transition was
  "commanded": the Odyssey deliberately adds drag and grade before choosing its actuator domain.
  """
  out = {"follow_brake_rms": None, "follow_brake_mean": None, "follow_gas_rms": None,
         "brake_domain_frac": None, "sign_disagree_frac": None, "sign_disagree_worst": None,
         "sign_disagree_downhill_frac": None, "sign_disagree_non_grade_frac": None,
         "sign_disagree_non_grade_worst": None, "sign_disagree_transition_frames": None,
         "brake_release_hold_sec": None, "brake_release_hold_events": None,
         "brake_release_hold_max": None, "brake_release_hold_force_margin_mean": None,
         "brake_release_hold_request_mean": None, "brake_release_hold_tracking_mean": None,
         "sign_disagree_sec": None, "sign_disagree_events": None, "sign_disagree_longest": None,
         "sign_disagree_withheld_integral": None, "sign_disagree_withheld_worst": None,
         "low_speed_conflict_sec": None, "low_speed_conflict_events": None,
         "low_speed_conflict_worst": None,
         "reengagement_events": None, "reengagement_stale_sec": None,
         "reengagement_stale_events": None, "reengagement_stale_worst": None,
         "gas_handoff_events": None, "gas_handoff_max": None,
         "brake_toggle_edges": None, "brake_toggle_per_min": None,
         "brake_toggle_max_10s": None, "brake_toggle_min_gap": None,
         "felt_jerk_rms": None, "cmd_jerk_rms": None, "felt_jerk_p99": None,
         "harshness_ratio": None, "felt_jerk_brake": None, "felt_jerk_gas": None,
         "stop_lurch_worst": None, "stop_lurch_excess": None,
         "stop_lurch_wire_extra": None, "stop_lurch_actuator_extra": None,
         "stop_lurch_request": None, "stop_lurch_wire": None, "stop_lurch_speed": None,
         "stop_jerk_worst": None, "stop_sec": None,
         "downhill_min": None, "downhill_toggles_per_min": None,
         "descent_hold_episodes": None, "descent_hold_sec": None, "descent_hold_longest": None,
         "windf_shadow_eligible_min": None, "windf_shadow_start": None,
         "windf_shadow_end": None, "windf_shadow_min": None, "windf_shadow_max": None,
         "windf_shadow_drift": None, "windf_shadow_floor_frac": None,
         "windf_shadow_error_mean": None, "windf_shadow_error_rms": None}
  try:
    from opendbc.can.parser import CANParser
    cp = CANParser(ODYSSEY_PT_DBC, [("ACC_CONTROL", 0)], 1)
    t, br, ac, gas = [], [], [], []
    for m in msgs:
      if m.which() == "sendcan":
        cp.update([(m.logMonoTime, [(c.address, c.dat, c.src) for c in m.sendcan])])
        if cp.can_valid:
          t.append(m.logMonoTime / 1e9)
          br.append(int(cp.vl["ACC_CONTROL"]["BRAKE_REQUEST"]))
          ac.append(float(cp.vl["ACC_CONTROL"]["ACCEL_COMMAND"]))
          gas.append(float(cp.vl["ACC_CONTROL"]["GAS_COMMAND"]))
  except Exception:
    return out
  if len(t) < 50:
    return out
  t = np.array(t)
  # A long qlog route still has thousands of sendcan frames, so a count check passes while the
  # data is far too sparse to see a toggle. Gate on rate instead.
  if _rate(t) < SENDCAN_RATE_MIN:
    return out
  # ACC_CONTROL is a discrete held command, not a ramp between samples. A linear interpolation
  # created half-on brake bits and gas values that never existed on the bus.
  BR = _hold_last(grid, t, br) > 0.5
  AC = _hold_last(grid, t, ac)
  GAS = _hold_last(grid, t, gas)
  err = AC - requested
  eng_all, vego_all = active.copy(), vego     # keep un-gated masks for stop/start metrics

  # CUSTOM TOOLING: lifecycle metrics live in a pure array function so synthetic golden traces
  # can prove the one-frame transport allowance, stale re-engagement detection, and gas handoff
  # measurement independently of CAN parsing and ledger mutation.
  out.update(command_transition_metrics(
    grid, requested, eng_all, vego_all, brakepressed, BR, GAS, AC,
    low_speed_vego=LOW_SPEED_DOMAIN_VEGO,
    request_threshold=SIGN_DISAGREE_REQUEST,
    command_period_s=CAN_COMMAND_PERIOD_S,
    reengage_window_s=REENGAGE_WINDOW_S,
    gas_inactive=GAS_INACTIVE,
  ))

  # Read-only candidate learner: unlike the live learner, this advances only while a real gas
  # command is on the wire and the plant is in a steady, unsaturated identification window. It
  # replays on frozen response, so report convergence/exposure but never claim ride-quality gain.
  base_drag = np.interp(vego_all, SHADOW_WIND_SPEED_BP, SHADOW_WIND_DRAG_V)
  out.update(shadow_windfactor_metrics(
    grid, requested, aego, vego_all, pitch, pid, gaspressed, brakepressed, BR, GAS,
    gas_inactive=GAS_INACTIVE,
    gas_max=SHADOW_WIND_GAS_MAX,
    accel_min=HondaParams.BOSCH_ACCEL_MIN,
    accel_max=HondaParams.BOSCH_ACCEL_MAX,
    base_drag=base_drag,
    initial_windfactor=SHADOW_WIND_INITIAL,
    windfactor_min=WINDF_FLOOR,
    windfactor_max=WINDF_CLIP,
    learn_divisor=SHADOW_WIND_LEARN_DIVISOR,
    update_period_s=SHADOW_WIND_UPDATE_PERIOD_S,
    min_speed=SHADOW_WIND_MIN_VEGO,
    steady_accel=SHADOW_WIND_STEADY_AEGO,
    steady_pitch_rate=SHADOW_WIND_STEADY_PITCH_RATE,
    accel_rail_margin=SHADOW_WIND_ACCEL_RAIL_MARGIN,
    gas_rail_margin=SHADOW_WIND_GAS_RAIL_MARGIN,
  ))

  # Gate to frames where following is even a meaningful question: moving, and the driver's foot
  # off the brake. Without the speed gate the standstill hold dominates - at a stop the request dives
  # while ACCEL_COMMAND sits on the stopping rail, which is correct behavior but reads as a
  # ~0.9 RMS "following error" and swamps the real signal (measured: 0.93 ungated vs 0.070 gated
  # on route 0000002f). Stopping is the planner's business anyway - see tune-evidence.md.
  active = active & (vego > FOLLOW_MIN_VEGO) & ~brakepressed
  if active.sum() < 200:
    return out

  eng_min = max(1e-3, active.sum() * dt / 60.0)
  bd, gd = active & BR, active & ~BR
  out["brake_domain_frac"] = float(bd.sum() / active.sum())
  if gd.sum() > 50:
    out["follow_gas_rms"] = float(np.sqrt(np.nanmean(err[gd] ** 2)))
  if bd.sum() > 50:
    out["follow_brake_rms"] = float(np.sqrt(np.nanmean(err[bd] ** 2)))
    # One-signed by construction: target_accel = min(accel, accel + brake_addon), addon <= 0.
    # So this is a direct readout of how much brake the brake_pid adds beyond the plan.
    out["follow_brake_mean"] = float(np.nanmean(err[bd]))

  # A positive request can lead the held 50 Hz command by one period, and a descent can correctly
  # remain in the brake domain because the car-port switch includes gravity. Keep both visible,
  # but grade only disagreement that survives transport grace away from a descent (or is huge).
  out.update(sign_disagreement_metrics(
    requested, AC, BR, active, pitch,
    request_threshold=SIGN_DISAGREE_REQUEST,
    downhill_pitch=DOWNHILL_PITCH,
    dt=dt,
    transition_grace_s=CAN_COMMAND_PERIOD_S,
  ))

  # Reconstruct the controller's compensated domain input and measure the symptom independently
  # of its release threshold: BRAKE_REQUEST remains live after the base entry predicate clears.
  filtered_pitch = _causal_lpf(pitch, dt, DOMAIN_PITCH_FILTER_TAU, initial=0.0)
  base_drag = np.interp(vego_all, DOMAIN_WIND_SPEED_BP, DOMAIN_WIND_BRAKE_V)
  gas_pedal_force = requested + base_drag * windfactor + np.sin(filtered_pitch) * ACCELERATION_DUE_TO_GRAVITY
  switch_accel = np.where(vego_all < LOW_SPEED_DOMAIN_VEGO, requested, gas_pedal_force)
  entry_threshold = np.interp(vego_all, [5.0, 10.0], [0.01, BRAKE_DOMAIN_ENTRY])
  out.update(brake_release_hold_metrics(
    switch_accel, entry_threshold, requested, aego, BR, active,
    dt=dt,
  ))

  # Measure the driver-felt symptom directly: physical BRAKE_REQUEST bursts. Calling an edge
  # "uncommanded" because raw accel did not cross zero is wrong on a grade; the controller's
  # actuator decision intentionally includes pitch and drag. The known tapping route 2f produced
  # 18 real edges in 10 s, failed BRAKE_RELEASE_HOLD produced 10, while 0.50 produced 2-4.
  brake_edges = _physical_edges(BR, active)
  brake_edge_times = grid[brake_edges]
  out["brake_toggle_edges"] = int(len(brake_edges))
  out["brake_toggle_per_min"] = float(len(brake_edges) / eng_min)
  out["brake_toggle_max_10s"] = int(
      _max_edges_in_window(brake_edge_times, BRAKE_TOGGLE_BURST_WINDOW_S))
  out["brake_toggle_min_gap"] = (
      float(np.min(np.diff(brake_edge_times))) if len(brake_edge_times) > 1 else None)

  # RIDE HARSHNESS - the driver's actual experience, and the thing our fidelity checks cannot see.
  # Command fidelity can be perfect while the ride is harsh: the wire is a TARGET Honda's ECU
  # closes its own loop on, and it amplifies commanded jerk ~2x. Split gas/brake because braking
  # is consistently the harsher domain (0.27-0.92 vs 0.22-0.32 m/s^3) and that is what the driver
  # reports. The RATIO is the attribution: ~1 means the car is tracking our command's smoothness,
  # >>1 means the harshness is being added downstream of us.
  w = max(1, int(JERK_WIN_S / dt))
  aego_s = _causal_lpf(aego, dt, JERK_SMOOTH_TAU)
  fj = np.zeros_like(aego_s)
  fj[w:-w] = (aego_s[2 * w:] - aego_s[:-2 * w]) / (2 * w * dt)
  cj = np.zeros_like(aego_s)
  ac_s = _causal_lpf(AC, dt, JERK_SMOOTH_TAU)
  cj[w:-w] = (ac_s[2 * w:] - ac_s[:-2 * w]) / (2 * w * dt)
  edge = np.zeros_like(active)
  for i in np.where(np.diff(active.astype(int)) != 0)[0]:
    edge[max(0, i - 2 * w):i + 2 * w + 1] = True
  m = active & ~edge
  if m.sum() > 200:
    out["felt_jerk_rms"] = float(np.sqrt(np.nanmean(fj[m] ** 2)))
    out["cmd_jerk_rms"] = float(np.sqrt(np.nanmean(cj[m] ** 2)))
    out["felt_jerk_p99"] = float(np.nanpercentile(np.abs(fj[m]), 99))
    out["harshness_ratio"] = float(out["felt_jerk_rms"] / max(out["cmd_jerk_rms"], 1e-6))
    mb, mg = m & BR, m & ~BR
    if mb.sum() > 50:
      out["felt_jerk_brake"] = float(np.sqrt(np.nanmean(fj[mb] ** 2)))
    if mg.sum() > 50:
      out["felt_jerk_gas"] = float(np.sqrt(np.nanmean(fj[mg] ** 2)))

  # STOP LURCH. Deliberately OUTSIDE the vEgo>3 gate above: the whole point is low speed. Absolute
  # deceleration cannot attribute a lurch: it flags a perfectly followed firm request. Select the
  # event where the achieved decel exceeds the controller input most, then split that excess into
  # car-port extra brake (request -> wire) and Honda actuator bite (wire -> aEgo).
  stopping = eng_all & (vego_all > STOP_LURCH_MIN_VEGO) & (vego_all < CREEP_VEGO) & (aego < 0.0)
  if stopping.sum() > 50:
    out.update(stop_lurch_metrics(
      requested, AC, aego, vego_all, eng_all, stop_state,
      min_speed=STOP_LURCH_MIN_VEGO,
      max_speed=CREEP_VEGO,
    ))
    sj = np.zeros_like(aego)
    aes = _causal_lpf(aego, dt, JERK_SMOOTH_TAU)
    sj[w:-w] = (aes[2 * w:] - aes[:-2 * w]) / (2 * w * dt)
    out["stop_jerk_worst"] = float(np.nanmax(np.abs(sj[stopping])))
    out["stop_sec"] = float(stopping.sum() * dt)

  # Grade breakout. The defect concentrates on descents, where hill_brake = sin(pitch)*g drags
  # gas_pedal_force across min_gas_accel and every crossing also resets brake_pid.
  down = active & (pitch < DOWNHILL_PITCH)
  dn_min = down.sum() * dt / 60.0
  out["downhill_min"] = float(dn_min)
  if down.sum() > 50:
    # Count edges on the FULL timeline and mask, never `np.diff(BR[down])`. Compacting first
    # concatenates non-adjacent descents, so the BR state at the end of one window diffs against
    # the start of the next and invents a toggle that never physically happened. Measured
    # 2026-07-30: route 3b scored 12 toggles across 11 windows where only 6 were real, route 37
    # scored 7 where 3 were real - i.e. the metric that drove the entire DOMAIN_HYST_EXIT
    # investigation was inflated by roughly one toggle per extra descent window.
    downhill_edges = _physical_edges(BR, down)
    out["downhill_toggles"] = int(len(downhill_edges))
    out["downhill_windows"] = int(np.sum(np.diff(down.astype(np.int8), prepend=0) == 1))
    out["downhill_toggles_per_min"] = float(out["downhill_toggles"] / max(dn_min, 1e-3))

  # Road-gate bookkeeping: score the BRAKE_DOMAIN_ENTRY arm in its own unit so pooling never
  # falls back to hand arithmetic. Uses the UN-narrowed longActive mask (eng_all), matching the
  # gate definition rather than the vEgo/brake-pressed following gate above.
  out.update(descent_hold_metrics(
    requested, BR, eng_all, pitch,
    request_threshold=SIGN_DISAGREE_REQUEST,
    downhill_pitch=DOWNHILL_PITCH,
    min_episode_s=DESCENT_HOLD_MIN_S,
    dt=dt,
  ))
  return out


def verdicts(r):
  """Map metrics -> per-check PASS/FLAG and the watchlist status each implies."""
  v = []
  def add(name, ok, detail, status=None):
    v.append({"check": name, "ok": bool(ok), "detail": detail, "status": status})

  add("controlsd crashes", r["crashes"] == 0,
      f"{r['crashes']}" + (f" ({', '.join(r.get('crashed_procs', []))})" if r["crashes"] else ""))
  if r["track_rms"] is not None:
    add("track RMS |aEgo-carControl|", r["track_rms"] <= TRACK_RMS_LIMIT,
        f"{r['track_rms']:.3f} (<= {TRACK_RMS_LIMIT})"
        + (f"; vs planner aTarget {r['track_rms_plan']:.3f}, longcontrol override "
           f"{r['plan_override_rms']:.3f}" if r.get("plan_override_rms") is not None else ""))
  if r["passthrough_rms"] is not None:
    add("passthrough RMS", r["passthrough_rms"] <= PASSTHROUGH_RMS_LIMIT, f"{r['passthrough_rms']:.3f} (<= {PASSTHROUGH_RMS_LIMIT})")
  if r["gasf_eff_mean"] is not None:
    ok = GASF_EFF_LO <= r["gasf_eff_min"] and r["gasf_eff_max"] <= GASF_EFF_HI and abs(r["gasf_drift"]) <= GASF_DRIFT_LIMIT
    add("gasfactor stability", ok, f"mean {r['gasf_eff_mean']:.2f} [{r['gasf_eff_min']:.2f},{r['gasf_eff_max']:.2f}] drift {r['gasf_drift']:+.2f}")
  if r["windf_mean"] is not None:
    floor_frac = r.get("windf_floor_frac_highway")
    upper_bad = r["windf_max"] >= WINDF_CLIP
    lower_bad = floor_frac is not None and floor_frac > WINDF_FLOOR_FRAC_FLAG
    floor_detail = f", highway lower-rail {floor_frac*100:.0f}%" if floor_frac is not None else ", no highway sample"
    add("windfactor rail exposure", not (upper_bad or lower_bad),
        f"mean {r['windf_mean']:.2f} max {r['windf_max']:.2f}{floor_detail}",
        status="wind learner pinned - revisit base drag curve / coupled gas learner" if upper_bad or lower_bad else None)
  if r.get("windf_shadow_eligible_min") is not None:
    eligible = r["windf_shadow_eligible_min"]
    if eligible > 0.0:
      add("windfactor shadow (offline)", True,
          f"{eligible:.1f} eligible min, {r['windf_shadow_start']:.2f}->{r['windf_shadow_end']:.2f} "
          f"[{r['windf_shadow_min']:.2f},{r['windf_shadow_max']:.2f}], observed error mean "
          f"{r['windf_shadow_error_mean']:+.3f} RMS {r['windf_shadow_error_rms']:.3f} m/s^2 "
          "[frozen response - not a command A/B]")
    else:
      add("windfactor shadow (offline)", True, "0.0 eligible min - no identifiable steady gas window")
  if "rail_hi_frac" in r:
    rail_bad = max(r["rail_hi_frac"], r["rail_lo_frac"]) > RAIL_FRAC_FLAG
    add("accel rail saturation", not rail_bad,
        f"{r['rail_hi_frac']*100:.1f}% pinned at +{HondaParams.BOSCH_ACCEL_MAX:.1f}, "
        f"{r['rail_lo_frac']*100:.1f}% at {HondaParams.BOSCH_ACCEL_MIN:.1f} m/s^2",
        status="planner asking past the interface rails (learner freezes at accel max)" if rail_bad else None)

  # driver interventions - graded on what the DRIVER did, not on telemetry we interpret.
  # Suppressed (reported, forced OK) on a thin sample, where one merge inflates the rate.
  thin = r.get("thin_sample", False)
  suffix = " [thin sample - not graded]" if thin else ""
  if "override_rate" in r:
    add("gas overrides", thin or r["override_rate"] <= OVERRIDE_RATE_FLAG,
        f"{r['override_events']} events, {r['override_rate']:.1f}/10min engaged "
        f"({r['override_frac']*100:.1f}% of engaged frames){suffix}",
        status="driver adding gas repeatedly - tune under-delivering accel" if not thin and r["override_rate"] > OVERRIDE_RATE_FLAG else None)
    add("brake takeovers", thin or r["takeover_rate"] <= TAKEOVER_RATE_FLAG,
        f"{r['takeover_events']} events of {r.get('brake_presses', 0)} brake presses, "
        f"{r['takeover_rate']:.1f}/10min engaged{suffix}",
        status="driver braking out of OP repeatedly - braking late or too weak" if not thin and r["takeover_rate"] > TAKEOVER_RATE_FLAG else None)

  # watchlist -> each FLAG names its candidate tweak + status implication
  add("brake_pid overshoot", r["overshoot_frac"] <= OVERSHOOT_FRAC_FLAG,
      f"{r['overshoot_frac']*100:.1f}% braking frames still adding past target "
      f"(addon mean {r.get('addon_mean', 0):+.3f}; Honda actuator bite {r.get('honda_bite_frac', 0)*100:.1f}% - NOT ours)",
      status="Toyota future-error winddown" if r["overshoot_frac"] > OVERSHOOT_FRAC_FLAG else None)
  add("creep at stop", r["creep_frames"] < CREEP_MIN_FRAMES,
      f"{r['creep_frames']} frames sustained",
      status="creep comp (NOT Ford subtraction - see tune-evidence.md)" if r["creep_frames"] >= CREEP_MIN_FRAMES else None)
  # Only a SUBSTANTIAL bind justifies un-parking: the planner's onset jerk normally sits
  # right at the 2.0 cap (holdback negligible - tune-evidence.md), so a lone marginal peak ~2.1
  # is noise. Flag on >=3 sustained binds or a peak well over the cap.
  # NOTE: the old "brake-onset jerk bind" CHECK was removed 2026-07-27. It differentiated
  # cc_accel - the PLANNER's command, an INPUT to the car controller - so it read identically on
  # every branch and could never measure a carcontroller change. Its only consumer was the jerk
  # limiter, dropped when the brake-onset experiment closed, and it kept emitting "revisit PARKED
  # ody-op-long2" at an archived branch. The `jerk_*` fields are still COMPUTED and still land in
  # the ledger (they answer "would a cap bind?", which is a real question about the planner and
  # costs nothing), they just no longer produce a verdict. `wire_jerk_*` below measures
  # ACCEL_COMMAND and is the check that can actually see our code.
  if r.get("wire_jerk_max") is not None:
    # Never flags: this is the A/B readout for brake-onset shaping, not a symptom. The planner
    # check above measures our INPUT and is identical across branches; this measures what we
    # actually put on the wire, so it is the only number that can move when the experiment lands.
    add("wire jerk (A/B readout)", True,
        f"peak {r['wire_jerk_max']:.2f}, p99 {r['wire_jerk_p99']:.2f}, "
        f"onset mean {r['wire_jerk_onset_mean']:.2f} m/s^3 over {r['wire_jerk_onsets']} onsets")

  # --- MODEL FOLLOWING: did the wire carry what CarController was asked? ---
  # This section replaced domain chatter / stop-approach quality / post-kickdown surge on
  # 2026-07-29. Those three graded the CAR's response (aEgo jerk, aEgo over target after a
  # downshift) or averaged a defect away over a whole drive. None of them could see, and none of
  # them did see, the driver-reported downhill brake tapping - which is a pure command-side
  # defect. Every check here compares ACCEL_COMMAND to carControl.actuators.accel and nothing else.
  if r.get("follow_gas_rms") is not None:
    add("following - gas domain", r["follow_gas_rms"] <= FOLLOW_GAS_RMS_LIMIT,
        f"RMS(wire - request) {r['follow_gas_rms']:.4f} (<= {FOLLOW_GAS_RMS_LIMIT})",
        status="wire diverging from the controller input where nothing should diverge"
               if r["follow_gas_rms"] > FOLLOW_GAS_RMS_LIMIT else None)
  if r.get("follow_brake_rms") is not None:
    # Regression bound, not a target: brake_pid supplements Honda's mushy brake response BY
    # DESIGN, so this is never zero. The mean is the number that matters - it is one-signed by
    # construction (addon <= 0), so it reads out exactly how much extra brake we add.
    add("following - brake domain", r["follow_brake_rms"] <= FOLLOW_BRAKE_RMS_REGRESSION,
        f"RMS {r['follow_brake_rms']:.4f}, mean {r['follow_brake_mean']:+.4f} m/s^2 extra brake "
        f"({r['brake_domain_frac']*100:.0f}% of engaged frames in brake domain)",
        status="brake_pid diverging further than designed" if r["follow_brake_rms"] > FOLLOW_BRAKE_RMS_REGRESSION else None)
  if r.get("low_speed_conflict_sec") is not None:
    conflict_bad = r["low_speed_conflict_sec"] > LOW_SPEED_CONFLICT_SEC_FLAG
    add("low-speed brake/accel conflict", not conflict_bad,
        f"{r['low_speed_conflict_sec']:.2f}s over {r['low_speed_conflict_events']} event(s), "
        f"worst wire-request {r['low_speed_conflict_worst']:+.2f} m/s^2",
        status="BRAKE_REQUEST latched with gas inactive against a positive start request" if conflict_bad else None)
  if r.get("reengagement_stale_sec") is not None:
    stale_bad = r["reengagement_stale_sec"] > REENGAGE_STALE_SEC_FLAG
    add("re-engagement brake lifecycle", not stale_bad,
        f"{r['reengagement_events']} engagement(s), {r['reengagement_stale_sec']:.2f}s stale brake "
        f"over {r['reengagement_stale_events']} event(s), worst "
        f"{r['reengagement_stale_worst']:+.2f} m/s^2",
        status="brake-domain state leaked across inactive control" if stale_bad else None)
  if r.get("gas_handoff_events"):
    handoff_bad = r["gas_handoff_max"] > GAS_RAMP_STEP + 0.5
    add("gas handoff ramp", not handoff_bad,
        f"{r['gas_handoff_events']} inactive-to-live handoff(s), largest first command "
        f"{r['gas_handoff_max']:.0f} counts (<= {GAS_RAMP_STEP})",
        status="gas ramp state advanced while GAS_COMMAND was ineligible" if handoff_bad else None)
  if r.get("brake_release_hold_sec") is not None:
    add("brake release hold (diagnostic)", True,
        f"{r['brake_release_hold_sec']:.2f}s over {r['brake_release_hold_events']} event(s), "
        f"longest {r['brake_release_hold_max']:.2f}s; mean force margin "
        f"{r['brake_release_hold_force_margin_mean']:+.2f}, request "
        f"{r['brake_release_hold_request_mean']:+.2f}, aEgo-request "
        f"{r['brake_release_hold_tracking_mean']:+.2f} m/s^2")
  if r.get("brake_toggle_max_10s") is not None:
    burst_bad = r["brake_toggle_max_10s"] > BRAKE_TOGGLE_BURST_FLAG
    dn = (f", {r['downhill_toggles_per_min']:.0f}/min on descents over {r['downhill_min']:.1f} min"
          if r.get("downhill_toggles_per_min") is not None else "")
    gap = (f", minimum gap {r['brake_toggle_min_gap']:.2f}s"
           if r.get("brake_toggle_min_gap") is not None else "")
    add("brake-domain transition bursts", not burst_bad,
        f"{r['brake_toggle_edges']} physical edges, peak {r['brake_toggle_max_10s']}/10s"
        f"{gap}{dn}",
        status="rapid BRAKE_REQUEST cycling (downhill tapping)" if burst_bad else None)
  if r.get("felt_jerk_rms") is not None:
    # Reported, and flagged on the SYMPTOM - not on blame. The driver feels aEgo jerk; whether it
    # is ours is what the ratio and the gas/brake split are for. Naming a check after a suspected
    # cause instead of the symptom is exactly how `domain chatter` got demoted two days before the
    # driver reported the thing it was watching.
    harsh = r["felt_jerk_rms"] > HARSH_FELT_JERK_RMS
    split = ""
    if r.get("felt_jerk_brake") is not None and r.get("felt_jerk_gas") is not None:
      split = f" [brake {r['felt_jerk_brake']:.2f} vs gas {r['felt_jerk_gas']:.2f}]"
    add("ride harshness (felt)", not harsh,
        f"aEgo jerk RMS {r['felt_jerk_rms']:.3f}, p99 {r['felt_jerk_p99']:.2f} vs commanded "
        f"{r['cmd_jerk_rms']:.3f} = {r['harshness_ratio']:.1f}x amplification{split}",
        status="harsh ride - check the ratio: ~1x is our command, >>1x is added downstream" if harsh else None)
  if r.get("stop_lurch_worst") is not None:
    # FLAG ON OUR SHARE, NOT THE TOTAL. Grading `stop_lurch_excess` (everything the car achieved
    # beyond the command) fired on 17 of 24 eligible drives while tune-evidence.md's own attribution says
    # the lurch is Honda's actuator bite and "do not tune against this metric" - a 71% flag rate on
    # a symptom nobody may act on is noise that also drives suggest_status promotions. The
    # car-port's contribution is already separated out as `stop_lurch_wire_extra`, so flag that and
    # keep reporting the rest. This preserves a real regression guard: if brake_pid ever starts
    # contributing at a stop, wire_extra grows and this goes red.
    lurch_bad = r.get("stop_lurch_wire_extra", 0.0) > STOP_LURCH_PORT_FLAG
    in_stop = r.get("stop_lurch_in_stopping")
    where = "" if in_stop is None else (" in longControlState=stopping" if in_stop
                                        else " in longControlState=pid (NOT the stopping ramp)")
    port_extra = r.get("stop_lurch_wire_extra", 0.0)
    actuator_extra = r.get("stop_lurch_actuator_extra", 0.0)
    owner = ("car-port supplemental brake" if port_extra > actuator_extra
             else "Honda actuator response")
    add("stop lurch (felt)", not lurch_bad,
        f"at {r['stop_lurch_speed']:.2f} m/s: request {r['stop_lurch_request']:+.2f}, "
        f"wire {r['stop_lurch_wire']:+.2f}, aEgo {-r['stop_lurch_worst']:+.2f}; achieved extra "
        f"{r['stop_lurch_excess']:+.2f} = port {port_extra:+.2f} + actuator {actuator_extra:+.2f} "
        f"m/s^2{where}, peak jerk {r['stop_jerk_worst']:.2f} m/s^3",
        status=f"low-speed excess decel is primarily {owner}" if lurch_bad else None)
  if r.get("sign_disagree_frac") is not None:
    non_grade = r.get("sign_disagree_non_grade_frac", 0.0)
    magnitude_bad = r["sign_disagree_worst"] < -SIGN_DISAGREE_MAG_FLAG
    sd_bad = non_grade > SIGN_DISAGREE_NON_GRADE_FLAG or magnitude_bad
    add("sign disagreement", not sd_bad,
        f"{r['sign_disagree_frac']*100:.2f}% sustained: "
        f"{r.get('sign_disagree_downhill_frac', 0.0)*100:.2f}% downhill, "
        f"{non_grade*100:.2f}% non-grade; {r.get('sign_disagree_sec', 0.0):.1f}s over "
        f"{r.get('sign_disagree_events', 0)} event(s), longest "
        f"{r.get('sign_disagree_longest', 0.0):.2f}s; "
        f"{r.get('sign_disagree_withheld_integral', 0.0):.2f} m/s of requested speed withheld "
        f"(worst request {r.get('sign_disagree_withheld_worst', 0.0):+.2f}, "
        f"wire error {r['sign_disagree_worst']:+.2f} m/s^2) "
        f"({r.get('sign_disagree_transition_frames', 0)} transition frames ignored)",
        status=("large brake/accel disagreement beyond the designed hysteresis band" if magnitude_bad
                else "sustained brake/accel disagreement away from descent grade compensation")
               if sd_bad else None)

  # --- device thermal (not the tune; it's whether the hardware is being cooked) ---
  if r.get("temp_present"):
    start = r["temp_start"]
    peak = r["temp_max"]
    soaked = start > TEMP_SOAK_FLAG
    hot = peak >= TEMP_OVERHEATED
    diag = None
    if hot:
      diag = (f"RUNNING HOT: peaked {peak:.0f}C, into the overheated band ({TEMP_OVERHEATED}C) and "
              f"{r['temp_headroom']:.0f}C from critical ({TEMP_CRITICAL}C), where openpilot refuses "
              f"to go onroad. Check mount airflow and that the fan is working.")
    elif soaked:
      diag = (f"HOT SOAK: device came up at {start:.0f}C, already past the {TEMP_OFFROAD_DANGER:.0f}C "
              f"offroad-danger line before doing any work - it baked while parked. Sunshade, shade "
              f"parking, or pull the device on hot days. NOTE: with constant power the device stays "
              f"ON while parked, adds its own heat, and openpilot has NO thermal shutdown "
              f"(should_shutdown() is voltage/budget/time only) - it just runs the fan at 100%.")
    detail = (f"start {start:.0f}C, median {r['temp_median']:.0f}C, peak {peak:.0f}C "
              f"({r['temp_headroom']:.0f}C headroom to critical)")
    if r.get("temp_frac_over_danger", 0) > 0.01:
      # Not a fault onroad - the onroad limit is TEMP_CRITICAL. Tracked because it is the best
      # cross-drive indicator of how hard the device is working thermally (season, mount, fan).
      detail += (f", {r['temp_frac_over_danger']*100:.0f}% over the {TEMP_OFFROAD_DANGER:.0f}C "
                 f"offroad line (fine onroad, limit is {TEMP_CRITICAL:.0f}C)")
    add("device thermal", diag is None, detail, status=diag)
  return v


def _suggest_status_rows(rows, route):
  """Suggest status changes using only drives from the current tune configuration."""
  route_key = _base_route(route)
  current = next(
      (r for r in reversed(rows) if _base_route(r.get("route", "")) == route_key),
      None,
  )
  if current is None or current.get("platform") != ODYSSEY:
    return []

  # The tune lives in the opendbc submodule. Mixing configurations can make an old, fixed symptom
  # appear current and can promote a retired experiment. Fall back to the parent commit only for
  # legacy/dirty rows where the pinned submodule could not be resolved; if neither is known, the
  # current route is the only defensible comparison.
  opendbc_commit = current.get("opendbc_commit")
  git_commit = current.get("git_commit")
  if opendbc_commit:
    ody = [r for r in rows if r.get("platform") == ODYSSEY
           and r.get("opendbc_commit") == opendbc_commit]
  elif git_commit:
    ody = [r for r in rows if r.get("platform") == ODYSSEY
           and not r.get("opendbc_commit") and r.get("git_commit") == git_commit]
  else:
    ody = [current]

  # A thin drive shouldn't get an equal vote in a "2 of the last 5" promotion. Rows written before
  # coverage was recorded have no engaged_min and are kept (they were all substantial drives).
  ody = [r for r in ody if r.get("engaged_min", THIN_ENGAGED_MIN) >= THIN_ENGAGED_MIN]
  recent = ody[-5:]
  out = []
  # a symptom flagged in >=2 of the last 5 Odyssey logs -> promote from watch to candidate
  from collections import Counter
  flagged = Counter()
  # Only consider checks the CURRENT suite still emits. Historical rows keep the verdicts they
  # were written with, so without this filter a retired check keeps voting - and keeps naming
  # branches that have since been deleted.
  live = {c["check"] for c in (current.get("verdicts") or [])}
  for r in recent:
    for c in r.get("verdicts", []):
      if not c["ok"] and c.get("status") and c["check"] in live:
        flagged[(c["check"], c["status"])] += 1
  for (check, status), n in flagged.items():
    if "PARKED" in status and n >= 1:
      out.append(f"{check}: seen {n}x recently -> {status} (one real occurrence justifies un-parking)")
    elif n >= 2:
      out.append(f"{check}: flagged in {n}/{len(recent)} recent logs -> promote watch->CANDIDATE ({status})")
  if not out and len(ody) >= 5:
    out.append(f"No watchlist symptom flagged across last {len(recent)} Odyssey logs - "
               "statuses stay 'watch only' with growing confidence.")
  return out


def suggest_status(route):
  """Read accumulated ledger and suggest watch->candidate / parked->revisit transitions."""
  if not LEDGER_JSONL.exists():
    return []
  rows = [json.loads(l) for l in LEDGER_JSONL.read_text().splitlines() if l.strip()]
  return _suggest_status_rows(rows, route)


def _base_route(route):
  # Key on the LOG ID alone (e.g. 00000015--ab025cd335), which identifies the drive however it was
  # addressed: API form (dongle/logid), local-file form (bare logid, used when logs are pulled off
  # the device over SSH), a trailing /a|/q|/r selector, or a segment slice all reduce to one row.
  # The old dongle/logid key broke on the local form - the same drive analysed from a local pull got
  # a SECOND ledger row rather than updating the first, double-counting it in every cross-drive
  # aggregate. Assumes a single device, where the log id is unique per drive.
  m = re.search(r"[0-9a-f]{8}--[0-9a-f]+", route)
  return m.group(0) if m else route


def append_ledger(route, description, r, v):
  ts = datetime.now(UTC).strftime("%Y-%m-%d")
  row = {"date": ts, "route": route, "description": description or "",
         "platform": r["platform"], **{k: r[k] for k in r if k != "notes"},
         "verdicts": v}
  # Idempotent per route: drop any prior row for the same drive, then append this one, so
  # re-validating a route replaces its entry rather than double-counting in the cross-drive stats.
  rows = []
  if LEDGER_JSONL.exists():
    rows = [json.loads(l) for l in LEDGER_JSONL.read_text().splitlines() if l.strip()]
  # The date column is read as the drive date (rows have always been written the day of the
  # drive). A later re-validation - e.g. backfilling a new metric - must not restamp it to the
  # rerun day, and must not blank a description the original run recorded.
  prior = next((x for x in rows if _base_route(x.get("route", "")) == _base_route(route)), None)
  if prior is not None:
    row["date"] = prior.get("date", ts)
    if not description:
      row["description"] = prior.get("description", "")
  rows = [x for x in rows if _base_route(x.get("route", "")) != _base_route(route)]
  rows.append(row)
  with LEDGER_JSONL.open("w") as f:
    for x in rows:
      f.write(json.dumps(x) + "\n")
  write_ledger_md(rows)


def write_ledger_md(rows):
  """Render the human MD table from the (deduped) jsonl rows so the two always match. Separate
  from append_ledger so the table can be regenerated after an out-of-band edit to the jsonl."""
  def fmt(x):
    return f"{x:.3f}" if isinstance(x, float) else ("-" if x is None else str(x))

  def num(row, k, p=1):
    # Rows written before a metric existed simply don't have the key - render those as "-"
    # rather than backfilling a fake value.
    val = row.get(k)
    return f"{val:.{p}f}" if isinstance(val, (int, float)) else "-"
  header = (
    "# Log Validation Ledger\n\n"
    "Auto-maintained by `.agents/validate_log.py` (idempotent per route). One row per validated "
    "drive. FLAGged watchlist symptoms name the candidate tweak; see `.agents/tune-evidence.md` "
    "\"Cross-Brand Longitudinal Patterns\" for status. Authoritative data is the sibling `.jsonl`; "
    "this table is the human view. `eng min` / `eng mi` are the coverage behind the row - a clean "
    "row off a couple engaged minutes is context, not evidence. `branch` is read from the log's own "
    "`initData`, so an A/B stays readable after the fact. **`opendbc` is the submodule commit that "
    "`git_commit` pins - THAT is where the tune lives, so group by it, not by branch**, and it is "
    "blank when the parent commit is not in the local object store or the tree was dirty. "
    "`follow gas`/`follow brk` are RMS(ACCEL_COMMAND - carControl.accel) in each domain. "
    "`burst/10s` is the largest number of physical BRAKE_REQUEST edges in any 10-second window; "
    "it measures the driver-felt tapping symptom without pretending raw request sign determines "
    "the grade-compensated actuator domain.\n\n"
    "| date | route | branch | opendbc | eng min | eng mi | crashes | track RMS | passthru RMS "
    "| gasf mean | windf mean | follow gas | follow brk | burst/10s | ovr/10m | tko/10m | FLAGS |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
  lines = []
  for x in rows:
    flags = [c["check"] for c in x.get("verdicts", []) if not c["ok"]]
    # CUSTOM TOOLING: verdict names can contain `|`, which otherwise creates extra Markdown table
    # columns and shifts every field after FLAGS. Use an HTML entity so the label still renders.
    flags_text = (", ".join(flags) if flags else "none").replace("|", "&#124;")
    branch = x.get("git_branch") or "-"   # "-" = row predates provenance tracking
    odbc = x.get("opendbc_commit") or "-"
    lines.append(f"| {x['date']} | {x['route']} | {branch} | {odbc} | {num(x, 'engaged_min')} | "
                 f"{num(x, 'engaged_mi')} | {x.get('crashes', '-')} | "
                 f"{fmt(x.get('track_rms'))} | {fmt(x.get('passthrough_rms'))} | "
                 f"{fmt(x.get('gasf_eff_mean'))} | {fmt(x.get('windf_mean'))} | "
                 f"{fmt(x.get('follow_gas_rms'))} | {fmt(x.get('follow_brake_rms'))} | "
                 f"{num(x, 'brake_toggle_max_10s', 0)} | "
                 f"{num(x, 'override_rate')} | {num(x, 'takeover_rate')} | "
                 f"{flags_text} |\n")
  LEDGER_MD.write_text(header + "".join(lines))


def main():
  ap = argparse.ArgumentParser(description="Validate a route against the ody-op-long tune watchlist")
  ap.add_argument("route")
  ap.add_argument("description", nargs="?")
  ap.add_argument("--no-ledger", action="store_true", help="print only, don't append to the ledger")
  args = ap.parse_args()

  if "/" in args.route or "|" in args.route:
    lr = LogReader(args.route)
  else:
    # Sort NUMERICALLY by segment index. os.listdir returns arbitrary order, and LogReader reads a
    # path list in the order given, so the unsorted version fed segments in shuffled order and
    # scrambled the whole timebase - producing negative log durations, absurd passthrough RMS and
    # degenerate 0.00 jerk. A lexical sort is not enough either: "--10" sorts before "--2".
    def _seg_idx(name):
      try:
        return int(name.rsplit("--", 1)[-1])
      except ValueError:
        return -1
    segs = sorted((s for s in os.listdir(Paths.log_root()) if args.route in s), key=_seg_idx)
    if not segs:
      raise SystemExit(f"no local segments matching '{args.route}' under {Paths.log_root()}")
    # RESOLVE the identifier to the full log id before it is ever used as a ledger key. A bare
    # prefix ("00000017") is a perfectly good way to name a local route, but _base_route's regex
    # needs the --hash, so an unresolved prefix falls through as a literal, misses the existing
    # row, and APPENDS A DUPLICATE instead of updating it. That happened on 2026-07-30 and
    # silently double-counted 26 drives in every cross-drive aggregate.
    full = {_base_route(s) for s in segs}
    if len(full) != 1:
      raise SystemExit(f"'{args.route}' matches {len(full)} distinct routes: {sorted(full)}")
    args.route = full.pop()
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
  print(f"  coverage: {r['engaged_min']:.1f} min engaged / {r['log_min']:.1f} min logged "
        f"({r['engaged_frac']*100:.0f}%), {r['engaged_mi']:.1f} mi engaged, "
        f"max {r['vego_max']*2.237:.0f} mph")
  print(f"  code:     {r.get('git_branch') or '?'} @ {r.get('git_commit') or '?'}"
        f"{' (DIRTY)' if r.get('git_dirty') else ''}")
  for note in r["notes"]:
    print(f"  ! {note}")
  conv = {"controlsd crashes", "track RMS |aEgo-carControl|", "passthrough RMS",
          "gasfactor stability", "windfactor rail exposure", "windfactor shadow (offline)",
          "accel rail saturation"}
  driver = {"gas overrides", "brake takeovers"}
  quality = {"following - gas domain", "following - brake domain",
             "low-speed brake/accel conflict", "re-engagement brake lifecycle",
             "brake release hold (diagnostic)",
             "brake-domain transition bursts",
             "sign disagreement", "ride harshness (felt)",
             "stop lurch (felt)"}
  hardware = {"device thermal"}
  def show(group):
    for c in v:
      if c["check"] in group:
        print(f"    [{'OK  ' if c['ok'] else 'FLAG'}] {c['check']:<26} {c['detail']}")
        if not c["ok"] and c.get("status"):
          print(f"           -> {c['status']}")
  print("\n  CONVERGENCE / SAFETY")
  show(conv)
  if any(c["check"] in driver for c in v):
    print("\n  DRIVER INTERVENTIONS (ground truth - what the driver overruled)")
    show(driver)
  print("\n  WATCHLIST (cross-brand candidate tweaks)")
  show({c["check"] for c in v} - conv - driver - quality - hardware)
  print("\n  MODEL FOLLOWING (did the wire carry what CarController was asked?)")
  show(quality)
  if any(c["check"] in hardware for c in v):
    print("\n  DEVICE HARDWARE")
    show(hardware)

  if not args.no_ledger:
    append_ledger(args.route, args.description, r, v)
    print(f"\n  ledger: appended to {LEDGER_MD.name} / {LEDGER_JSONL.name}")
    sugg = suggest_status(args.route)
    if sugg:
      print("\n  STATUS SUGGESTIONS (human applies to tune-evidence.md):")
      for s in sugg:
        print(f"    * {s}")
    report_thermal_advisory()
    report_gasf_seed()


def report_thermal_advisory():
  """Cross-drive: should the device be coming out of the car while it's parked?

  A single hot start proves nothing - the device may simply not have cooled since the last drive
  (routes 00000015/00000016 are 2 minutes apart and the second came up at 73C for exactly that
  reason). So only COLD-START drives count: ones that began at least COLD_START_GAP_H after the
  previous drive ended, where temp_start really is the parked soak. Print-only; a human decides."""
  if not LEDGER_JSONL.exists():
    return
  rows = [json.loads(x) for x in LEDGER_JSONL.read_text().splitlines() if x.strip()]
  rows = [x for x in rows if x.get("start_wall") and x.get("temp_start") is not None]
  if not rows:
    return
  rows.sort(key=lambda x: x["start_wall"])

  cold = []
  for i, x in enumerate(rows):
    if i == 0:
      gap_h = None   # nothing before it; can't classify, so don't count it
    else:
      p = rows[i - 1]
      prev_end = p["start_wall"] + (p.get("log_min") or 0) * 60.0
      gap_h = (x["start_wall"] - prev_end) / 3600.0
    x["_gap_h"] = gap_h
    if gap_h is not None and gap_h >= COLD_START_GAP_H:
      cold.append(x)

  recent = cold[-5:]
  if not recent:
    print(f"\n  DEVICE THERMAL: no cold-start drive yet (need one starting >{COLD_START_GAP_H:.0f}h "
          f"after the previous drive ended). Until then a hot start can't be told from leftover "
          f"heat, so no parked-soak advice can be given.")
    return
  hot = [x for x in recent if x["temp_start"] >= SOAK_ADVISORY_C]
  worst = max(recent, key=lambda x: x["temp_start"])
  print(f"\n  DEVICE THERMAL ({len(recent)} cold-start drive(s), hottest start "
        f"{worst['temp_start']:.0f}C after {worst['_gap_h']:.1f}h parked):")
  if hot:
    print(f"    *** PULL THE DEVICE WHEN PARKED *** {len(hot)} of the last {len(recent)} cold starts "
          f"came up at/over {SOAK_ADVISORY_C:.0f}C, i.e. the parked car is soaking it to within "
          f"reach of the {TEMP_OFFROAD_DANGER:.0f}C offroad-danger line before it does any work.")
    print("    Take it out of the car when not in use (or sunshade / shade-park) until the hot "
          "weather passes. Re-check once cold starts drop back under "
          f"{SOAK_ADVISORY_C:.0f}C.")
  else:
    print(f"    OK - hottest cold start is {worst['temp_start']:.0f}C, under the "
          f"{SOAK_ADVISORY_C:.0f}C advisory line. Leaving it in the car is fine for now.")


def report_gasf_seed():
  """Cross-drive: aggregate learned gasfactor_effective by speed bin across all Odyssey rows
  and compare to the live seed table, so the seed (GAS_FACTOR_SPEED_V) can be refined from
  accumulated evidence rather than the single drive it came from. Print-only; a human edits
  the seed. Needs >=3 drives with data in a bin before suggesting a change."""
  if not LEDGER_JSONL.exists():
    return
  rows = [json.loads(l) for l in LEDGER_JSONL.read_text().splitlines() if l.strip()]
  ody = [r for r in rows if r.get("platform") == ODYSSEY and r.get("gasf_by_speed")]
  if len(ody) < 3:
    return
  print(f"\n  GASFACTOR vs SEED (learned effective, {len(ody)} Odyssey drives):")
  for bp, seed in zip(GAS_FACTOR_SPEED_BP, GAS_FACTOR_SPEED_V, strict=False):
    vals = [d["gasf_by_speed"].get(str(bp)) for d in ody]
    vals = [x for x in vals if x is not None]
    if len(vals) < 3:
      print(f"    {bp:>4.0f} m/s: seed {seed:.2f}  (only {len(vals)} drives w/ data - need 3)")
      continue
    m = float(np.mean(vals))
    delta = m - seed
    hint = f"  -> seed runs {'low' if delta > 0 else 'high'} by {abs(delta):.2f}, consider {seed + delta:.2f}" if abs(delta) > 0.08 else "  (seed good)"
    print(f"    {bp:>4.0f} m/s: seed {seed:.2f}  learned {m:.2f} (n={len(vals)}, "
          f"spread {min(vals):.2f}-{max(vals):.2f}){hint}")


if __name__ == "__main__":
  main()
