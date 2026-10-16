import pytest

import openpilot.cereal.messaging as messaging
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.realtime import DT_MDL
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_planner import (A_CRUISE_MAX_BP, J_CRUISE_VALS, LongitudinalPlanner,
                                                                  LongitudinalPlanSource, get_cruise_accel, get_max_accel)


@pytest.mark.parametrize("experimental", [False, True])
@pytest.mark.parametrize("eco", [False, True])
@pytest.mark.parametrize("speed", [10., 25., 35.])
def test_cruise_speed_reduction_remains_gentle_and_request_sensitive(experimental, eco, speed):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = 0.
  for speed_error, expected in [(-5., -.5), (-.2, -.2), (0., 0.)]:
    for _ in range(100):
      previous = accel
      accel = get_cruise_accel(experimental, speed + speed_error, speed, accel, 0., cp, DT_MDL, 0., True, eco=eco)
      assert abs(accel - previous) <= 1.6 * DT_MDL + 1e-9
      assert accel >= -.5 - 1e-9
    assert accel == pytest.approx(expected)


def planner_inputs(experimental, eco=False):
  sm = {name: getattr(messaging.new_message(name), name)
        for name in ("carState", "carControl", "controlsState", "selfdriveState", "vehicleParameters", "radarState", "modelV2")}
  sm["carState"].vEgo = 25.
  sm["carState"].vCruise = 20. * 3.6
  sm["carControl"].orientationNED = [0., 0., 0.]
  sm["controlsState"].longControlState = LongCtrlState.pid
  sm["selfdriveState"].enabled = True
  sm["selfdriveState"].experimentalMode = experimental
  sm["selfdriveState"].ecoMode = eco
  sm["selfdriveState"].personality = 1
  sm["modelV2"].action.desiredAcceleration = 1.
  sm["modelV2"].meta.disengagePredictions.gasPressProbs = [1., 1.]
  return sm


@pytest.mark.parametrize("experimental", [False, True])
@pytest.mark.parametrize("eco", [False, True])
def test_lead_braking_can_exceed_cruise_deceleration(experimental, eco):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(experimental, eco)
  sm["radarState"].leadOne.present = True
  sm["radarState"].leadOne.dRel = 60.
  sm["radarState"].leadOne.vLead = 0.
  sm["radarState"].leadOne.aLeadTau = 1.5
  for _ in range(20):
    planner.update(sm)
  assert planner.output_a_target < -1.
  assert planner.mpc.source in (LongitudinalPlanSource.lead0, LongitudinalPlanSource.lead1)


@pytest.mark.parametrize("eco", [False, True])
def test_experimental_model_braking_can_exceed_cruise_deceleration(eco):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(True, eco)
  sm["modelV2"].action.desiredAcceleration = -2.
  planner.update(sm)
  assert planner.output_a_target == pytest.approx(-2.)
  assert planner.mpc.source == LongitudinalPlanSource.e2e


@pytest.mark.parametrize("eco", [False, True])
def test_disallowed_throttle_retains_coast_deceleration(eco):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = get_cruise_accel(False, 20., 25., -.8, 0., cp, DT_MDL, -.8, False, eco=eco)
  assert accel == pytest.approx(-.8)


@pytest.mark.parametrize("speed", [0., 10., 25., 40.])
def test_eco_speed_recovery_uses_existing_cruise_envelope(speed):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = 0.
  for _ in range(100):
    accel = get_cruise_accel(True, speed + 10., speed, accel, 0., cp, DT_MDL, 0., True, eco=True)
  assert accel == pytest.approx(get_max_accel(speed))


def test_eco_toggle_preserves_acceleration_slew_and_restores_normal_recovery():
  import numpy as np

  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = 0.
  jerk = np.interp(25., A_CRUISE_MAX_BP, J_CRUISE_VALS)
  for eco, expected in ((False, 2.), (True, .8), (False, 2.)):
    for _ in range(100):
      previous = accel
      accel = get_cruise_accel(True, 35., 25., accel, 0., cp, DT_MDL, 0., True, eco=eco)
      assert abs(accel - previous) <= jerk * DT_MDL + 1e-9
    assert accel == pytest.approx(expected)


@pytest.mark.parametrize("eco", [False, True])
def test_planner_speed_recovery_respects_selected_mode(eco):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(True, eco)
  sm['carState'].vCruise = 35. * 3.6
  sm['modelV2'].action.desiredAcceleration = 3.
  for _ in range(100):
    planner.update(sm)
  assert planner.output_a_target == pytest.approx(.8 if eco else 2.)


@pytest.mark.parametrize("eco", [False, True])
def test_eco_retains_model_stop_request_when_acceleration_is_positive(eco):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(True, eco)
  sm['carState'].vCruise = 35. * 3.6
  sm['modelV2'].action.shouldStop = True
  planner.update(sm)
  assert planner.output_should_stop


class TestEcoManeuvers(OpenpilotTestCase):
  def test_speed_recovery_converges_without_changing_following_distance(self):
    from openpilot.selfdrive.test.longitudinal_maneuvers.maneuver import Maneuver

    endpoints = []
    for eco in (False, True):
      valid, output = Maneuver('speed recovery', duration=100., initial_speed=20., initial_distance_lead=80.,
                               lead_relevancy=True, speed_lead_values=[25.], breakpoints=[0.],
                               cruise_values=[30.], e2e=True, personality=1, eco=eco).evaluate()
      self.assertTrue(valid)
      self.assertAlmostEqual(output[-1, 3], 25., delta=.1)
      endpoints.append(output[-1, 6])
    self.assertAlmostEqual(*endpoints, delta=.1)

  def test_stopped_lead_remains_reachable_in_both_modes(self):
    from openpilot.selfdrive.test.longitudinal_maneuvers.maneuver import Maneuver

    for eco in (False, True):
      valid, output = Maneuver('lead stop', duration=50., initial_speed=25., initial_distance_lead=60.,
                               lead_relevancy=True, speed_lead_values=[25., 25., 0., 0.],
                               breakpoints=[0., 3., 10., 50.], cruise_values=[30., 30., 30., 30.],
                               e2e=True, personality=1, eco=eco).evaluate()
      self.assertTrue(valid)
      self.assertLess(output[-1, 3], .1)
