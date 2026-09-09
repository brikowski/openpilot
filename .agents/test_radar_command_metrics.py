import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from radar_command_metrics import (
  binned_summary,
  command_domain,
  cross_route_regression,
  feature_matrix,
  regression_metrics,
  transition_metrics,
)


def test_command_domain_uses_control_on_for_openpilot_and_brake_wins():
  domain = command_domain(
    [0, 0, 1, 1], [0, 0, 0, 1], [-30000, 20, 20, 20], control_on=[0, 5, 0, 5])
  assert domain.tolist() == ["inactive", "gas", "gas", "brake"]


def test_transition_metrics_counts_interlock_and_does_not_bridge_gap():
  times = np.array([0.00, 0.02, 0.04, 0.06, 1.00, 1.02])
  domains = np.array(["gas", "coast", "coast", "brake", "gas", "gas"])
  gas = np.array([100, -30000, -30000, -30000, 200, 220])
  result = transition_metrics(times, domains, gas)
  assert result["direct_gas_to_brake"] == 0
  assert result["direct_brake_to_gas"] == 0
  assert result["gas_to_coast_to_brake"] == 1
  assert result["gap_count"] == 1
  assert result["first_live_gas"] == []


def test_route_held_out_model_does_not_need_route_identity():
  speed = np.linspace(5.0, 35.0, 100)
  accel = np.sin(speed / 6.0)
  pitch = np.cos(speed / 9.0) * 0.02
  features = feature_matrix(speed, accel, pitch)
  coefficients = np.array([10.0, 2.0, -0.1, 80.0, 0.5, 3.0, -1.0])
  target = features @ coefficients
  routes = [
    {"name": "route-a", "features": features[:50], "target": target[:50]},
    {"name": "route-b", "features": features[50:], "target": target[50:]},
  ]
  reports = cross_route_regression(routes)
  assert len(reports) == 2
  assert all(report["metrics"]["mae"] < 1e-8 for report in reports)


def test_binned_summary_reports_only_exposed_cells():
  speed = np.repeat([5.0, 15.0], 3)
  accel = np.repeat([0.05, 0.25], 3)
  gas = np.array([10.0, 20.0, 30.0, 100.0, 120.0, 140.0])
  rows = binned_summary(speed, accel, gas, [3.0, 8.0, 18.0], [0.0, 0.1, 0.4], min_count=3)
  assert len(rows) == 2
  assert rows[0]["median"] == 20.0
  assert rows[1]["median"] == 120.0


def test_regression_metrics_exposes_low_command_error_separately():
  metrics = regression_metrics(np.array([10.0, 20.0, 1000.0]), np.array([20.0, 20.0, 1100.0]))
  assert metrics["n"] == 3
  assert metrics["low_command_n"] == 2
  assert metrics["low_command_mae"] == 5.0
