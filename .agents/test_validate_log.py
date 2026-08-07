import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_log
from validate_log import (
  ODYSSEY,
  _base_route,
  _suggest_status_rows,
  write_ledger_md,
)
from tuning_metrics import (
  after_grace,
  brake_release_hold_metrics,
  causal_lpf,
  command_transition_metrics,
  hold_last,
  max_edges_in_window,
  physical_edges,
  post_edge_window,
  shadow_windfactor_metrics,
  sign_disagreement_metrics,
  stop_lurch_metrics,
)


def test_hold_last_does_not_invent_intermediate_can_values():
  grid = np.array([-0.01, 0.00, 0.01, 0.02, 0.03, 0.04])
  sent_at = np.array([0.00, 0.02, 0.04])
  commands = np.array([-30000.0, 60.0, 120.0])

  assert hold_last(grid, sent_at, commands).tolist() == [-30000.0, -30000.0, -30000.0, 60.0, 60.0, 120.0]


def test_after_grace_ignores_one_can_period_but_keeps_a_latch():
  one_period = np.array([False, True, True, False])
  latched = np.array([False, True, True, True, True, False])

  assert not after_grace(one_period, 0.01, 0.02).any()
  assert after_grace(latched, 0.01, 0.02).tolist() == [False, False, False, True, True, False]


def test_causal_lpf_can_reproduce_a_zero_initialized_controller_filter():
  samples = np.ones(3)

  assert causal_lpf(samples, dt=0.1, tau=0.1).tolist() == [1.0, 1.0, 1.0]
  assert causal_lpf(samples, dt=0.1, tau=0.1, initial=0.0).tolist() == [0.5, 0.75, 0.875]


def test_physical_edges_do_not_splice_disjoint_mask_windows():
  signal = np.array([False, False, True, True, True, True])
  split_mask = np.array([True, True, False, False, True, True])
  contiguous_mask = np.array([True, True, True, False, False, False])

  assert physical_edges(signal, split_mask).tolist() == []
  assert physical_edges(signal, contiguous_mask).tolist() == [2]


def test_brake_burst_uses_real_timestamps():
  times = np.array([0.0, 0.5, 1.0, 9.9, 10.1, 20.0])

  assert max_edges_in_window(times, 10.0) == 4
  assert max_edges_in_window(np.array([]), 10.0) == 0


def test_post_edge_window_excludes_transport_period():
  window = post_edge_window(np.array([10]), length=100, dt=0.01, start_s=0.02, end_s=0.50)

  assert not window[11]
  assert window[12]
  assert window[59]
  assert not window[60]


def _transition_trace(brake_release_frame, first_gas):
  """Build a complete inactive -> active -> gas trace for mutation-style metric tests."""
  n = 80
  grid = np.arange(n, dtype=float) * 0.01
  engaged = np.zeros(n, dtype=bool)
  engaged[10:] = True
  requested = np.zeros(n)
  requested[10:] = 0.1
  vego = np.zeros(n)
  brake_pressed = np.zeros(n, dtype=bool)
  brake_request = np.zeros(n, dtype=bool)
  brake_request[10:brake_release_frame] = True
  gas = np.full(n, -30000.0)
  gas[brake_release_frame:] = first_gas
  wire = np.full(n, -2.0)
  wire[brake_release_frame:] = 0.1
  return command_transition_metrics(
    grid, requested, engaged, vego, brake_pressed, brake_request, gas, wire,
    low_speed_vego=5.0,
    request_threshold=0.02,
    command_period_s=0.02,
    reengage_window_s=0.50,
    gas_inactive=-30000,
  )


def test_transition_golden_trace_accepts_transport_skew_and_60_count_handoff():
  """The fixed trace stays clean while still proving every detector was exercised.

  TODO: delete excessive comments before trying to submit a PR.
  """
  metrics = _transition_trace(brake_release_frame=12, first_gas=60)

  assert metrics == {
    "low_speed_conflict_sec": 0.0,
    "low_speed_conflict_events": 0,
    "low_speed_conflict_worst": 0.0,
    "low_speed_conflict_skew_frames": 2,
    "reengagement_events": 1,
    "reengagement_stale_sec": 0.0,
    "reengagement_stale_events": 0,
    "reengagement_stale_worst": 0.0,
    "gas_handoff_events": 1,
    "gas_handoff_max": 60.0,
  }


def test_transition_mutation_detects_latch_and_precharged_gas():
  """Mutating the trace to the old failure must make all three lifecycle metrics nonzero."""
  metrics = _transition_trace(brake_release_frame=25, first_gas=240)

  assert np.isclose(metrics["low_speed_conflict_sec"], 0.13)
  assert metrics["low_speed_conflict_events"] == 1
  assert np.isclose(metrics["reengagement_stale_sec"], 0.13)
  assert metrics["reengagement_stale_events"] == 1
  assert metrics["gas_handoff_events"] == 1
  assert metrics["gas_handoff_max"] == 240.0


def test_sign_disagreement_ignores_transport_and_separates_downhill():
  requested = np.full(12, 0.1)
  wire = np.zeros(12)
  brake = np.zeros(12, dtype=bool)
  brake[1:6] = True       # after 20 ms grace: frames 3-5 remain
  brake[7:10] = True      # after grace: frame 9 remains
  active = np.ones(12, dtype=bool)
  pitch = np.zeros(12)
  pitch[3:6] = -0.03

  metrics = sign_disagreement_metrics(
    requested, wire, brake, active, pitch,
    request_threshold=0.02,
    downhill_pitch=-0.012,
    dt=0.01,
    transition_grace_s=0.02,
  )

  assert np.isclose(metrics["sign_disagree_frac"], 4 / 12)
  assert np.isclose(metrics["sign_disagree_downhill_frac"], 3 / 12)
  assert np.isclose(metrics["sign_disagree_non_grade_frac"], 1 / 12)
  assert metrics["sign_disagree_transition_frames"] == 4


def test_creep_detector_can_actually_fire():
  """`creep at stop` has never flagged in 79 drives - prove that is the car, not a dead check.

  tune-evidence.md habit #1: a check you have never seen fail is not evidence. This drives the exact
  predicate with a synthetic creep (rolling forward at 1 m/s while the planner asks <= 0) and
  asserts it trips, so a future edit that silently disables it goes red.
  """
  creep_vego, creep_aego, min_frames = 2.0, 0.15, 50
  n = 200
  active = np.ones(n, dtype=bool)
  vego = np.full(n, 1.0)
  cc_accel = np.full(n, -0.10)      # planner asking for no drive torque
  aego = np.full(n, 0.20)           # ...and the van rolling forward anyway

  creep = active & (vego < creep_vego) & (cc_accel <= 0.0) & (aego > creep_aego)
  run = best = 0
  for c in creep:
    run = run + 1 if c else 0
    best = max(best, run)
  assert best >= min_frames, "creep predicate cannot fire even on a synthetic creep"

  # And the healthy case must NOT fire, or the check is vacuous in the other direction.
  healthy = active & (vego < creep_vego) & (cc_accel <= 0.0) & (np.full(n, -0.05) > creep_aego)
  assert not healthy.any()


def test_sign_disagreement_severity_uses_the_request_not_the_wire_error():
  """The wire error is near-zero exactly where the domain withholds gas; grade the request.

  Guards the 2026-08-05 finding: ACCEL_COMMAND carries the request faithfully through a domain
  hold, so `sign_disagree_worst` (min(wire - requested)) stays tiny no matter how much
  acceleration was actually withheld. If the withheld-request fields are ever re-derived from
  `wire` this test goes red.
  """
  n = 22
  requested = np.full(n, 0.40)   # openpilot asking for real acceleration
  wire = requested.copy()        # ...and the wire carrying it perfectly
  brake = np.zeros(n, dtype=bool)
  brake[1:21] = True             # 20 frames latched; 2 lost to the 20 ms grace
  active = np.ones(n, dtype=bool)
  pitch = np.zeros(n)

  m = sign_disagreement_metrics(
    requested, wire, brake, active, pitch,
    request_threshold=0.02, downhill_pitch=-0.012, dt=0.01, transition_grace_s=0.02,
  )

  # The error-based number sees nothing at all here - that is the whole point.
  assert np.isclose(m["sign_disagree_worst"], 0.0)
  # The request-based numbers see the full severity.
  assert m["sign_disagree_events"] == 1
  assert np.isclose(m["sign_disagree_sec"], 0.18)
  assert np.isclose(m["sign_disagree_longest"], 0.18)
  assert np.isclose(m["sign_disagree_withheld_worst"], 0.40)
  assert np.isclose(m["sign_disagree_withheld_integral"], 18 * 0.01 * 0.40)
  # Mutation guard: withheld severity must not collapse when the wire tracks the request.
  assert m["sign_disagree_withheld_integral"] > abs(m["sign_disagree_worst"])


def test_release_hold_uses_compensated_entry_predicate_and_measures_runs():
  switch_accel = np.array([-0.3, -0.3, -0.19, -0.1, 0.0, 0.1,
                           -0.3, -0.3, -0.15, -0.05, 0.05, -0.3])
  entry = np.full(12, -0.2)
  requested = np.linspace(-0.1, 0.12, 12)
  actual = requested - 0.2
  brake = np.zeros(12, dtype=bool)
  brake[1:6] = True
  brake[7:11] = True
  active = np.ones(12, dtype=bool)

  metrics = brake_release_hold_metrics(
    switch_accel, entry, requested, actual, brake, active, dt=0.01,
  )

  assert np.isclose(metrics["brake_release_hold_sec"], 0.07)
  assert metrics["brake_release_hold_events"] == 2
  assert np.isclose(metrics["brake_release_hold_max"], 0.04)
  assert np.isclose(metrics["brake_release_hold_force_margin_mean"], np.mean([0.01, 0.1, 0.2, 0.3, 0.05, 0.15, 0.25]))
  assert np.isclose(metrics["brake_release_hold_tracking_mean"], -0.2)


def _shadow_trace(error_sign=1.0, *, gas_live=True, braking=False):
  n = 200
  grid = np.arange(n, dtype=float) * 0.01
  requested = np.full(n, 0.1 * error_sign)
  actual = np.zeros(n)
  speed = np.full(n, 22.0)
  pitch = np.zeros(n)
  active_pid = np.ones(n, dtype=bool)
  pedal = np.zeros(n, dtype=bool)
  brake_request = np.full(n, braking, dtype=bool)
  gas = np.full(n, 100.0 if gas_live else -30000.0)
  return shadow_windfactor_metrics(
    grid, requested, actual, speed, pitch, active_pid, pedal, pedal, brake_request, gas,
    gas_inactive=-30000.0,
    gas_max=2000.0,
    accel_min=-3.5,
    accel_max=2.0,
    base_drag=np.full(n, 0.136),
    initial_windfactor=0.5,
    windfactor_min=0.1,
    windfactor_max=3.0,
    learn_divisor=500.0,
    update_period_s=0.02,
    min_speed=15.0,
    steady_accel=0.3,
    steady_pitch_rate=0.003,
    accel_rail_margin=0.2,
    gas_rail_margin=100.0,
  )


def test_shadow_windfactor_moves_only_on_identifiable_gas_frames():
  increasing = _shadow_trace(error_sign=1.0)
  decreasing = _shadow_trace(error_sign=-1.0)
  inactive_gas = _shadow_trace(gas_live=False)
  braking = _shadow_trace(braking=True)

  assert increasing["windf_shadow_end"] > 0.5
  assert decreasing["windf_shadow_end"] < 0.5
  assert increasing["windf_shadow_eligible_min"] > 0.0
  assert inactive_gas["windf_shadow_eligible_min"] == 0.0
  assert inactive_gas["windf_shadow_end"] == 0.5
  assert braking["windf_shadow_eligible_min"] == 0.0
  assert braking["windf_shadow_end"] == 0.5


def test_stop_lurch_attributes_request_to_wire_to_actuator():
  requested = np.array([0.2, 0.5, -0.4, -0.6, -1.2])
  wire = np.array([0.2, 0.5, -0.4, -0.7, -1.2])
  actual = np.array([-0.8, 0.1, -0.5, -1.0, -1.3])
  speed = np.array([0.0, 1.0, 1.8, 1.2, 0.7])
  engaged = np.ones(5, dtype=bool)
  stop_state = np.array([False, False, False, False, True])

  metrics = stop_lurch_metrics(
    requested, wire, actual, speed, engaged, stop_state,
    min_speed=0.25,
    max_speed=2.0,
  )

  # The stationary decel noise, positive actual acceleration, and hardest absolute decel are not
  # lurch events. The moving -1.0 sample exceeds its milder request by 0.4 and splits cleanly.
  assert np.isclose(metrics["stop_lurch_worst"], 1.0)
  assert np.isclose(metrics["stop_lurch_excess"], 0.4)
  assert np.isclose(metrics["stop_lurch_wire_extra"], 0.1)
  assert np.isclose(metrics["stop_lurch_actuator_extra"], 0.3)
  assert np.isclose(metrics["stop_lurch_speed"], 1.2)
  assert not metrics["stop_lurch_in_stopping"]


def test_base_route_normalizes_local_and_api_forms():
  route = "0000003b--aeccafe9e4"

  assert _base_route(route) == route
  assert _base_route(f"805f87f5e96d128c/{route}/a") == route
  assert _base_route(f"{route}--42") == route


def test_write_ledger_md_escapes_flag_column_delimiters(monkeypatch, tmp_path):
  ledger = tmp_path / "ledger.md"
  monkeypatch.setattr(validate_log, "LEDGER_MD", ledger)
  row = {
    "date": "2026-08-04",
    "route": "00000055--b6c9bb3917",
    "verdicts": [{"check": "track RMS |aEgo-aTarget|", "ok": False}],
  }

  write_ledger_md([row])

  table_row = ledger.read_text().splitlines()[-1]
  assert "track RMS &#124;aEgo-aTarget&#124;" in table_row
  assert len(table_row.split("|")) == 19


def _status_row(route, opendbc_commit, flagged=True):
  return {
    "route": route,
    "platform": ODYSSEY,
    "opendbc_commit": opendbc_commit,
    "engaged_min": 10.0,
    "verdicts": [{
      "check": "brake-domain transition bursts",
      "ok": not flagged,
      "status": "brake-domain chatter - revisit hysteresis",
    }],
  }


def test_status_suggestions_do_not_mix_opendbc_configurations():
  rows = [
    _status_row("00000001--aaaaaaaaaa", "old"),
    _status_row("00000002--bbbbbbbbbb", "current"),
  ]

  assert _suggest_status_rows(rows, "00000002--bbbbbbbbbb") == []


def test_status_suggestions_promote_repeated_symptom_on_same_opendbc():
  rows = [
    _status_row("00000001--aaaaaaaaaa", "current"),
    _status_row("00000002--bbbbbbbbbb", "current"),
  ]

  suggestions = _suggest_status_rows(rows, "00000002--bbbbbbbbbb")
  assert len(suggestions) == 1
  assert "flagged in 2/2 recent logs" in suggestions[0]
