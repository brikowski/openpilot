import unittest

import numpy as np

from compare_lateral_response import lateral_points, matched_lateral


class TestLateralResponseMatch(unittest.TestCase):
  def test_match_requires_overlap_in_each_feature(self):
    baseline = np.array([[22.0, 1.8, 0.04, 0.0, 0.1]])
    candidate = np.array([
      [22.1, 1.9, 0.045, 0.1, 0.2],
      [22.1, -1.9, 0.045, 0.1, 0.2],  # opposite turn direction
      [22.1, 1.9, 0.06, 0.1, 0.2],  # different grade
    ])
    result = matched_lateral(candidate, baseline)
    self.assertEqual(result["matched"], 1)
    self.assertEqual(result["unique_baseline"], 1)
    self.assertAlmostEqual(result["candidate_mae"], 0.2)
    self.assertAlmostEqual(result["baseline_mae"], 0.1)

  def test_filter_uses_signed_tracking_error_and_can_authority(self):
    n = 5
    d = {
      "t": np.arange(n) * 0.1,
      "desired_lat_accel": np.full(n, -1.0),
      "actual_lat_accel": np.full(n, -0.8),
      "lat_active": np.ones(n, dtype=bool),
      "lat_state_active": np.ones(n, dtype=bool),
      "steering_pressed": np.zeros(n, dtype=bool),
      "steer_fault_temp": np.zeros(n, dtype=bool),
      "steer_fault_perm": np.zeros(n, dtype=bool),
      "vego": np.full(n, 22.0),
      "pitch": np.full(n, 0.04),
      "lat_output_torque_can": np.array([-2560, -2560, -1000, -2560, -2560]),
    }
    points = lateral_points(d, stride=1)
    self.assertEqual(len(points), 4)
    np.testing.assert_allclose(points[:, 4], 0.2)


if __name__ == "__main__":
  unittest.main()
