import numpy as np

from extract import plan_to_control, select_lead_field


def test_plan_to_control_holds_published_target_until_next_plan():
  grid = np.array([0.01, 0.02, 0.03, 0.04])
  plan_t = np.array([0.00, 0.03])
  a_target = np.array([-0.40, 0.80])

  np.testing.assert_array_equal(plan_to_control(grid, plan_t, a_target), [-0.40, -0.40, 0.80, 0.80])


def test_select_lead_field_follows_published_mpc_source():
  source = np.array([1, 2, 0, 4, 2])
  lead_one = np.array([10., 11., 12., 13., 14.])
  lead_two = np.array([20., 21., 22., 23., 24.])

  selected = select_lead_field(source, lead_one, lead_two)

  np.testing.assert_array_equal(selected[:2], [10., 21.])
  assert np.isnan(selected[2])
  assert np.isnan(selected[3])
  assert selected[4] == 24.


def test_select_lead_field_does_not_substitute_lead_one_for_non_lead_plan():
  selected = select_lead_field(np.array([0]), np.array([10.]), np.array([20.]))

  assert np.isnan(selected[0])
