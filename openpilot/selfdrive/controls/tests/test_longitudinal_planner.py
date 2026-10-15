import pytest

import openpilot.cereal.messaging as messaging
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, LongitudinalPlanSource, get_cruise_accel


@pytest.mark.parametrize("experimental", [False, True])
@pytest.mark.parametrize("speed", [10., 25., 35.])
def test_cruise_speed_reduction_remains_gentle_and_request_sensitive(experimental, speed):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = 0.
  for speed_error, expected in [(-5., -.5), (-.2, -.2), (0., 0.)]:
    for _ in range(100):
      previous = accel
      accel = get_cruise_accel(experimental, speed + speed_error, speed, accel, 0., cp, DT_MDL, 0., True)
      assert abs(accel - previous) <= 1.6 * DT_MDL + 1e-9
      assert accel >= -.5 - 1e-9
    assert accel == pytest.approx(expected)


def planner_inputs(experimental):
  sm = {name: getattr(messaging.new_message(name), name)
        for name in ("carState", "carControl", "controlsState", "selfdriveState", "vehicleParameters", "radarState", "modelV2")}
  sm["carState"].vEgo = 25.
  sm["carState"].vCruise = 20. * 3.6
  sm["carControl"].orientationNED = [0., 0., 0.]
  sm["controlsState"].longControlState = LongCtrlState.pid
  sm["selfdriveState"].enabled = True
  sm["selfdriveState"].experimentalMode = experimental
  sm["selfdriveState"].personality = 1
  sm["modelV2"].action.desiredAcceleration = 1.
  sm["modelV2"].meta.disengagePredictions.gasPressProbs = [1., 1.]
  return sm


@pytest.mark.parametrize("experimental", [False, True])
def test_lead_braking_can_exceed_cruise_deceleration(experimental):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(experimental)
  sm["radarState"].leadOne.present = True
  sm["radarState"].leadOne.dRel = 60.
  sm["radarState"].leadOne.vLead = 0.
  sm["radarState"].leadOne.aLeadTau = 1.5
  for _ in range(20):
    planner.update(sm)
  assert planner.output_a_target < -1.
  assert planner.mpc.source in (LongitudinalPlanSource.lead0, LongitudinalPlanSource.lead1)


def test_experimental_model_braking_can_exceed_cruise_deceleration():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  planner = LongitudinalPlanner(cp, init_v=25.)
  sm = planner_inputs(True)
  sm["modelV2"].action.desiredAcceleration = -2.
  planner.update(sm)
  assert planner.output_a_target == pytest.approx(-2.)
  assert planner.mpc.source == LongitudinalPlanSource.e2e


def test_disallowed_throttle_retains_coast_deceleration():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_ODYSSEY_5G_MMR)
  accel = get_cruise_accel(False, 20., 25., -.8, 0., cp, DT_MDL, -.8, False)
  assert accel == pytest.approx(-.8)
