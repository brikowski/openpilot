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


def steering_forwarding_metrics(sent, received, state_t, speed, steering_pressed,
                                steer_fault_temp, steer_fault_perm, *, min_speed,
                                cap_command, extended_command, settle_s, max_delay_s):
  """Compare camera/radar-bus steering sends with the radar-forwarded powertrain-bus frames.

  Honda's two-bit counter repeats every four frames, so each received frame is matched to the
  latest earlier sent frame with the same counter and a bounded transport delay. The caller passes
  decoded ``[time, torque, request, counter]`` arrays and native car-state arrays; this function
  remains independent from route I/O and DBC parsing for mutation-tested attribution.
  """
  keys = (
    "lat_radar_forward_matched_frames", "lat_radar_forward_active_frames",
    "lat_radar_forward_clean_frames", "lat_radar_forward_dropped_request_frames",
    "lat_radar_forward_delay_ms_median", "lat_radar_forward_delay_ms_p99",
    "lat_radar_forward_mae", "lat_radar_forward_corr",
    "lat_radar_forward_source_max_abs", "lat_radar_forward_output_max_abs",
    "lat_radar_forward_cap_stable_sec", "lat_radar_forward_cap_gain_median",
    "lat_radar_forward_cap_exact_frac", "lat_radar_forward_extended_source_sec",
    "lat_radar_forward_extended_output_sec", "lat_radar_forward_extended_gain_median",
    "lat_radar_forward_extended_output_max_abs",
  )
  out = dict.fromkeys(keys)
  sent = np.asarray(sent, dtype=float)
  received = np.asarray(received, dtype=float)
  state_t = np.asarray(state_t, dtype=float)
  if sent.ndim != 2 or received.ndim != 2 or sent.shape[1:] != (4,) or received.shape[1:] != (4,):
    return out
  if not len(sent) or not len(received) or not len(state_t):
    return out

  source_rows = []
  received_rows = []
  for counter in np.unique(received[:, 3]):
    sent_idx = np.flatnonzero(sent[:, 3] == counter)
    recv_idx = np.flatnonzero(received[:, 3] == counter)
    if not len(sent_idx) or not len(recv_idx):
      continue
    source_pos = np.searchsorted(sent[sent_idx, 0], received[recv_idx, 0], side="right") - 1
    valid = source_pos >= 0
    source_idx = sent_idx[np.clip(source_pos, 0, len(sent_idx) - 1)]
    delay = received[recv_idx, 0] - sent[source_idx, 0]
    valid &= (delay >= 0.0) & (delay <= max_delay_s)
    source_rows.extend(source_idx[valid])
    received_rows.extend(recv_idx[valid])

  if not source_rows:
    return out
  source_rows = np.asarray(source_rows, dtype=int)
  received_rows = np.asarray(received_rows, dtype=int)
  order = np.argsort(received[received_rows, 0])
  source = sent[source_rows[order]]
  forwarded = received[received_rows[order]]
  delay = forwarded[:, 0] - source[:, 0]

  state_idx = np.searchsorted(state_t, forwarded[:, 0], side="right") - 1
  state_valid = state_idx >= 0
  state_idx = np.clip(state_idx, 0, len(state_t) - 1)
  speed = np.asarray(speed, dtype=float)[state_idx]
  steering_pressed = np.asarray(steering_pressed, dtype=bool)[state_idx]
  steer_fault_temp = np.asarray(steer_fault_temp, dtype=bool)[state_idx]
  steer_fault_perm = np.asarray(steer_fault_perm, dtype=bool)[state_idx]

  source_request = source[:, 2] > 0.5
  forwarded_request = forwarded[:, 2] > 0.5
  active = source_request & forwarded_request
  clean = (active & state_valid & (speed >= min_speed) & ~steering_pressed &
           ~steer_fault_temp & ~steer_fault_perm)
  dropped = source_request & ~forwarded_request
  source_torque = source[:, 1]
  forwarded_torque = forwarded[:, 1]
  out.update({
    "lat_radar_forward_matched_frames": int(len(source)),
    "lat_radar_forward_active_frames": int(active.sum()),
    "lat_radar_forward_clean_frames": int(clean.sum()),
    "lat_radar_forward_dropped_request_frames": int(dropped.sum()),
    "lat_radar_forward_delay_ms_median": float(np.median(delay) * 1e3),
    "lat_radar_forward_delay_ms_p99": float(np.percentile(delay, 99) * 1e3),
    "lat_radar_forward_source_max_abs": float(np.max(np.abs(source_torque[clean]))) if clean.any() else None,
    "lat_radar_forward_output_max_abs": float(np.max(np.abs(forwarded_torque[clean]))) if clean.any() else None,
  })
  if active.sum() > 1:
    out["lat_radar_forward_mae"] = float(np.mean(np.abs(source_torque[active] - forwarded_torque[active])))
    if np.std(source_torque[active]) > 0.0 and np.std(forwarded_torque[active]) > 0.0:
      out["lat_radar_forward_corr"] = float(np.corrcoef(source_torque[active], forwarded_torque[active])[0, 1])

  dt = float(np.median(np.diff(forwarded[:, 0]))) if len(forwarded) > 1 else 0.01
  high = clean & (np.abs(source_torque) >= cap_command)
  stable_high = after_grace(high, dt, settle_s)
  if stable_high.any():
    gain = np.abs(forwarded_torque[stable_high]) / np.maximum(np.abs(source_torque[stable_high]), 1.0)
    out["lat_radar_forward_cap_stable_sec"] = float(stable_high.sum() * dt)
    out["lat_radar_forward_cap_gain_median"] = float(np.median(gain))
    out["lat_radar_forward_cap_exact_frac"] = float(np.mean(source_torque[stable_high] == forwarded_torque[stable_high]))
  else:
    out["lat_radar_forward_cap_stable_sec"] = 0.0

  extended = clean & (np.abs(source_torque) > extended_command)
  extended_output = extended & (np.abs(forwarded_torque) > extended_command)
  out["lat_radar_forward_extended_source_sec"] = float(extended.sum() * dt)
  out["lat_radar_forward_extended_output_sec"] = float(extended_output.sum() * dt)
  if extended.any():
    gain = np.abs(forwarded_torque[extended]) / np.maximum(np.abs(source_torque[extended]), 1.0)
    out["lat_radar_forward_extended_gain_median"] = float(np.median(gain))
    out["lat_radar_forward_extended_output_max_abs"] = float(np.max(np.abs(forwarded_torque[extended])))
  return out


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


def gas_reentry_pulse_metrics(grid, requested, engaged, vego, brake_request, brake_pressed,
                              gas_command, *, low_speed_vego, gas_inactive,
                              entry_request_max, short_duration_s, entry_window_s):
  """Measure short gas re-entries from a moving coast domain.

  This is a symptom readout, not a tuning rule. A re-entry is counted only when the preceding
  moving frame was neither gas nor brake, so a normal brake-to-gas handoff is kept separate. The
  entry request is the largest controller request over one command period after the gas edge;
  using a short window avoids mistaking the 50 Hz CAN hold for a small controller request.
  """
  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  engaged = np.asarray(engaged, dtype=bool)
  vego = np.asarray(vego, dtype=float)
  brake_request = np.asarray(brake_request, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  gas_live = np.asarray(gas_command, dtype=float) > gas_inactive
  empty = {
    "gas_reentry_pulse_events": 0,
    "gas_reentry_pulse_short_events": 0,
    "gas_reentry_pulse_tiny_events": 0,
    "gas_reentry_pulse_tiny_short_events": 0,
    "gas_reentry_pulse_duration_median": None,
    "gas_reentry_pulse_tiny_duration_median": None,
    "gas_reentry_pulse_entry_request_max": None,
  }
  if len(grid) < 3:
    return empty

  dt = float(np.median(np.diff(grid)))
  moving = engaged & ~brake_pressed & (vego > low_speed_vego)
  active_gas = moving & gas_live
  starts = np.flatnonzero(np.diff(active_gas.astype(np.int8), prepend=0) == 1)
  ends = np.flatnonzero(np.diff(active_gas.astype(np.int8), append=0) == -1) + 1
  entry_frames = max(1, int(np.ceil(entry_window_s / max(dt, 1e-6))))
  rows = []
  for start in starts:
    if start == 0 or not (moving[start - 1] and not gas_live[start - 1] and
                          not brake_request[start - 1]):
      continue
    later = ends[ends > start]
    if not len(later):
      continue
    end = int(later[0])
    # A normal command shutdown is not a gas pulse. Require the vehicle to remain in the moving
    # control mask when gas ends; this excludes longitudinal disengagement and driver-brake exits.
    if end >= len(moving) or not moving[end]:
      continue
    duration = float(grid[end - 1] - grid[start])
    entry_end = min(end, start + entry_frames)
    entry_requests = requested[start:entry_end]
    if not len(entry_requests) or not np.isfinite(entry_requests).any():
      continue
    entry_request = float(np.nanmax(entry_requests))
    rows.append((duration, entry_request))

  durations = [duration for duration, _ in rows]
  tiny = [(duration, request) for duration, request in rows if request <= entry_request_max]
  short = [duration for duration in durations if duration < short_duration_s]
  tiny_short = [duration for duration, request in tiny if duration < short_duration_s]
  return {
    "gas_reentry_pulse_events": len(rows),
    "gas_reentry_pulse_short_events": len(short),
    "gas_reentry_pulse_tiny_events": len(tiny),
    "gas_reentry_pulse_tiny_short_events": len(tiny_short),
    "gas_reentry_pulse_duration_median": float(np.median(durations)) if durations else None,
    "gas_reentry_pulse_tiny_duration_median": (
      float(np.median([duration for duration, _ in tiny])) if tiny else None),
    "gas_reentry_pulse_entry_request_max": (
      float(max(request for _, request in rows)) if rows else None),
  }


def negative_request_gas_metrics(grid, requested, engaged, vego, brake_pressed,
                                 brake_request, gas_command, *, low_speed_vego,
                                 request_threshold, gas_inactive, dt=None):
  """Measure live gas while the controller requests a mild negative acceleration.

  This is a diagnostic readout of the upstream-domain split, not a tuning rule or a comfort
  verdict. It intentionally excludes the low-speed stop/start region, driver-brake frames, and
  any frame where Honda's brake domain is live.
  """
  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  engaged = np.asarray(engaged, dtype=bool)
  vego = np.asarray(vego, dtype=float)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  brake_request = np.asarray(brake_request, dtype=bool)
  gas_live = np.asarray(gas_command, dtype=float) > gas_inactive
  empty = {
    "negative_request_gas_sec": 0.0,
    "negative_request_gas_events": 0,
    "negative_request_gas_longest": 0.0,
    "negative_request_gas_request_min": None,
  }
  if not len(grid):
    return empty
  if dt is None:
    dt = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  eligible = (engaged & ~brake_pressed & (vego >= low_speed_vego) &
              (requested < request_threshold) & gas_live & ~brake_request)
  transitions = np.diff(eligible.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(transitions == 1)
  ends = np.flatnonzero(transitions == -1)
  durations = (ends - starts) * dt
  return {
    "negative_request_gas_sec": float(eligible.sum() * dt),
    "negative_request_gas_events": int(len(starts)),
    "negative_request_gas_longest": float(np.max(durations)) if len(durations) else 0.0,
    "negative_request_gas_request_min": (
      float(np.nanmin(requested[eligible])) if eligible.any() else None),
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
  """Measure braking retained after the production domain input clears its entry threshold."""
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

  The historical domain-entry road gate (restated 2026-08-06) is scored in episodes of
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
