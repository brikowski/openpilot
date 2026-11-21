import numpy as np
from unittest.mock import patch

from openpilot.cereal import log, messaging
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.selfdrive.locationd.locationd import CAM_ODO_POSE_DELAY, LocationEstimator
from openpilot.selfdrive.locationd.models.pose_kf import EARTH_G, PoseKalman, States


def _simulate_drive(duration_s=60.0, speed=20.0, roll_true=0.02, pitch_true=-0.05,
                    acc_bias_true=(0.0, 0.0, 0.0), spike_step=None, spike_raw_v0=0.0,
                    spike_accel_vec=(0.0, 0.0, 0.0), transient_accel_window=None,
                    transient_accel_true=0.0, transient_odo_dv=0.0,
                    trans_std=(0.02, 0.02, 0.02), rot_std=(0.005, 0.005, 0.005)):
  """Simulate 100 Hz IMU and 20 Hz camera odometry through LocationEstimator."""
  estimator = LocationEstimator(debug=True)
  t0 = 100.0
  estimator.reset(t0, PoseKalman.initial_x.copy(), PoseKalman.initial_P.copy())

  ned_from_device = rot_from_euler([roll_true, pitch_true, 0.0])
  device_from_ned = ned_from_device.T
  gravity_device = device_from_ned @ np.array([0.0, 0.0, -EARTH_G])
  acc_bias = np.asarray(acc_bias_true, dtype=float)

  calib_msg = messaging.new_message('extrinsicsCalibration')
  calib_msg.extrinsicsCalibration.rpyCalib = [0.0, 0.0, 0.0]
  estimator.handle_log(t0, 'extrinsicsCalibration', calib_msg.extrinsicsCalibration)

  v = float(speed)
  steps = int(round(duration_s * 100))
  orientations = []
  for step in range(steps):
    t = t0 + step * 0.01
    t_ns = int(round(t * 1e9))
    in_transient = (transient_accel_window is not None and
                    transient_accel_window[0] <= step < transient_accel_window[1])
    a_true = transient_accel_true if in_transient else 0.0
    if in_transient:
      v = min(25.0, v + transient_odo_dv)

    car_msg = messaging.new_message('carState')
    car_msg.carState.vEgo = v
    estimator.handle_log(t, 'carState', car_msg.carState)

    gyro_msg = messaging.new_message('gyroscope')
    gyro_msg.gyroscope.source = log.SensorEventData.SensorSource.lsm6ds3
    gyro_msg.gyroscope.timestamp = t_ns
    gyro_uncal = gyro_msg.gyroscope.init('gyroUncalibrated')
    gyro_uncal.v = [0.0, 0.0, 0.0]
    estimator.handle_log(t, 'gyroscope', gyro_msg.gyroscope)

    acc_meas = gravity_device + acc_bias + np.array([a_true, 0.0, 0.0])
    if spike_step is not None and step == spike_step:
      acc_meas = acc_meas + np.asarray(spike_accel_vec, dtype=float)
    acc_msg = messaging.new_message('accelerometer')
    acc_msg.accelerometer.source = log.SensorEventData.SensorSource.lsm6ds3
    acc_msg.accelerometer.timestamp = t_ns
    # locationd maps acceleration.v via meas = [-v[2], -v[1], -v[0]]
    acc_data = acc_msg.accelerometer.init('acceleration')
    v0_spike = spike_raw_v0 if (spike_step is not None and step == spike_step) else 0.0
    acc_data.v = [float(-acc_meas[2] + v0_spike), float(-acc_meas[1]), float(-acc_meas[0])]
    estimator.handle_log(t, 'accelerometer', acc_msg.accelerometer)

    if step % 5 == 0:
      odo_msg = messaging.new_message('cameraOdometry')
      odo_msg.cameraOdometry.timestampEof = int(round((t + CAM_ODO_POSE_DELAY) * 1e9))
      odo_msg.cameraOdometry.trans = [v, 0.0, 0.0]
      odo_msg.cameraOdometry.transStd = list(trans_std)
      odo_msg.cameraOdometry.rot = [0.0, 0.0, 0.0]
      odo_msg.cameraOdometry.rotStd = list(rot_std)
      estimator.handle_log(t, 'cameraOdometry', odo_msg.cameraOdometry)

      motion = estimator.get_msg(sensors_valid=True, inputs_valid=True, filter_initialized=True).deviceMotion
      ori = motion.orientationNED
      orientations.append([ori.x, ori.y, ori.z])

  return np.asarray(orientations), estimator.kf.x[States.ACCEL_BIAS].copy()


class TestPoseKalman(OpenpilotTestCase):
  def test_mount_pitch_and_roll_converge_without_horizontal_accel_bias_drift(self):
    orientations, acc_bias = _simulate_drive(duration_s=60.0, roll_true=0.02, pitch_true=-0.05)
    roll, pitch, _ = orientations[-1]
    assert abs(pitch - (-0.05)) < 0.003
    assert abs(roll - 0.02) < 0.003
    assert abs(acc_bias[0]) < 0.02
    assert abs(acc_bias[1]) < 0.02

  def test_rejects_legacy_unobservable_horizontal_accel_bias_drift(self):
    legacy_P = np.diag([0.01**2, 0.01**2, 0.01**2,
                        10**2, 10**2, 10**2,
                        1**2, 1**2, 1**2,
                        0.1**2, 0.1**2, 0.1**2,
                        100**2, 100**2, 100**2,
                        0.01**2, 0.01**2, 0.01**2])
    legacy_Q = np.diag([0.001**2, 0.001**2, 0.001**2,
                        0.01**2, 0.01**2, 0.01**2,
                        0.085**2, 0.085**2, 0.085**2,
                        (0.005 / 100)**2, (0.005 / 100)**2, (0.005 / 100)**2,
                        3**2, 3**2, 3**2,
                        0.005**2, 0.005**2, 0.005**2])
    scenario = {
      'duration_s': 120.0, 'speed': 15.0, 'roll_true': 0.02, 'pitch_true': -0.05,
      'transient_accel_window': (3000, 6000), 'transient_accel_true': 1.5,
      'transient_odo_dv': 0.003, 'trans_std': (0.1, 0.1, 0.1), 'rot_std': (0.005, 0.005, 0.005),
    }
    fixed_orientations, fixed_ab = _simulate_drive(**scenario)
    with patch.object(PoseKalman, 'initial_P', legacy_P), patch.object(PoseKalman, 'Q', legacy_Q):
      legacy_orientations, legacy_ab = _simulate_drive(**scenario)
    assert abs(fixed_orientations[-1, 1] - (-0.05)) < 0.002
    assert abs(fixed_ab[0]) < 0.005
    assert abs(legacy_ab[0]) > 0.02
    assert abs(legacy_ab[0]) > 10 * abs(fixed_ab[0])
    assert abs(legacy_orientations[-1, 1] - (-0.05)) > 0.003

  def test_accelerometer_spike_resilience(self):
    clean, _ = _simulate_drive(duration_s=30.0, roll_true=0.02, pitch_true=-0.05)
    spiked_sanity, _ = _simulate_drive(duration_s=30.0, roll_true=0.02, pitch_true=-0.05,
                                       spike_step=1500, spike_raw_v0=100.0)
    assert np.max(np.abs(spiked_sanity[:, 0] - clean[:, 0])) < np.radians(0.1)
    assert np.max(np.abs(spiked_sanity[:, 1] - clean[:, 1])) < np.radians(0.1)

    spiked_bump, _ = _simulate_drive(duration_s=30.0, roll_true=0.02, pitch_true=-0.05,
                                     spike_step=1500, spike_accel_vec=(0.0, 0.0, -15.0))
    assert np.max(np.abs(spiked_bump[:, 0] - clean[:, 0])) < np.radians(0.2)
    assert np.max(np.abs(spiked_bump[:, 1] - clean[:, 1])) < np.radians(0.2)

  def test_vertical_accel_bias_remains_observable(self):
    orientations, acc_bias = _simulate_drive(duration_s=60.0, roll_true=0.01, pitch_true=-0.04,
                                             acc_bias_true=(0.0, 0.0, 0.15))
    assert abs(acc_bias[2] - 0.15) < 0.03
    assert abs(orientations[-1, 0] - 0.01) < 0.003
    assert abs(orientations[-1, 1] - (-0.04)) < 0.003
