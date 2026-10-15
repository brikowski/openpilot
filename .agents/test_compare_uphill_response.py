import numpy as np

from compare_uphill_response import matched_response, uphill_points


def test_uphill_points_require_clean_sustained_gas_and_stable_gear():
  n = 500
  request = np.full(n, 0.9)
  base = {"t": np.arange(n) * 0.01, "request": request,
          "active": np.ones(n, dtype=bool), "pid": np.ones(n, dtype=bool),
          "allow_throttle": np.ones(n, dtype=bool), "has_lead": np.zeros(n, dtype=bool),
          "plan_source": np.zeros(n, dtype=int), "gas_pressed": np.zeros(n, dtype=bool),
          "brake_pressed": np.zeros(n, dtype=bool), "brake_request": np.zeros(n, dtype=bool),
          "gas_command": np.full(n, 500.0), "vego": np.full(n, 20.0),
          "pitch": np.full(n, 0.06), "accel_command": request.copy(),
          "gear": np.full(n, 5.0), "aego": request + 0.1}
  points, episodes = uphill_points(base, "high")
  assert episodes == 1 and len(points) == 45
  assert np.allclose(points[:, 4], 0.1)

  lead = {**base, "has_lead": np.ones(n, dtype=bool)}
  assert uphill_points(lead, "high")[1] == 0
  shifted = {**base, "gear": np.r_[np.full(250, 5.0), np.full(250, 4.0)]}
  assert uphill_points(shifted, "high")[1] == 0


def test_uphill_match_requires_all_features_and_same_gear():
  candidate = np.array([[20.0, 0.9, 0.06, 5.0, 0.10],
                        [30.0, 0.9, 0.06, 5.0, -0.20]])
  baseline = np.array([[20.1, 0.91, 0.061, 5.0, -0.05],
                       [30.0, 0.9, 0.06, 4.0, -0.20]])
  result = matched_response(candidate, baseline)
  assert result["matched"] == 1
  assert result["unique_baseline"] == 1
  assert np.isclose(result["candidate_mae"], 0.10)
  assert np.isclose(result["baseline_mae"], 0.05)
  assert np.isclose(result["paired_median_delta"], 0.15)
