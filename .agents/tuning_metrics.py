"""Pure, synthetic-testable metrics used by the Odyssey log validator.

Keep log I/O, CAN decoding, ledger mutation, and verdict policy in validate_log.py. Functions in
this module accept arrays and return arrays or metric dictionaries, so every behavior-changing
measurement can be mutation-tested without needing a route or comma device.
"""

import numpy as np

CRUISE_SET_SPEED_UNSET_MPS = 255.0 / 3.6  # selfdrive.car.cruise.V_CRUISE_UNSET, converted from km/h


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


def steering_direct_metrics(sent, output_t, output_torque_can, *, stock_cap, max_delay_s=0.05):
  """Compare Alpha Long bus-1 steering TX to the same-cycle carOutput published just after TX.

  This verifies the logged command path, not EPS acceptance or vehicle turning response. The
  caller supplies decoded ``[time, torque, request, counter]`` TX frames and carOutput series.
  """
  out = dict.fromkeys((
    "lat_direct_sent_frames", "lat_direct_active_frames", "lat_direct_sent_max_abs",
    "lat_direct_extended_frames", "lat_direct_paired_frames", "lat_direct_exact_frac",
    "lat_direct_mae", "lat_direct_max_error", "lat_direct_delay_ms_median",
  ))
  sent = np.asarray(sent, dtype=float)
  output_t = np.asarray(output_t, dtype=float)
  output_torque_can = np.asarray(output_torque_can, dtype=float)
  if sent.ndim != 2 or sent.shape[1:] != (4,) or not len(sent):
    return out
  active = sent[:, 2] > 0.5
  out.update({
    "lat_direct_sent_frames": int(len(sent)),
    "lat_direct_active_frames": int(active.sum()),
    "lat_direct_sent_max_abs": float(np.max(np.abs(sent[active, 1]))) if active.any() else None,
    "lat_direct_extended_frames": int(np.sum(active & (np.abs(sent[:, 1]) > stock_cap))),
    "lat_direct_paired_frames": 0,
  })
  if not len(output_t) or len(output_t) != len(output_torque_can):
    return out
  idx = np.searchsorted(output_t, sent[:, 0], side="left")
  valid = idx < len(output_t)
  delay = output_t[np.minimum(idx, len(output_t) - 1)] - sent[:, 0]
  valid &= (delay >= 0.0) & (delay <= max_delay_s)
  if not valid.any():
    return out
  error = sent[valid, 1] - output_torque_can[idx[valid]]
  out.update({
    "lat_direct_paired_frames": int(valid.sum()),
    "lat_direct_exact_frac": float(np.mean(error == 0)),
    "lat_direct_mae": float(np.mean(np.abs(error))),
    "lat_direct_max_error": float(np.max(np.abs(error))),
    "lat_direct_delay_ms_median": float(np.median(delay[valid]) * 1e3),
  })
  return out


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


def response_jerk_events(grid, planner, requested, wire, actual_accel, active, brake_request,
                         computer_braking, gas_command, speed, pitch, has_lead, plan_source, gear,
                         engine_torque, rpm,
                         *, gas_inactive,
                         min_speed=5.0, threshold=1.0, separation_s=0.75, history_s=1.5,
                         attribution_s=0.10, smooth_tau=0.20, jerk_window_s=0.10, limit=8):
  """Rank achieved-jerk peaks and retain the command-path context that preceded each one.

  This is an attribution diagnostic, not an acceptance threshold. The response peak is compared
  with the largest wire-command jerk in its causal history, while planner/request and request/wire
  RMS keep an upstream or Honda-translation divergence visible. Domain edges are counted from the
  discrete zero-order-held commands supplied by the caller.
  """
  arrays = [planner, requested, wire, actual_accel, active, brake_request, computer_braking, gas_command,
            speed, pitch, has_lead, plan_source, gear, engine_torque, rpm]
  if len(grid) < 3 or any(len(x) != len(grid) for x in arrays):
    return []

  grid = np.asarray(grid, dtype=float)
  planner = np.asarray(planner, dtype=float)
  requested = np.asarray(requested, dtype=float)
  wire = np.asarray(wire, dtype=float)
  actual_accel = np.asarray(actual_accel, dtype=float)
  active = np.asarray(active, dtype=bool)
  brake_request = np.asarray(brake_request, dtype=bool)
  computer_braking_raw = np.asarray(computer_braking, dtype=float)
  computer_braking_valid = np.isfinite(computer_braking_raw)
  computer_braking = np.nan_to_num(computer_braking_raw, nan=0.0) > 0.5
  gas_command = np.asarray(gas_command, dtype=float)
  speed = np.asarray(speed, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  has_lead = np.asarray(has_lead, dtype=bool)
  plan_source = np.asarray(plan_source, dtype=int)
  gear = np.asarray(gear, dtype=float)
  engine_torque = np.asarray(engine_torque, dtype=float)
  rpm = np.asarray(rpm, dtype=float)
  dt = float(np.median(np.diff(grid)))
  if not np.isfinite(dt) or dt <= 0.0:
    return []

  finite = (np.isfinite(planner) & np.isfinite(requested) & np.isfinite(wire) &
            np.isfinite(actual_accel) & np.isfinite(speed) & np.isfinite(pitch))
  valid = active & finite & (speed >= min_speed)
  response_jerk = windowed_jerk(causal_lpf(actual_accel, dt, smooth_tau), dt, valid, jerk_window_s)
  command_jerk = windowed_jerk(causal_lpf(wire, dt, smooth_tau), dt, valid, jerk_window_s)

  domain = np.where(brake_request, 2, np.where(gas_command > gas_inactive, 1, 0))
  edges = physical_edges(domain, valid)
  computer_brake_edges = physical_edges(computer_braking, valid & computer_braking_valid)
  computer_brake_rises = computer_brake_edges[computer_braking[computer_brake_edges]]
  local_peak = np.ones(len(grid), dtype=bool)
  local_peak[1:-1] = ((np.abs(response_jerk[1:-1]) >= np.abs(response_jerk[:-2])) &
                      (np.abs(response_jerk[1:-1]) > np.abs(response_jerk[2:])))
  candidates = np.flatnonzero(valid & local_peak & (np.abs(response_jerk) >= threshold))

  selected = []
  for index in candidates[np.argsort(np.abs(response_jerk[candidates]))[::-1]]:
    if any(abs(grid[index] - grid[prior]) < separation_s for prior in selected):
      continue
    selected.append(int(index))
    if limit is not None and len(selected) >= limit:
      break

  names = ("coast", "gas", "brake")
  rows = []
  for index in sorted(selected, key=lambda i: grid[i]):
    history = valid & (grid >= grid[index] - history_s) & (grid <= grid[index])
    history_idx = np.flatnonzero(history)
    if not len(history_idx):
      continue
    command_peak_index = history_idx[np.argmax(np.abs(command_jerk[history_idx]))]
    attribution = history & (grid >= grid[index] - attribution_s)
    previous_edges = edges[edges <= index]
    last_edge = int(previous_edges[-1]) if len(previous_edges) else None
    edge_age = float(grid[index] - grid[last_edge]) if last_edge is not None else None
    domain_from = names[int(domain[last_edge - 1])] if last_edge is not None and last_edge > 0 else None
    computer_brake_edge = None
    if (last_edge is not None and domain[index] == 2 and computer_braking_valid[last_edge - 1] and
        not computer_braking[last_edge - 1]):
      following = computer_brake_rises[(computer_brake_rises >= last_edge) & (computer_brake_rises <= index)]
      computer_brake_edge = int(following[0]) if len(following) else None
    request_to_computer_brake = (float(grid[computer_brake_edge] - grid[last_edge])
                                 if computer_brake_edge is not None else None)
    computer_brake_to_peak = (float(grid[index] - grid[computer_brake_edge])
                              if computer_brake_edge is not None else None)
    history_edges = int(np.sum((edges >= history_idx[0]) & (edges <= index)))
    gear_edges = physical_edges(gear, history & np.isfinite(gear))
    response = float(response_jerk[index])
    command = float(command_jerk[command_peak_index])
    rows.append({
      "time": float(grid[index]),
      "response_jerk": response,
      "command_jerk_peak": command,
      "amplification": float(abs(response) / max(abs(command), 1e-6)),
      "domain": names[int(domain[index])],
      "domain_from": domain_from,
      "domain_edge_age": edge_age,
      "domain_edges_in_history": history_edges,
      "computer_braking_before_entry": (bool(computer_braking[last_edge - 1])
                                          if last_edge is not None and last_edge > 0 and
                                          computer_braking_valid[last_edge - 1] else None),
      "computer_braking_at_peak": (bool(computer_braking[index])
                                     if computer_braking_valid[index] else None),
      "request_to_computer_brake_s": request_to_computer_brake,
      "computer_brake_to_peak_s": computer_brake_to_peak,
      "gear_edges_in_history": int(len(gear_edges)),
      "plan_request_rms": float(np.sqrt(np.mean((planner[attribution] - requested[attribution]) ** 2))),
      "request_wire_rms": float(np.sqrt(np.mean((requested[attribution] - wire[attribution]) ** 2))),
      "request": float(requested[index]),
      "wire": float(wire[index]),
      "actual_accel": float(actual_accel[index]),
      "speed": float(speed[index]),
      "pitch": float(pitch[index]),
      "has_lead": bool(has_lead[index]),
      "plan_source": int(plan_source[index]),
      "gear": float(gear[index]),
      "engine_torque": float(engine_torque[index]),
      "rpm": float(rpm[index]),
    })
  return rows


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


def active_zero_gas_metrics(grid, requested, achieved, engaged, vego, brake_request,
                            brake_pressed, gas_command, *, low_speed_vego,
                            short_duration_s, dt=None):
  """Describe Honda's live gas domain with a zero ``GAS_COMMAND``.

  Active zero is distinct from both inactive gas and positive gas on Honda Bosch. This ungraded
  readout isolates that state above the low-speed stop/start region and reports the vehicle response
  without asserting that active zero is better than coast for any particular request.
  """
  arrays = [grid, requested, achieved, engaged, vego, brake_request, brake_pressed, gas_command]
  n = len(grid)
  empty = {
    "active_zero_gas_sec": 0.0,
    "active_zero_gas_events": 0,
    "active_zero_gas_short_events": 0,
    "active_zero_gas_longest": 0.0,
    "active_zero_gas_request_min": None,
    "active_zero_gas_request_max": None,
    "active_zero_gas_response_error_mean": None,
    "active_zero_gas_response_error_rms": None,
  }
  if not n or any(len(np.asarray(value)) != n for value in arrays[1:]):
    return empty

  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  achieved = np.asarray(achieved, dtype=float)
  engaged = np.asarray(engaged, dtype=bool)
  vego = np.asarray(vego, dtype=float)
  brake_request = np.asarray(brake_request, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  gas_command = np.asarray(gas_command, dtype=float)
  if dt is None:
    dt = float(np.median(np.diff(grid))) if n > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  eligible = (engaged & ~brake_pressed & (vego >= low_speed_vego) & ~brake_request &
              (gas_command == 0.0))
  transitions = np.diff(eligible.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(transitions == 1)
  ends = np.flatnonzero(transitions == -1)
  durations = (ends - starts) * dt
  finite_request = eligible & np.isfinite(requested)
  finite_response = finite_request & np.isfinite(achieved)
  response_error = achieved[finite_response] - requested[finite_response]
  return {
    "active_zero_gas_sec": float(eligible.sum() * dt),
    "active_zero_gas_events": int(len(starts)),
    "active_zero_gas_short_events": int(np.sum(durations < short_duration_s)),
    "active_zero_gas_longest": float(np.max(durations)) if len(durations) else 0.0,
    "active_zero_gas_request_min": (
      float(np.min(requested[finite_request])) if finite_request.any() else None),
    "active_zero_gas_request_max": (
      float(np.max(requested[finite_request])) if finite_request.any() else None),
    "active_zero_gas_response_error_mean": (
      float(np.mean(response_error)) if len(response_error) else None),
    "active_zero_gas_response_error_rms": (
      float(np.sqrt(np.mean(response_error ** 2))) if len(response_error) else None),
  }


def negative_live_gas_bridge_metrics(grid, requested, achieved, engaged, vego, brake_request,
                                     brake_pressed, gas_command, *, low_speed_vego,
                                     bridge_entry_min, bridge_command, gas_inactive, smooth_tau,
                                     jerk_window_s, dt=None):
  """Describe the Odyssey's inferred negative-live gas bridge and achieved response."""
  arrays = [grid, requested, achieved, engaged, vego, brake_request, brake_pressed, gas_command]
  n = len(grid)
  empty = {
    "gas_bridge_sec": 0.0,
    "gas_bridge_events": 0,
    "gas_bridge_longest": 0.0,
    "gas_bridge_request_min": None,
    "gas_bridge_request_max": None,
    "gas_bridge_response_error_mean": None,
    "gas_bridge_response_error_median": None,
    "gas_bridge_response_error_rms": None,
    "gas_bridge_felt_jerk_rms": None,
    "gas_bridge_felt_jerk_p95": None,
    "gas_bridge_brake_overlap_sec": 0.0,
    "gas_bridge_low_speed_sec": 0.0,
    "gas_bridge_exit_events": 0,
    "gas_bridge_exit_jerk_median": None,
    "gas_bridge_exit_jerk_p90": None,
    "gas_bridge_event_details": [],
  }
  if not n or any(len(np.asarray(value)) != n for value in arrays[1:]):
    return empty

  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  achieved = np.asarray(achieved, dtype=float)
  engaged = np.asarray(engaged, dtype=bool)
  vego = np.asarray(vego, dtype=float)
  brake_request = np.asarray(brake_request, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  gas_command = np.asarray(gas_command, dtype=float)
  if dt is None:
    dt = float(np.median(np.diff(grid))) if n > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  exact_bridge = np.isclose(gas_command, bridge_command, atol=0.5)
  bridge_state = np.zeros(n, dtype=bool)
  for i in range(n):
    if not exact_bridge[i]:
      continue
    continuing = i > 0 and bridge_state[i - 1]
    prior_inactive = i == 0 or gas_command[i - 1] <= gas_inactive
    entering = prior_inactive and np.isfinite(requested[i]) and bridge_entry_min <= requested[i] < 0.0
    bridge_state[i] = continuing or entering

  candidate = engaged & ~brake_pressed & (vego >= low_speed_vego) & ~brake_request & bridge_state
  transitions = np.diff(candidate.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(transitions == 1)
  ends = np.flatnonzero(transitions == -1)
  durations = (ends - starts) * dt

  finite_request = candidate & np.isfinite(requested)
  finite_response = finite_request & np.isfinite(achieved)
  response_error = achieved[finite_response] - requested[finite_response]
  jerk = windowed_jerk(causal_lpf(achieved, dt, smooth_tau), dt, engaged, jerk_window_s)
  finite_jerk = candidate & np.isfinite(jerk)

  exit_edges = np.flatnonzero(candidate[:-1] & ~candidate[1:] &
                              engaged[1:] & (gas_command[1:] >= 0.0)) + 1
  exit_jerks = []
  event_details = []
  start_offset = max(0, int(np.ceil(0.15 / dt)))
  end_offset = max(start_offset + 1, int(np.ceil(0.80 / dt)))
  for edge in exit_edges:
    values = jerk[min(n, edge + start_offset):min(n, edge + end_offset)]
    values = values[np.isfinite(values)]
    if len(values):
      exit_jerks.append(float(np.max(values)))

  for start, end in zip(starts, ends, strict=True):
    event_request = requested[start:end]
    event_achieved = achieved[start:end]
    finite = np.isfinite(event_request) & np.isfinite(event_achieved)
    trend_start = max(0, start - max(1, int(round(0.02 / dt))))
    context_start = max(0, start - max(1, int(round(0.20 / dt))))
    positive_exit = end < n and engaged[end] and gas_command[end] >= 0.0
    values = jerk[min(n, end + start_offset):min(n, end + end_offset)] if positive_exit else np.array([])
    values = values[np.isfinite(values)]
    event_details.append({
      "start_s": float(grid[start] - grid[0]),
      "duration_s": float((end - start) * dt),
      "request_start": float(requested[start]) if np.isfinite(requested[start]) else None,
      "request_delta_20ms": (float(requested[start] - requested[trend_start])
                             if np.isfinite(requested[start]) and np.isfinite(requested[trend_start]) else None),
      "request_before_200ms": float(requested[context_start]) if np.isfinite(requested[context_start]) else None,
      "request_delta_200ms": (float(requested[start] - requested[context_start])
                              if np.isfinite(requested[start]) and np.isfinite(requested[context_start]) else None),
      "request_min": float(np.min(event_request[np.isfinite(event_request)])) if np.isfinite(event_request).any() else None,
      "request_max": float(np.max(event_request[np.isfinite(event_request)])) if np.isfinite(event_request).any() else None,
      "speed_median": float(np.median(vego[start:end])) if end > start else None,
      "response_error_mean": float(np.mean(event_achieved[finite] - event_request[finite])) if finite.any() else None,
      "positive_exit": bool(positive_exit),
      "exit_jerk_max": float(np.max(values)) if len(values) else None,
    })

  return {
    "gas_bridge_sec": float(candidate.sum() * dt),
    "gas_bridge_events": int(len(starts)),
    "gas_bridge_longest": float(np.max(durations)) if len(durations) else 0.0,
    "gas_bridge_request_min": float(np.min(requested[finite_request])) if finite_request.any() else None,
    "gas_bridge_request_max": float(np.max(requested[finite_request])) if finite_request.any() else None,
    "gas_bridge_response_error_mean": float(np.mean(response_error)) if len(response_error) else None,
    "gas_bridge_response_error_median": float(np.median(response_error)) if len(response_error) else None,
    "gas_bridge_response_error_rms": float(np.sqrt(np.mean(response_error ** 2))) if len(response_error) else None,
    "gas_bridge_felt_jerk_rms": (
      float(np.sqrt(np.mean(jerk[finite_jerk] ** 2))) if finite_jerk.any() else None),
    "gas_bridge_felt_jerk_p95": (
      float(np.percentile(np.abs(jerk[finite_jerk]), 95)) if finite_jerk.any() else None),
    "gas_bridge_brake_overlap_sec": float((bridge_state & engaged & (brake_request | brake_pressed)).sum() * dt),
    "gas_bridge_low_speed_sec": float((bridge_state & engaged & (vego < low_speed_vego)).sum() * dt),
    "gas_bridge_exit_events": len(exit_jerks),
    "gas_bridge_exit_jerk_median": float(np.median(exit_jerks)) if exit_jerks else None,
    "gas_bridge_exit_jerk_p90": float(np.percentile(exit_jerks, 90)) if exit_jerks else None,
    "gas_bridge_event_details": event_details,
  }


def uphill_near_zero_gas_step_metrics(grid, requested, engaged, vego, pitch,
                                      brake_request, brake_pressed, gas_command, *,
                                      speed_min, pitch_min, pitch_max, request_abs_max,
                                      request_delta_max, gas_delta_min):
  """Count large live-gas steps while a small uphill request barely changes.

  This is a command-path diagnostic, not a ride score. Requiring live positive gas and no
  brake on both sides excludes gas-domain entries and the negative-live bridge.
  """
  grid = np.asarray(grid, dtype=float)
  empty = {"uphill_near_zero_gas_exposure_sec": 0.0,
           "uphill_near_zero_gas_step_events": 0,
           "uphill_near_zero_gas_step_median": None}
  if len(grid) < 2:
    return empty

  requested = np.asarray(requested, dtype=float)
  gas = np.asarray(gas_command, dtype=float)
  eligible = (np.asarray(engaged, dtype=bool) & ~np.asarray(brake_request, dtype=bool) &
              ~np.asarray(brake_pressed, dtype=bool) & (np.asarray(vego, dtype=float) > speed_min) &
              (np.asarray(pitch, dtype=float) >= pitch_min) &
              (np.asarray(pitch, dtype=float) <= pitch_max) &
              (np.abs(requested) < request_abs_max) & (gas > 0.0))
  pair = eligible[1:] & eligible[:-1] & (np.abs(np.diff(requested)) < request_delta_max)
  jumps = np.abs(np.diff(gas))[pair & (np.abs(np.diff(gas)) > gas_delta_min)]
  return {
    "uphill_near_zero_gas_exposure_sec": float(pair.sum() * np.median(np.diff(grid))),
    "uphill_near_zero_gas_step_events": int(len(jumps)),
    "uphill_near_zero_gas_step_median": float(np.median(jumps)) if len(jumps) else None,
  }


def uphill_negative_gas_tracking_metrics(grid, requested, actual_accel, speed, pitch, active_pid,
                                         gas_pressed, brake_pressed, brake_request, gas_command, *,
                                         gas_inactive, pitch_min=0.015, speed_min=10.0,
                                         response_delay_s=0.6, pitch_filter_tau=0.5):
  """Grade the live-gas uphill bands changed by the bounded negative-request translation."""
  bands = {"transition": (-0.20, -0.10), "near_zero": (-0.10, 0.0)}
  fields = ("sec", "events", "request_median", "pitch_median", "gas_median",
            "response_error_mean", "response_error_median", "response_error_rms")
  result = {f"uphill_negative_{name}_{field}": (0 if field == "events" else (0.0 if field == "sec" else None))
            for name in bands for field in fields}
  arrays = (requested, actual_accel, speed, pitch, active_pid, gas_pressed,
            brake_pressed, brake_request, gas_command)
  n = len(grid)
  if n < 3 or any(len(np.asarray(a)) != n for a in arrays):
    return result

  grid = np.asarray(grid, dtype=float)
  dt = float(np.median(np.diff(grid)))
  if not np.isfinite(dt) or dt <= 0.0:
    return result
  requested, actual_accel, speed, pitch, gas_command = (
    np.asarray(a, dtype=float) for a in (requested, actual_accel, speed, pitch, gas_command))
  filtered_pitch = causal_lpf(pitch, dt, pitch_filter_tau, initial=0.0)
  common = (np.asarray(active_pid, dtype=bool) & ~np.asarray(gas_pressed, dtype=bool) &
            ~np.asarray(brake_pressed, dtype=bool) & ~np.asarray(brake_request, dtype=bool) &
            (gas_command > gas_inactive) & (speed >= speed_min) & (filtered_pitch >= pitch_min) &
            np.isfinite(requested) & np.isfinite(actual_accel) & np.isfinite(filtered_pitch))

  target_t = grid + response_delay_s
  right = np.searchsorted(grid, target_t, side="left")
  aligned = (right > 0) & (right < n)
  safe_right = np.clip(right, 1, n - 1)
  left = safe_right - 1
  local_gap = grid[safe_right] - grid[left]
  aligned &= local_gap > 0.0
  aligned &= local_gap <= 2.5 * dt
  gap_edges = np.diff(grid) > 2.5 * dt
  gap_prefix = np.concatenate(([0], np.cumsum(gap_edges)))
  aligned &= (gap_prefix[safe_right] - gap_prefix[np.arange(n)]) == 0
  future_accel = np.full(n, np.nan)
  valid_idx = np.flatnonzero(aligned)
  if len(valid_idx):
    weight = ((target_t[valid_idx] - grid[left[valid_idx]]) /
              (grid[safe_right[valid_idx]] - grid[left[valid_idx]]))
    future_accel[valid_idx] = (actual_accel[left[valid_idx]] * (1.0 - weight) +
                               actual_accel[safe_right[valid_idx]] * weight)

  gap_before = np.concatenate(([False], gap_edges))
  for name, (lower, upper) in bands.items():
    mask = common & (requested >= lower) & (requested < upper)
    starts = mask & (~np.roll(mask, 1) | gap_before)
    starts[0] = mask[0]
    response_mask = mask & aligned & np.isfinite(future_accel)
    response_error = future_accel[response_mask] - requested[response_mask]
    prefix = f"uphill_negative_{name}_"
    result.update({
      prefix + "sec": float(mask.sum() * dt),
      prefix + "events": int(starts.sum()),
      prefix + "request_median": float(np.median(requested[mask])) if mask.any() else None,
      prefix + "pitch_median": float(np.median(filtered_pitch[mask])) if mask.any() else None,
      prefix + "gas_median": float(np.median(gas_command[mask])) if mask.any() else None,
      prefix + "response_error_mean": float(np.mean(response_error)) if len(response_error) else None,
      prefix + "response_error_median": float(np.median(response_error)) if len(response_error) else None,
      prefix + "response_error_rms": float(np.sqrt(np.mean(response_error ** 2))) if len(response_error) else None,
    })
  return result


def uphill_tracking_bin_metrics(grid, requested, actual_accel, wire_accel, speed, pitch,
                                active, cruise_plan, allow_throttle, has_lead,
                                gas_pressed, brake_pressed, brake_request, gas_command, *,
                                speed_min=10.0, pitch_min=0.04, pitch_max=0.09,
                                min_episode_s=2.0, settle_s=0.5):
  """Expose steady uphill carControl-to-vehicle error in the candidate's two demand bands.

  These are descriptive within-route bins, not a matched-road verdict. Exclude lead following,
  driver pedals, and non-gas domains so a planner or domain change cannot masquerade as gas-map
  response. Drop the start of each qualifying episode to reduce command-edge delay effects.
  """
  names = {"moderate": (0.10, 0.40), "high": (0.80, 1.05)}
  fields = ("sec", "episodes", "request_median", "speed_median", "pitch_median",
            "response_error_median", "response_error_rms", "wire_rms")
  result = {f"uphill_{name}_{field}": 0 if field == "episodes" else (0.0 if field == "sec" else None)
            for name in names for field in fields}
  arrays = (requested, actual_accel, wire_accel, speed, pitch, active, cruise_plan,
            allow_throttle, has_lead, gas_pressed, brake_pressed, brake_request, gas_command)
  n = len(grid)
  if n < 3 or any(len(np.asarray(a)) != n for a in arrays):
    return result
  grid = np.asarray(grid, dtype=float)
  dt = float(np.median(np.diff(grid)))
  if not np.isfinite(dt) or dt <= 0.0:
    return result
  time_gap = ~np.isfinite(np.diff(grid)) | (np.diff(grid) <= 0.0) | (np.diff(grid) > 2.5 * dt)
  requested, actual_accel, wire_accel, speed, pitch, gas_command = (
    np.asarray(a, dtype=float) for a in
    (requested, actual_accel, wire_accel, speed, pitch, gas_command))
  common = (np.asarray(active, dtype=bool) & np.asarray(cruise_plan, dtype=bool) &
            np.asarray(allow_throttle, dtype=bool) & ~np.asarray(has_lead, dtype=bool) &
            ~np.asarray(gas_pressed, dtype=bool) & ~np.asarray(brake_pressed, dtype=bool) &
            ~np.asarray(brake_request, dtype=bool) & (gas_command > 0.0) &
            (speed > speed_min) & (pitch >= pitch_min) & (pitch <= pitch_max) &
            np.isfinite(requested) & np.isfinite(actual_accel) & np.isfinite(wire_accel) &
            np.isfinite(speed) & np.isfinite(pitch))
  for name, (lower, upper) in names.items():
    mask = common & (requested >= lower) & (requested < upper)
    indices = np.flatnonzero(mask)
    if not len(indices):
      continue
    splits = np.flatnonzero((np.diff(indices) > 1) | time_gap[indices[:-1]])
    starts = indices[np.r_[0, splits + 1]]
    ends = indices[np.r_[splits, len(indices) - 1]] + 1
    selected = np.zeros(n, dtype=bool)
    episodes = 0
    for start, end in zip(starts, ends, strict=True):
      if end - start >= round(min_episode_s / dt):
        selected[start + int(round(settle_s / dt)):end] = True
        episodes += 1
    result[f"uphill_{name}_episodes"] = episodes
    if selected.any():
      response_error = actual_accel[selected] - requested[selected]
      wire_error = wire_accel[selected] - requested[selected]
      result.update({
        f"uphill_{name}_sec": float(selected.sum() * dt),
        f"uphill_{name}_request_median": float(np.median(requested[selected])),
        f"uphill_{name}_speed_median": float(np.median(speed[selected])),
        f"uphill_{name}_pitch_median": float(np.median(pitch[selected])),
        f"uphill_{name}_response_error_median": float(np.median(response_error)),
        f"uphill_{name}_response_error_rms": float(np.sqrt(np.mean(response_error ** 2))),
        f"uphill_{name}_wire_rms": float(np.sqrt(np.mean(wire_error ** 2))),
      })
  return result


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


def gas_release_band_metrics(grid, requested, achieved, engaged, vego, pitch, brake_pressed,
                             brake_request, gas_command, *, speed_min, speed_max, request_min,
                             request_max, min_episode_s, gas_inactive):
  """Compare sustained gas and coast response in an active-gas release band.

  The band is diagnostic rather than a calibration rule. Requiring a sustained contiguous domain
  episode keeps one-command-period transport edges from dominating the response comparison.
  """
  keys = (
    "gas_release_band_gas_sec", "gas_release_band_gas_events",
    "gas_release_band_gas_error_mean", "gas_release_band_coast_sec",
    "gas_release_band_coast_events", "gas_release_band_coast_error_mean",
    "gas_release_band_coast_error_median", "gas_release_band_coast_error_rms",
    "gas_release_band_gas_speed_median", "gas_release_band_gas_pitch_median",
    "gas_release_band_coast_speed_median", "gas_release_band_coast_pitch_median",
  )
  empty = dict.fromkeys(keys)
  empty.update({
    "gas_release_band_gas_sec": 0.0,
    "gas_release_band_gas_events": 0,
    "gas_release_band_coast_sec": 0.0,
    "gas_release_band_coast_events": 0,
  })
  arrays = (requested, achieved, engaged, vego, pitch, brake_pressed, brake_request, gas_command)
  if not len(grid) or any(len(np.asarray(value)) != len(grid) for value in arrays):
    return empty

  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  achieved = np.asarray(achieved, dtype=float)
  engaged = np.asarray(engaged, dtype=bool)
  vego = np.asarray(vego, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  brake_request = np.asarray(brake_request, dtype=bool)
  gas_live = np.asarray(gas_command, dtype=float) > gas_inactive
  dt = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  base = (engaged & ~brake_pressed & ~brake_request & np.isfinite(requested) &
          np.isfinite(achieved) & np.isfinite(vego) & np.isfinite(pitch) &
          (vego >= speed_min) & (vego <= speed_max) &
          (requested >= request_min) & (requested <= request_max))

  def sustained(mask):
    transitions = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    keep = np.zeros(len(mask), dtype=bool)
    episodes = 0
    for start, end in zip(starts, ends, strict=True):
      if (end - start) * dt >= min_episode_s:
        keep[start:end] = True
        episodes += 1
    return keep, episodes

  gas, gas_events = sustained(base & gas_live)
  coast, coast_events = sustained(base & ~gas_live)
  gas_error = achieved[gas] - requested[gas]
  coast_error = achieved[coast] - requested[coast]
  return {
    "gas_release_band_gas_sec": float(gas.sum() * dt),
    "gas_release_band_gas_events": gas_events,
    "gas_release_band_gas_error_mean": float(np.mean(gas_error)) if len(gas_error) else None,
    "gas_release_band_coast_sec": float(coast.sum() * dt),
    "gas_release_band_coast_events": coast_events,
    "gas_release_band_coast_error_mean": float(np.mean(coast_error)) if len(coast_error) else None,
    "gas_release_band_coast_error_median": float(np.median(coast_error)) if len(coast_error) else None,
    "gas_release_band_coast_error_rms": (
      float(np.sqrt(np.mean(coast_error ** 2))) if len(coast_error) else None),
    "gas_release_band_gas_speed_median": float(np.median(vego[gas])) if gas.any() else None,
    "gas_release_band_gas_pitch_median": float(np.median(pitch[gas])) if gas.any() else None,
    "gas_release_band_coast_speed_median": float(np.median(vego[coast])) if coast.any() else None,
    "gas_release_band_coast_pitch_median": float(np.median(pitch[coast])) if coast.any() else None,
  }


def under_set_speed_metrics(grid, set_speed, speed, requested, actual_accel, pitch, active,
                            speed_visible, cruise_plan, allow_throttle, has_lead,
                            gas_pressed, brake_pressed, *, speed_min, gap_min, gap_max,
                            request_min, min_episode_s):
  """Describe sustained no-lead cruise below the displayed set speed.

  This is a diagnostic for separating an uphill/load response question from a command-path
  failure. It intentionally selects the upstream ``cruise`` plan with throttle allowed, excludes
  driver pedals, and reports the request and achieved acceleration in the same episodes. It never
  grades a route or authorizes pitch/gas tuning; a matched road comparison is still required.
  """
  arrays = [grid, set_speed, speed, requested, actual_accel, pitch, active, speed_visible,
            cruise_plan, allow_throttle, has_lead, gas_pressed, brake_pressed]
  n = len(grid)
  empty = {
    "under_set_speed_sec": 0.0,
    "under_set_speed_events": 0,
    "under_set_speed_longest": 0.0,
    "under_set_speed_gap_median": None,
    "under_set_speed_request_median": None,
    "under_set_speed_aego_median": None,
    "under_set_speed_response_error_mean": None,
    "under_set_speed_pitch_median": None,
  }
  if n < 3 or any(len(np.asarray(value)) != n for value in arrays[1:]):
    return empty

  grid = np.asarray(grid, dtype=float)
  set_speed = np.asarray(set_speed, dtype=float)
  speed = np.asarray(speed, dtype=float)
  requested = np.asarray(requested, dtype=float)
  actual_accel = np.asarray(actual_accel, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  active = np.asarray(active, dtype=bool)
  speed_visible = np.asarray(speed_visible, dtype=bool)
  cruise_plan = np.asarray(cruise_plan, dtype=bool)
  allow_throttle = np.asarray(allow_throttle, dtype=bool)
  has_lead = np.asarray(has_lead, dtype=bool)
  gas_pressed = np.asarray(gas_pressed, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  dt = float(np.median(np.diff(grid))) if n > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  gap = set_speed - speed
  eligible = (
    active & speed_visible & cruise_plan & allow_throttle & ~has_lead &
    ~gas_pressed & ~brake_pressed & (speed > speed_min) & (set_speed > speed_min) &
    (gap >= gap_min) & (gap <= gap_max) & (requested >= request_min) &
    np.isfinite(set_speed) & np.isfinite(speed) & np.isfinite(requested) &
    np.isfinite(actual_accel) & np.isfinite(pitch)
  )
  edges = np.diff(eligible.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(edges == 1)
  ends = np.flatnonzero(edges == -1)
  durations = (ends - starts) * dt
  qualifying = durations >= min_episode_s
  if not qualifying.any():
    return empty

  selected = np.zeros(n, dtype=bool)
  for start, end in zip(starts[qualifying], ends[qualifying], strict=True):
    selected[start:end] = True
  selected_gap = gap[selected]
  selected_request = requested[selected]
  selected_aego = actual_accel[selected]
  return {
    "under_set_speed_sec": float(selected.sum() * dt),
    "under_set_speed_events": int(np.sum(qualifying)),
    "under_set_speed_longest": float(np.max(durations[qualifying])),
    "under_set_speed_gap_median": float(np.median(selected_gap)),
    "under_set_speed_request_median": float(np.median(selected_request)),
    "under_set_speed_aego_median": float(np.median(selected_aego)),
    "under_set_speed_response_error_mean": float(np.mean(selected_aego - selected_request)),
    "under_set_speed_pitch_median": float(np.median(pitch[selected])),
  }


def level_positive_response_metrics(grid, requested, actual_accel, wire_accel, speed, pitch,
                                    active, cruise_plan, allow_throttle, has_lead,
                                    gas_pressed, brake_pressed, *, speed_min, pitch_abs_max,
                                    request_min, min_episode_s):
  """Describe sustained near-level positive cruise requests and their response.

  This is an exposure readout for a future matched actuator comparison. It deliberately does not
  infer a gas map, grade correction, or a response delay, and it never grades a route. The caller
  must already have held planner booleans and the discrete CAN acceleration onto the native
  ``carControl`` grid; this function only applies the attribution mask and summarizes complete
  episodes.
  """
  arrays = [grid, requested, actual_accel, wire_accel, speed, pitch, active, cruise_plan,
            allow_throttle, has_lead, gas_pressed, brake_pressed]
  n = len(grid)
  empty = {
    "level_positive_sec": 0.0,
    "level_positive_events": 0,
    "level_positive_longest": 0.0,
    "level_positive_request_median": None,
    "level_positive_aego_median": None,
    "level_positive_response_error_mean": None,
    "level_positive_response_error_rms": None,
    "level_positive_wire_rms": None,
    "level_positive_pitch_median": None,
  }
  if n < 3 or any(len(np.asarray(value)) != n for value in arrays[1:]):
    return empty

  grid = np.asarray(grid, dtype=float)
  requested = np.asarray(requested, dtype=float)
  actual_accel = np.asarray(actual_accel, dtype=float)
  wire_accel = np.asarray(wire_accel, dtype=float)
  speed = np.asarray(speed, dtype=float)
  pitch = np.asarray(pitch, dtype=float)
  active = np.asarray(active, dtype=bool)
  cruise_plan = np.asarray(cruise_plan, dtype=bool)
  allow_throttle = np.asarray(allow_throttle, dtype=bool)
  has_lead = np.asarray(has_lead, dtype=bool)
  gas_pressed = np.asarray(gas_pressed, dtype=bool)
  brake_pressed = np.asarray(brake_pressed, dtype=bool)
  dt = float(np.median(np.diff(grid))) if n > 1 else 0.01
  if not np.isfinite(dt) or dt <= 0.0:
    dt = 0.01

  eligible = (
    active & cruise_plan & allow_throttle & ~has_lead & ~gas_pressed & ~brake_pressed &
    (speed > speed_min) & (requested >= request_min) & (np.abs(pitch) <= pitch_abs_max) &
    np.isfinite(requested) & np.isfinite(actual_accel) & np.isfinite(wire_accel) &
    np.isfinite(speed) & np.isfinite(pitch)
  )
  edges = np.diff(eligible.astype(np.int8), prepend=0, append=0)
  starts = np.flatnonzero(edges == 1)
  ends = np.flatnonzero(edges == -1)
  durations = (ends - starts) * dt
  qualifying = durations >= min_episode_s
  if not qualifying.any():
    return empty

  selected = np.zeros(n, dtype=bool)
  for start, end in zip(starts[qualifying], ends[qualifying], strict=True):
    selected[start:end] = True
  response_error = actual_accel[selected] - requested[selected]
  wire_error = wire_accel[selected] - requested[selected]
  return {
    "level_positive_sec": float(selected.sum() * dt),
    "level_positive_events": int(np.sum(qualifying)),
    "level_positive_longest": float(np.max(durations[qualifying])),
    "level_positive_request_median": float(np.median(requested[selected])),
    "level_positive_aego_median": float(np.median(actual_accel[selected])),
    "level_positive_response_error_mean": float(np.mean(response_error)),
    "level_positive_response_error_rms": float(np.sqrt(np.mean(response_error ** 2))),
    "level_positive_wire_rms": float(np.sqrt(np.mean(wire_error ** 2))),
    "level_positive_pitch_median": float(np.median(pitch[selected])),
  }


def cruise_input_metrics(button_times, button_types, button_pressed, set_speed_times,
                         set_speed, *, route_start=None, max_events=256):
  """Summarize cruise inputs that can change the longitudinal command.

  ``carState.buttonEvents`` and the car-control HUD set speed are upstream inputs, not Honda
  actuator behavior. Keeping their route-relative transitions in the ledger prevents a later hill
  trace from being misread as a planner or car-port response when the driver changed the setpoint.
  This function deliberately returns bounded, JSON-friendly summaries and does not infer intent.
  ``set_speed`` is in m/s, matching ``carControl.hudControl.setSpeed``.
  """
  empty = {
    "cruise_button_events": [],
    "cruise_button_press_events": 0,
    "cruise_button_press_counts": {},
    "cruise_set_speed_changes": [],
    "cruise_set_speed_change_events": 0,
    "cruise_set_speed_up_events": 0,
    "cruise_set_speed_down_events": 0,
    "cruise_set_speed_up_max_mps": None,
    "cruise_set_speed_down_max_mps": None,
    "cruise_input_first_rel_s": None,
    "cruise_input_last_rel_s": None,
    "cruise_input_events_truncated": False,
  }
  try:
    button_times = np.asarray(button_times, dtype=float)
    button_pressed = np.asarray(button_pressed, dtype=bool)
    button_types = np.asarray(button_types, dtype=object)
    set_speed_times = np.asarray(set_speed_times, dtype=float)
    set_speed = np.asarray(set_speed, dtype=float)
  except (TypeError, ValueError):
    return empty

  if button_times.ndim != 1 or button_pressed.ndim != 1 or button_types.ndim != 1:
    return empty
  if set_speed_times.ndim != 1 or set_speed.ndim != 1:
    return empty
  if len(button_times) != len(button_pressed) or len(button_times) != len(button_types):
    return empty
  if len(set_speed_times) != len(set_speed):
    return empty

  all_times = []
  if len(button_times):
    all_times.extend(button_times[np.isfinite(button_times)].tolist())
  if len(set_speed_times):
    all_times.extend(set_speed_times[np.isfinite(set_speed_times)].tolist())
  if route_start is None:
    route_start = min(all_times) if all_times else 0.0
  try:
    route_start = float(route_start)
  except (TypeError, ValueError):
    route_start = 0.0
  if not np.isfinite(route_start):
    route_start = 0.0
  max_events = max(0, int(max_events))

  # Preserve both press and release edges. Press-only counts are used for concise route output,
  # while the bounded event list retains enough timing to exclude input-contaminated hill windows.
  button_valid = np.isfinite(button_times)
  button_rows = []
  for t, kind, pressed in zip(button_times[button_valid], button_types[button_valid],
                              button_pressed[button_valid], strict=True):
    button_rows.append({
      "time_s": round(float(t - route_start), 3),
      "type": str(kind),
      "pressed": bool(pressed),
    })
  button_rows.sort(key=lambda row: row["time_s"])
  press_rows = [row for row in button_rows if row["pressed"]]
  counts = {}
  for row in press_rows:
    counts[row["type"]] = counts.get(row["type"], 0) + 1

  # A set-speed sample is a held state. Ignore zero/uninitialized HUD values and collapse repeated
  # samples; a real transition is one adjacent change in the native carControl series.
  speed_valid = (np.isfinite(set_speed_times) & np.isfinite(set_speed) &
                 (set_speed > 1e-3) & (set_speed < CRUISE_SET_SPEED_UNSET_MPS))
  speed_rows = []
  previous = None
  for t, value in zip(set_speed_times[speed_valid], set_speed[speed_valid], strict=True):
    value = float(value)
    if previous is not None and np.isclose(value, previous[1], atol=1e-4, rtol=0.0):
      continue
    if previous is not None:
      delta = value - previous[1]
      speed_rows.append({
        "time_s": round(float(t - route_start), 3),
        "from_mps": round(previous[1], 6),
        "to_mps": round(value, 6),
        "delta_mps": round(delta, 6),
      })
    previous = (float(t), value)

  all_input_times = [row["time_s"] for row in button_rows]
  all_input_times.extend(row["time_s"] for row in speed_rows)
  if all_input_times:
    empty["cruise_input_first_rel_s"] = float(min(all_input_times))
    empty["cruise_input_last_rel_s"] = float(max(all_input_times))
  empty.update({
    "cruise_button_events": button_rows[:max_events],
    "cruise_button_press_events": len(press_rows),
    "cruise_button_press_counts": dict(sorted(counts.items())),
    "cruise_set_speed_changes": speed_rows[:max_events],
    "cruise_set_speed_change_events": len(speed_rows),
    "cruise_set_speed_up_events": sum(row["delta_mps"] > 0.0 for row in speed_rows),
    "cruise_set_speed_down_events": sum(row["delta_mps"] < 0.0 for row in speed_rows),
    "cruise_set_speed_up_max_mps": (
      max((row["delta_mps"] for row in speed_rows if row["delta_mps"] > 0.0), default=None)),
    "cruise_set_speed_down_max_mps": (
      min((row["delta_mps"] for row in speed_rows if row["delta_mps"] < 0.0), default=None)),
    "cruise_input_events_truncated": len(button_rows) > max_events or len(speed_rows) > max_events,
  })
  return empty


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
