import numpy as np
import pytest

from inspect_response import brake_entry_summary
from tuning_metrics import response_jerk_events


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
  gas = np.where(brake, -30000.0, 100.0)

  rows = response_jerk_events(
    t, requested, requested, requested, actual, np.ones_like(t, dtype=bool), brake, gas,
    np.full_like(t, 20.0), np.zeros_like(t), np.zeros_like(t, dtype=bool),
    np.zeros_like(t, dtype=int), np.full_like(t, 6.0), np.full_like(t, -100.0),
    np.full_like(t, 1800.0), gas_inactive=-30000, threshold=0.5, limit=1,
  )

  assert len(rows) == 1
  event = rows[0]
  assert event["domain"] == "brake"
  assert 0.5 < event["domain_edge_age"] < 1.2
  assert event["domain_edges_in_history"] == 1
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
    "without_gear_edge": 1,
    "plan_request_rms_max": 0.03,
    "request_wire_rms_max": 0.04,
  }
