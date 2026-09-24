import numpy as np
import pytest

from inspect_response import brake_entry_summary, print_brake_entry_summary
from tuning_metrics import brake_entry_tracking_profile, response_jerk_events


def test_brake_entry_tracking_profile_captures_early_lag_and_late_overresponse():
  t = np.arange(0.0, 3.0, 0.01)
  brake = t >= 1.0
  wire = np.where(brake, -0.3, -0.1)
  actual = np.where(brake, np.interp(t - 1.0, [0.0, 0.5, 1.0], [0.0, -0.1, -0.5]), 0.0)
  gas = np.full_like(t, -30000.0)
  clean = np.ones_like(t, dtype=bool)
  speed = np.full_like(t, 20.0)
  gear = np.full_like(t, 6.0)

  rows = brake_entry_tracking_profile(t, actual, wire, brake, gas, clean, speed, gear, filter_tau=0.0)
  assert len(rows) == 1
  assert rows[0]["time"] == pytest.approx(1.0)
  assert rows[0]["speed"] == pytest.approx(20.0)
  assert rows[0]["wire_at_half"] == pytest.approx(-0.3)
  assert rows[0]["errors"][0] > 0.20
  assert rows[0]["errors"][1] > 0.15
  assert rows[0]["errors"][2] < 0.0
  assert rows[0]["errors"][3] < -0.15

  gas[99] = -60.0
  assert not brake_entry_tracking_profile(t, actual, wire, brake, gas, clean, speed, gear, filter_tau=0.0)
  gas[99] = -30000.0
  gear[150] = 5.0
  assert not brake_entry_tracking_profile(t, actual, wire, brake, gas, clean, speed, gear, filter_tau=0.0)


def test_response_jerk_event_preserves_first_divergence_and_domain_context():
  t = np.arange(0.0, 8.0, 0.01)
  requested = np.zeros_like(t)
  command_ramp = (t >= 2.0) & (t < 2.5)
  requested[command_ramp] = -0.8 * (t[command_ramp] - 2.0)
  requested[t >= 2.5] = -0.4
  actual = np.zeros_like(t)
  response_ramp = (t >= 2.6) & (t < 2.9)
  actual[response_ramp] = -2.0 * (t[response_ramp] - 2.6)
  actual[t >= 2.9] = -0.6
  brake = t >= 2.0
  computer_braking = t >= 2.08
  gas = np.where(brake, -30000.0, 100.0)

  rows = response_jerk_events(
    t, requested, requested, requested, actual, np.ones_like(t, dtype=bool), brake,
    computer_braking, gas,
    np.full_like(t, 20.0), np.zeros_like(t), np.zeros_like(t, dtype=bool),
    np.zeros_like(t, dtype=int), np.full_like(t, 6.0), np.full_like(t, -100.0),
    np.full_like(t, 1800.0), gas_inactive=-30000, threshold=0.5, limit=1,
  )

  assert len(rows) == 1
  event = rows[0]
  assert event["domain"] == "brake"
  assert event["domain_from"] == "gas"
  assert 0.5 < event["domain_edge_age"] < 1.2
  assert event["domain_edges_in_history"] == 1
  assert event["computer_braking_before_entry"] is False
  assert event["computer_braking_at_peak"] is True
  assert event["request_to_computer_brake_s"] == pytest.approx(0.08)
  assert event["computer_brake_to_peak_s"] == pytest.approx(
    event["domain_edge_age"] - event["request_to_computer_brake_s"])
  assert event["response_jerk"] < -1.0
  assert event["command_jerk_peak"] < -0.5
  assert event["amplification"] > 1.5
  assert event["plan_request_rms"] == 0.0
  assert event["request_wire_rms"] == 0.0
  assert event["gear_edges_in_history"] == 0
  assert event["gear"] == 6.0

  summary = brake_entry_summary(rows, max_edge_age=1.0)
  assert summary == {
    "count": 1,
    "edge_age_min": event["domain_edge_age"],
    "edge_age_max": event["domain_edge_age"],
    "response_jerk_median": event["response_jerk"],
    "command_jerk_abs_median": abs(event["command_jerk_peak"]),
    "amplification_median": event["amplification"],
    "jerk_magnitude_correlation": None,
    "domain_from_counts": {"gas": 1, "coast": 0, "brake": 0},
    "computer_brake_edges": 1,
    "computer_braking_at_peak": 1,
    "computer_braking_peak_samples": 1,
    "request_to_computer_brake_median": event["request_to_computer_brake_s"],
    "computer_brake_to_peak_median": event["computer_brake_to_peak_s"],
    "without_gear_edge": 1,
    "plan_request_rms_max": 0.0,
    "request_wire_rms_max": 0.0,
  }


def test_brake_entry_summary_uses_every_qualifying_event():
  base = {
    "domain": "brake",
    "domain_edge_age": 0.5,
    "gear_edges_in_history": 0,
    "plan_request_rms": 0.01,
    "request_wire_rms": 0.02,
    "domain_from": "coast",
    "computer_braking_at_peak": True,
    "request_to_computer_brake_s": 0.06,
    "computer_brake_to_peak_s": 0.44,
  }
  rows = [
    {**base, "response_jerk": -1.0, "command_jerk_peak": -0.5, "amplification": 2.0},
    {**base, "domain_edge_age": 0.6, "gear_edges_in_history": 1,
     "plan_request_rms": 0.03, "request_wire_rms": 0.04,
     "response_jerk": -2.0, "command_jerk_peak": -1.0, "amplification": 2.0},
    {**base, "response_jerk": +3.0, "command_jerk_peak": +1.0, "amplification": 3.0},
    {**base, "domain_edge_age": 0.8,
     "response_jerk": -4.0, "command_jerk_peak": -2.0, "amplification": 2.0},
  ]

  assert brake_entry_summary(rows) == {
    "count": 2,
    "edge_age_min": 0.5,
    "edge_age_max": 0.6,
    "response_jerk_median": -1.5,
    "command_jerk_abs_median": 0.75,
    "amplification_median": 2.0,
    "jerk_magnitude_correlation": pytest.approx(1.0),
    "domain_from_counts": {"gas": 0, "coast": 2, "brake": 0},
    "computer_brake_edges": 2,
    "computer_braking_at_peak": 2,
    "computer_braking_peak_samples": 2,
    "request_to_computer_brake_median": 0.06,
    "computer_brake_to_peak_median": 0.44,
    "without_gear_edge": 1,
    "plan_request_rms_max": 0.03,
    "request_wire_rms_max": 0.04,
  }


def test_brake_entry_summary_keeps_missing_computer_brake_state_explicit(capsys):
  rows = [{
    "domain": "brake",
    "domain_edge_age": 0.5,
    "gear_edges_in_history": 0,
    "plan_request_rms": 0.01,
    "request_wire_rms": 0.02,
    "domain_from": "coast",
    "computer_braking_at_peak": None,
    "request_to_computer_brake_s": None,
    "computer_brake_to_peak_s": None,
    "response_jerk": -1.0,
    "command_jerk_peak": -0.5,
    "amplification": 2.0,
  }]

  summary = brake_entry_summary(rows)
  assert summary["computer_brake_edges"] == 0
  assert summary["computer_braking_peak_samples"] == 0
  assert summary["request_to_computer_brake_median"] is None
  assert summary["computer_brake_to_peak_median"] is None
  print_brake_entry_summary(rows)
  assert "request->state median n/a, state->peak median n/a" in capsys.readouterr().out
