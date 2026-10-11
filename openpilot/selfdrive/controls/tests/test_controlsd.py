from unittest.mock import MagicMock

from opendbc.car.structs import car
from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.common.parameterized import parameterized
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.controlsd import Controls
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState


class TestControlsLongitudinalPublication(OpenpilotTestCase):
  @parameterized.expand([
    ("engage", LongCtrlState.off, True, False, LongCtrlState.pid, 0.2),
    ("engage_stopping", LongCtrlState.off, True, True, LongCtrlState.stopping, -0.01),
    ("enter_stopping", LongCtrlState.pid, True, True, LongCtrlState.stopping, -0.01),
    ("resume", LongCtrlState.stopping, True, False, LongCtrlState.pid, 0.2),
    ("disengage_pid", LongCtrlState.pid, False, False, LongCtrlState.off, 0.0),
    ("disengage_stopping", LongCtrlState.stopping, False, True, LongCtrlState.off, 0.0),
    ("retain_pid", LongCtrlState.pid, True, False, LongCtrlState.pid, 0.2),
    ("retain_stopping", LongCtrlState.stopping, True, True, LongCtrlState.stopping, -0.01),
  ])
  def test_state_matches_acceleration(self, name, initial_state, enabled, should_stop, expected_state, expected_accel):
    controls = Controls.__new__(Controls)
    controls.CP = car.CarParams.new_message()
    controls.CP.openpilotLongitudinalControl = True
    controls.CP.stopAccel = -0.5
    controls.CP.lateralTuning.init('pid')
    controls.CP.longitudinalTuning.kiBP = [0.0]
    controls.CP.longitudinalTuning.kiV = [0.0]

    services = ['vehicleParameters', 'longitudinalPlan', 'modelV2', 'selfdriveState', 'lateralDelay',
                'driverMonitoringState', 'driverAssistance']
    data = {service: getattr(messaging.new_message(service), service) for service in services}
    data['carState'] = car.CarState.new_message(vEgo=1.0, canValid=True)
    data['carOutput'] = car.CarOutput.new_message()
    data['onroadEvents'] = []
    data['vehicleParameters'].stiffnessFactor = 1.0
    data['vehicleParameters'].steerRatio = 15.0
    data['longitudinalPlan'].aTarget = -0.2 if should_stop else 0.2
    data['longitudinalPlan'].shouldStop = should_stop
    data['selfdriveState'].enabled = enabled
    controls.sm = MagicMock()
    controls.sm.__getitem__.side_effect = data.__getitem__
    controls.sm.valid = {'lateralManeuverPlan': False, 'driverAssistance': False}
    controls.sm.logMonoTime = {'longitudinalPlan': 1, 'modelV2': 2}
    controls.pm = MagicMock()
    controls.VM = MagicMock()
    controls.VM.calc_curvature.return_value = 0.0
    controls.CI = MagicMock()
    controls.CI.get_pid_accel_limits.return_value = (-3.5, 2.0)
    controls.LaC = MagicMock()
    controls.LaC.update.return_value = (0.0, 0.0, log.ControlsState.new_message().lateralControlState.init('pidState'))
    controls.LoC = LongControl(controls.CP)
    controls.LoC.long_control_state = initial_state
    controls.LoC.last_output_accel = 0.2
    controls.desired_curvature = 0.0
    controls.steer_limited_by_safety = False
    controls.calibrated_pose = None

    CC, lac_log = controls.state_control()
    controls.publish(CC, lac_log)

    published = dict(call.args for call in controls.pm.send.call_args_list)
    actuators = published['carControl'].carControl.actuators
    self.assertEqual(actuators.longControlState, expected_state)
    self.assertEqual(actuators.longControlState, controls.LoC.long_control_state)
    self.assertEqual(actuators.longControlState, published['controlsState'].controlsState.longControlState)
    self.assertAlmostEqual(actuators.accel, expected_accel)
    self.assertAlmostEqual(actuators.accel, controls.LoC.last_output_accel)
    self.assertEqual(published['carControl'].carControl.longActive, enabled)
