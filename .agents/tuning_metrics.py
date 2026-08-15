"""Pure, synthetic-testable metrics used by the Odyssey log validator.

Keep log I/O, CAN decoding, ledger mutation, and verdict policy in validate_log.py. Functions in
this module accept arrays and return arrays or metric dictionaries, so every behavior-changing
measurement can be mutation-tested without needing a route or comma device.
"""

import numpy as np


def causal_lpf(x, dt, tau, initial=None):
  if len(x) == 0:
    return x
  alpha = dt / (tau + dt)
  y = np.empty_like(x)
  y[0] = x[0] if initial is None else initial + alpha * (x[0] - initial)
  for i in range(1, len(x)):
    y[i] = y[i - 1] + alpha * (x[i] - y[i - 1])
  return y


def sample_rate(t):
  """Sample rate of a series, in Hz. 0.0 when there is not enough to tell."""
  if len(t) < 10:
    return 0.0
  d = float(np.median(np.diff(t)))
  return 1.0 / d if d > 0 else 0.0


def hold_last(grid, t, values):
  """Resample a discrete CAN command as a zero-order hold."""
  if not len(t):
    return np.full(len(grid), np.nan, dtype=float)
  idx = np.searchsorted(t, grid, side="right") - 1
  return np.asarray(values, dtype=float)[np.clip(idx, 0, len(t) - 1)]


def after_grace(mask, dt, grace_s):
  """Keep only the portion of each True run that persists beyond ``grace_s``."""
  frames = max(0, int(np.ceil(grace_s / max(dt, 1e-6))))
  sustained = mask.copy()
  for k in range(1, frames + 1):
    sustained &= np.roll(mask, k)
  sustained[:frames] = False
  return sustained


def physical_edges(signal, mask):
  """Indices of real adjacent-sample edges wholly inside a mask."""
  if len(signal) < 2:
    return np.array([], dtype=int)
  return np.flatnonzero((signal[1:] != signal[:-1]) & mask[1:] & mask[:-1]) + 1


def max_edges_in_window(times, window_s):
  """Maximum number of event timestamps in any forward-looking fixed-width window."""
  best = left = 0
  for right, timestamp in enumerate(times):
    while timestamp - times[left] >= window_s:
      left += 1
    best = max(best, right - left + 1)
  return best


def post_edge_window(edges, length, dt, start_s, end_s):
  """Mask samples in ``[start_s, end_s)`` after each edge."""
  out = np.zeros(length, dtype=bool)
  start = max(0, int(np.ceil(start_s / max(dt, 1e-6))))
  end = max(start, int(np.ceil(end_s / max(dt, 1e-6))))
  for edge in edges:
    out[min(length, edge + start):min(length, edge + end)] = True
  return out


def windowed_jerk(smoothed, dt, active, window_s):
  """Central-slope derivative with engagement-edge exclusion."""
  win = max(1, int(round(window_s / dt)))
  jerk = np.zeros_like(smoothed)
  if len(smoothed) > 2 * win:
    jerk[win:-win] = (smoothed[2 * win:] - smoothed[:-2 * win]) / (2 * win * dt)
  edge = np.zeros_like(active)
  for i in np.where(np.diff(active.astype(int)) != 0)[0]:
    edge[max(0, i - 2 * win):i + 2 * win + 1] = True
  return np.where(active & ~edge, jerk, 0.0)


def brake_episode_metrics(grid, actual_accel, brake_request, controlling, brake_pressed, speed,
                          pitch, *, min_speed, downhill_pitch, min_duration_s,
                          smooth_tau, jerk_window_s):
  """Describe complete computer-braking episodes using the achieved acceleration shape.

  The same received ``BRAKE_REQUEST`` definition works for stock radar and openpilot. The caller
  supplies the appropriate control mask, so this function does not guess who owned ACC_CONTROL.
  """
  grid = np.asarray(grid, dtype=float)
  actual_accel = np.asarray(actual_accel, dtype=float)
  brake_request = np.asarray(brake_request, dtype=bool)
  controlling = np.asarray(controlling, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  speed = np.asarray(speed, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  empty = {
    "brake_episode_count": 0,
    "brake_episode_duration_median": None,
    "brake_episode_ramp80_median": None,
    "brake_episode_onset_jerk_median": None,
    "downhill_brake_episode_count": 0,
    "downhill_brake_episode_duration_median": None,
    "downhill_brake_episode_ramp80_median": None,
  }
  if len(grid) < 3:
    return empty

  dt = float(np.median(np.diff(grid)))
  valid = (controlling & ~brake_pressed & np.isfinite(actual_accel) &
           np.isfinite(speed) & np.isfinite(pitch))
  computer_braking = brake_request & valid
  starts = np.flatnonzero(np.diff(computer_braking.astype(np.int8), prepend=0) == 1)
  ends = np.flatnonzero(np.diff(computer_braking.astype(np.int8), append=0) == -1) + 1
  accel_smooth = causal_lpf(actual_accel, dt, smooth_tau)
  jerk = windowed_jerk(accel_smooth, dt, valid, jerk_window_s)
  rows = []
  for start in starts:
    later = ends[ends > start]
    if not len(later):
      continue
    end = int(later[0])
    duration = float(grid[end - 1] - grid[start])
    if duration < min_duration_s or speed[start] < min_speed:
      continue
    segment = accel_smooth[start:end]
    if not len(segment):
      continue
    initial = float(segment[0])
    peak = float(np.nanmin(segment))
    threshold = initial - 0.8 * (initial - peak)
    reached = np.flatnonzero(segment <= threshold)
    ramp80 = float(grid[start + reached[0]] - grid[start]) if len(reached) else None
    onset_end = min(end, start + max(1, int(round(1.5 / dt))))
    rows.append({
      "duration": duration,
      "ramp80": ramp80,
      "onset_jerk": float(np.nanmin(jerk[start:onset_end])),
      "downhill": bool(np.mean(pitch[start:end] < downhill_pitch) >= 0.5),
    })

  def median(key, selected):
    values = [row[key] for row in selected if row[key] is not None]
    return float(np.median(values)) if values else None

  downhill = [row for row in rows if row["downhill"]]
  return {
    "brake_episode_count": len(rows),
    "brake_episode_duration_median": median("duration", rows),
    "brake_episode_ramp80_median": median("ramp80", rows),
    "brake_episode_onset_jerk_median": median("onset_jerk", rows),
    "downhill_brake_episode_count": len(downhill),
    "downhill_brake_episode_duration_median": median("duration", downhill),
    "downhill_brake_episode_ramp80_median": median("ramp80", downhill),
  }


def gas_handoff_values(gas_command, gas_inactive):
  """First live GAS_COMMAND after each physically adjacent inactive-to-live transition."""
  gas = np.asarray(gas_command)
  if len(gas) < 2:
    return np.array([], dtype=gas.dtype)
  handoffs = (gas[1:] > gas_inactive) & (gas[:-1] <= gas_inactive)
  return gas[1:][handoffs]


def gasfactor_breakpoint_metrics(speed, effective, eligible, breakpoints, seed_values, *,
                                 half_width, min_exposure_s, dt):
  """Compare learned gasfactor with the live seed over the same narrow speed windows."""
  speed = np.asarray(speed, dtype=float)
  effective = np.asarray(effective, dtype=float)
  eligible = np.asarray(eligible, dtype=bool)
  breakpoints = np.asarray(breakpoints, dtype=float)
  seed_values = np.asarray(seed_values, dtype=float)
  finite = np.isfinite(speed) & np.isfinite(effective)
  learned, expected, exposure = {}, {}, {}
  for bp in breakpoints:
    key = str(float(bp))
    mask = eligible & finite & (np.abs(speed - bp) <= half_width)
    seconds = float(mask.sum() * dt)
    exposure[key] = seconds
    if seconds < min_exposure_s:
      learned[key] = expected[key] = None
      continue
    learned[key] = float(np.mean(effective[mask]))
    expected[key] = float(np.mean(np.interp(speed[mask], breakpoints, seed_values)))
  return {
    "gasf_by_speed": learned,
    "gasf_seed_by_speed": expected,
    "gasf_seconds_by_speed": exposure,
  }


def command_transition_metrics(grid, requested, engaged, vego, brake_pressed, brake_request,
                               gas_command, wire_accel, *, low_speed_vego, request_threshold,
                               command_period_s, reengage_window_s, gas_inactive):
  """Golden-trace metrics for low-speed skew, re-engagement, and gas handoffs.

  These are car-port lifecycle invariants. They deliberately do not decide ride quality or infer
  closed-loop vehicle response.
  """
  dt = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.01
  err = wire_accel - requested

  conflict = (engaged & ~brake_pressed & (vego <= low_speed_vego) &
              (requested > request_threshold) & brake_request & (gas_command <= gas_inactive))
  sustained = after_grace(conflict, dt, command_period_s)

  reengagements = np.flatnonzero(np.diff(engaged.astype(np.int8), prepend=0) == 1)
  reengage_window = post_edge_window(reengagements, len(grid), dt,
                                     command_period_s, reengage_window_s)
  reengage_stale = (reengage_window & (requested > request_threshold) &
                    brake_request & (gas_command <= gas_inactive))

  handoffs = gas_handoff_values(gas_command, gas_inactive)
  gas_live = gas_command > gas_inactive
  road_edge = (engaged[1:] & engaged[:-1] &
               (vego[1:] > low_speed_vego) & (vego[:-1] > low_speed_vego))
  gas_to_brake = road_edge & gas_live[:-1] & brake_request[1:]
  brake_to_gas = road_edge & brake_request[:-1] & gas_live[1:]
  return {
    "low_speed_conflict_sec": float(sustained.sum() * dt),
    "low_speed_conflict_events": int(np.sum(np.diff(sustained.astype(np.int8), prepend=0) == 1)),
    "low_speed_conflict_worst": float(np.nanmin(err[sustained])) if sustained.any() else 0.0,
    "low_speed_conflict_skew_frames": int(conflict.sum() - sustained.sum()),
    "reengagement_events": int(len(reengagements)),
    "reengagement_stale_sec": float(reengage_stale.sum() * dt),
    "reengagement_stale_events": int(
      np.sum(np.diff(reengage_stale.astype(np.int8), prepend=0) == 1)),
    "reengagement_stale_worst": (
      float(np.nanmin(err[reengage_stale])) if reengage_stale.any() else 0.0),
    "gas_handoff_events": int(len(handoffs)),
    "gas_handoff_max": float(np.max(handoffs)) if len(handoffs) else None,
    "direct_gas_to_brake": int(np.sum(gas_to_brake)),
    "direct_brake_to_gas": int(np.sum(brake_to_gas)),
  }


def sign_disagreement_metrics(requested, wire_accel, brake_request, active, pitch, *,
                              request_threshold, downhill_pitch, dt, transition_grace_s):
  """Measure sustained brake/accel disagreement and separate grade-owned exposure.

  A positive request can arrive one ACC_CONTROL period before the held CAN command releases.
  That transport phase is not a latched brake defect. Descents are kept separately because the
  actuator-domain decision intentionally includes gravity while ``requested`` does not.

  MAGNITUDE IS REPORTED TWICE, ON PURPOSE - they answer different questions and one of them is
  structurally near-zero here (measured 2026-08-05, routes 00000002/00000003):
    * ``sign_disagree_worst`` = min(wire - requested). This is the ACCEL_COMMAND error, and in
      exactly these frames the wire carries the request faithfully - measured -0.06 and -0.11
      m/s^2. It is the right number for a STALE-STATE leak (route 34 read -2.04 that way) and
      the wrong number for a domain hold, so ``SIGN_DISAGREE_MAG_FLAG`` at 0.50 cannot fire on
      a hold no matter how bad the hold gets. Do not "fix" that by lowering the constant; it
      guards a different failure.
    * ``sign_disagree_withheld_*`` = the REQUEST itself over those frames. GAS_COMMAND is at its
      inactive constant throughout (``brake_request`` and gas-inactive are exact complements in
      create_acc_commands - verified 0 disagreeing frames across both routes), so a positive
      ACCEL_COMMAND cannot produce acceleration. This is the severity the driver feels, and the
      integral is in m/s: the speed openpilot asked for and did not get. Measured 1.82 and 7.62
      m/s on those two routes while the error-based number stayed under 0.11.
  Both are defined only on the CarController input and the wire, never on the reconstructed
  domain or its thresholds, so two tunes can be compared on identical terms.
  """
  raw = active & brake_request & (requested > request_threshold)
  sustained = after_grace(raw, dt, transition_grace_s)
  downhill = sustained & (pitch < downhill_pitch)
  non_grade = sustained & ~downhill
  denom = max(1, int(np.sum(active)))
  err = wire_accel - requested
  runs = np.diff(sustained.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(runs == 1)
  ends = np.flatnonzero(runs == -1)
  return {
    "sign_disagree_frac": float(np.sum(sustained) / denom),
    "sign_disagree_downhill_frac": float(np.sum(downhill) / denom),
    "sign_disagree_non_grade_frac": float(np.sum(non_grade) / denom),
    "sign_disagree_worst": float(np.min(err[sustained])) if sustained.any() else 0.0,
    "sign_disagree_non_grade_worst": float(np.min(err[non_grade])) if non_grade.any() else 0.0,
    "sign_disagree_transition_frames": int(np.sum(raw) - np.sum(sustained)),
    "sign_disagree_sec": float(np.sum(sustained) * dt),
    "sign_disagree_events": int(len(starts)),
    "sign_disagree_longest": float(np.max((ends - starts) * dt)) if len(starts) else 0.0,
    "sign_disagree_withheld_integral": float(np.sum(requested[sustained]) * dt),
    "sign_disagree_withheld_worst": float(np.max(requested[sustained])) if sustained.any() else 0.0,
  }


def brake_release_hold_metrics(switch_accel, entry_threshold, requested, actual_accel,
                               brake_request, active, *, dt):
  """Measure braking retained after the compensated input clears the entry threshold."""
  hold = active & brake_request & (switch_accel >= entry_threshold)
  edges = np.diff(hold.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(edges == 1)
  ends = np.flatnonzero(edges == -1)
  durations = (ends - starts) * dt
  force_margin = switch_accel - entry_threshold
  tracking_error = actual_accel - requested
  return {
    "brake_release_hold_sec": float(np.sum(hold) * dt),
    "brake_release_hold_events": int(len(starts)),
    "brake_release_hold_max": float(np.max(durations)) if len(durations) else 0.0,
    "brake_release_hold_force_margin_mean": float(np.mean(force_margin[hold])) if hold.any() else 0.0,
    "brake_release_hold_request_mean": float(np.mean(requested[hold])) if hold.any() else 0.0,
    "brake_release_hold_tracking_mean": float(np.mean(tracking_error[hold])) if hold.any() else 0.0,
  }


def descent_hold_metrics(requested, brake_request, long_active, pitch, *,
                         request_threshold, downhill_pitch, min_episode_s, dt):
  """Count the road gate's unit directly: descent hold-episodes.

  The BRAKE_DOMAIN_ENTRY road gate (restated 2026-08-06) is scored in episodes of
  ``longActive & request > threshold & BRAKE_REQUEST & pitch < downhill_pitch`` lasting at least
  ``min_episode_s``. Until this existed the gate was scored by ad-hoc offline analysis, and the
  hand-summed totals in the evidence doc drifted (12 + 13 was recorded as 26). Same underlying
  frames as ``sign_disagree_downhill_frac`` minus the vEgo/brake-pressed narrowing - deliberate
  overlap: this is the gate's bookkeeping counter, not a new verdict, so it carries no flag.
  """
  hold = long_active & brake_request & (requested > request_threshold) & (pitch < downhill_pitch)
  edges = np.diff(hold.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(edges == 1)
  ends = np.flatnonzero(edges == -1)
  durations = (ends - starts) * dt
  episodes = durations >= min_episode_s
  return {
    "descent_hold_episodes": int(np.sum(episodes)),
    "descent_hold_sec": float(np.sum(durations[episodes])),
    "descent_hold_longest": float(np.max(durations[episodes])) if episodes.any() else 0.0,
  }


def shadow_windfactor_metrics(grid, requested, actual_accel, speed, pitch, active_pid,
                              gas_pressed, brake_pressed, brake_request, gas_command, *,
                              gas_inactive, gas_max, accel_min, accel_max, base_drag,
                              initial_windfactor, windfactor_min, windfactor_max,
                              learn_divisor, update_period_s, min_speed, steady_accel,
                              steady_pitch_rate, accel_rail_margin, gas_rail_margin):
  """Run the proposed gas-active-only wind learner without changing recorded commands.

  This deliberately replays the production learner's sign-only multiplicative update on a much
  narrower identification gate. It can establish exposure and convergence, but the recorded
  plant response is frozen, so its error statistics are observational rather than a prediction
  of closed-loop ride quality.
  """
  n = len(grid)
  if n < 2:
    return {
      "windf_shadow_eligible_min": 0.0,
      "windf_shadow_start": float(initial_windfactor),
      "windf_shadow_end": float(initial_windfactor),
      "windf_shadow_min": float(initial_windfactor),
      "windf_shadow_max": float(initial_windfactor),
      "windf_shadow_drift": 0.0,
      "windf_shadow_floor_frac": None,
      "windf_shadow_error_mean": None,
      "windf_shadow_error_rms": None,
    }

  dt = float(np.median(np.diff(grid)))
  pitch_rate = np.gradient(pitch, dt)
  error = requested - actual_accel
  eligible = (
    active_pid & ~gas_pressed & ~brake_pressed & ~brake_request &
    (gas_command > gas_inactive) &
    (gas_command < gas_max - gas_rail_margin) &
    (requested > accel_min + accel_rail_margin) &
    (requested < accel_max - accel_rail_margin) &
    (speed >= min_speed) &
    (np.abs(actual_accel) <= steady_accel) &
    (np.abs(pitch_rate) <= steady_pitch_rate)
  )

  cadence = max(1, int(round(update_period_s / max(dt, 1e-6))))
  update = eligible & ((np.arange(n) % cadence) == 0)
  shadow = np.empty(n, dtype=float)
  value = float(initial_windfactor)
  for i in range(n):
    if update[i]:
      adjustment = 1.0 + max(0.0, float(base_drag[i])) / learn_divisor
      value = value * adjustment if error[i] > 0.0 else value / adjustment
      value = float(np.clip(value, windfactor_min, windfactor_max))
    shadow[i] = value

  eligible_values = shadow[eligible]
  eligible_error = error[eligible]
  floor_frac = (float(np.mean(eligible_values <= windfactor_min + 1e-6))
                if len(eligible_values) else None)
  return {
    "windf_shadow_eligible_min": float(np.sum(eligible) * dt / 60.0),
    "windf_shadow_start": float(initial_windfactor),
    "windf_shadow_end": float(value),
    "windf_shadow_min": float(np.min(shadow)),
    "windf_shadow_max": float(np.max(shadow)),
    "windf_shadow_drift": float(value - initial_windfactor),
    "windf_shadow_floor_frac": floor_frac,
    "windf_shadow_error_mean": float(np.mean(eligible_error)) if len(eligible_error) else None,
    "windf_shadow_error_rms": (float(np.sqrt(np.mean(eligible_error ** 2)))
                                if len(eligible_error) else None),
  }


def stop_lurch_metrics(requested, wire_accel, actual_accel, speed, engaged, stop_state, *,
                       min_speed, max_speed):
  """Attribute low-speed excess deceleration at the worst achieved-vs-request event."""
  stopping = engaged & (speed > min_speed) & (speed < max_speed) & (actual_accel < 0.0)
  if np.sum(stopping) == 0:
    return {
      "stop_lurch_worst": None,
      "stop_lurch_excess": None,
      "stop_lurch_wire_extra": None,
      "stop_lurch_actuator_extra": None,
      "stop_lurch_request": None,
      "stop_lurch_wire": None,
      "stop_lurch_speed": None,
      "stop_lurch_in_stopping": None,
    }

  excess = requested - actual_accel
  worst_i = int(np.nanargmax(np.where(stopping, excess, np.nan)))
  return {
    "stop_lurch_worst": float(-actual_accel[worst_i]),
    "stop_lurch_excess": float(excess[worst_i]),
    "stop_lurch_wire_extra": float(requested[worst_i] - wire_accel[worst_i]),
    "stop_lurch_actuator_extra": float(wire_accel[worst_i] - actual_accel[worst_i]),
    "stop_lurch_request": float(requested[worst_i]),
    "stop_lurch_wire": float(wire_accel[worst_i]),
    "stop_lurch_speed": float(speed[worst_i]),
    "stop_lurch_in_stopping": bool(stop_state[worst_i]),
  }
