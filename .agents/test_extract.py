import numpy as np

from extract import select_lead_field


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
