import pytest
import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from opendbc.car.interfaces import ACCEL_MAX
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, LongitudinalPlanSource, get_cruise_accel


@pytest.mark.parametrize("speed", [10., 25., 35.])
def test_cruise_speed_reduction_remains_gentle_and_request_sensitive(speed):
  accel = 0.
  for speed_error, expected in [(-5., -.5), (-.2, -.2), (0., 0.)]:
    for _ in range(100):
      previous = accel
      accel = get_cruise_accel(speed + speed_error, speed, accel, previous, DT_MDL)
      assert abs(accel - previous) <= 1.6 * DT_MDL + 1e-9
      assert accel >= -.5 - 1e-9
    assert accel == pytest.approx(expected)


def planner_inputs():
  sm = {name: getattr(messaging.new_message(name), name)
        for name in ("carState", "carControl", "controlsState", "selfdriveState", "vehicleParameters", "radarState", "modelV2")}
  sm["carState"].vEgo = 25.
  sm["carState"].vCruise = 20. * 3.6
  sm["carControl"].orientationNED = [0., 0., 0.]
  sm["controlsState"].longControlState = LongCtrlState.pid
  sm["selfdriveState"].enabled = True
  sm["selfdriveState"].personality = 1
  sm["modelV2"].action.desiredAcceleration = 1.
  sm["modelV2"].meta.disengagePredictions.gasPressProbs = [1., 1.]
  return sm


def test_lead_braking_can_exceed_cruise_deceleration():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs()
  sm["radarState"].leadOne.present = True
  sm["radarState"].leadOne.dRel = 60.
  sm["radarState"].leadOne.vLead = 0.
  sm["radarState"].leadOne.aLeadTau = 1.5
  for _ in range(20):
    planner.update(sm)
  assert planner.output_a_target < -1.
  assert planner.mpc.source in (LongitudinalPlanSource.lead0, LongitudinalPlanSource.lead1)


def test_model_braking_can_exceed_cruise_deceleration():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs()
  sm["modelV2"].action.desiredAcceleration = -2.
  planner.update(sm)
  assert planner.output_a_target == pytest.approx(-2.)
  assert planner.mpc.source == LongitudinalPlanSource.e2e


def test_cruise_reduction_uses_previous_selected_acceleration():
  accel = get_cruise_accel(20., 25., 2., -1., DT_MDL)
  assert accel == pytest.approx(-.5)


@pytest.mark.parametrize("speed", [0., 10., 25., 35.])
def test_factory_econ_does_not_add_a_planner_acceleration_cap(speed):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=speed)
  reference = LongitudinalPlanner(cp, init_v=speed)
  sm = planner_inputs()
  normal = planner_inputs()
  for inputs in (sm, normal):
    inputs['carState'].vEgo = speed
    inputs['carState'].vCruise = (speed + 10.) * 3.6
    inputs['carState'].ecoModeValid = True
    inputs['modelV2'].action.desiredAcceleration = 3.
  for selected in (False, True, False):
    sm['carState'].ecoMode = selected
    sm['selfdriveState'].ecoMode = selected
    for _ in range(100):
      planner.update(sm)
      reference.update(normal)
      assert planner.output_a_target == reference.output_a_target
      assert planner.output_should_stop == reference.output_should_stop
      assert planner.mpc.source == reference.mpc.source
      np.testing.assert_array_equal(planner.a_desired_trajectory, reference.a_desired_trajectory)
    assert planner.output_a_target == pytest.approx(ACCEL_MAX)


def test_model_stop_request_remains_authoritative_with_positive_acceleration():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs()
  sm['carState'].vCruise = 35. * 3.6
  sm['modelV2'].action.shouldStop = True
  planner.update(sm)
  assert planner.output_should_stop
