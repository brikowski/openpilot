"""CUSTOM TUNE (ody-op-long): safety-rail coverage for the Odyssey longitudinal tune.

Upstream has no test that executes this code. The archived Odyssey test route
(opendbc/car/tests/routes.py) predates openpilot longitudinal on this car, so alpha_long resolves
False, openpilotLongitudinalControl is False, and create_acc_commands is never called - measured, 0
ACC_CONTROL frames. And test_panda_safety_tx_cases drives the controller with structs.CarControl()
defaults (longActive=False), which pins ACCEL_COMMAND at 0 and GAS_COMMAND at the -30000 inactive
constant. Neither exercises the domain decision, brake_pid, or the gas lookup.

What this covers: every ACC_CONTROL frame our ACTIVE longitudinal path emits, over the full accel
authority and on grades, must pass the real panda safety TX hook. honda_tx_hook bounds ACCEL_COMMAND
to [-350, 200] counts and GAS_COMMAND to [-30000, 2000]; a frame outside those is dropped by the
panda SILENTLY while driving, so it must be caught here instead.

The safety hook has no BRAKE_REQUEST check and no gas/brake mutual-exclusion check, so the rail
sweep cannot validate the domain decision. Two explicit state-machine regressions below cover the
invariants we have learned on-road; ride quality and closed-loop behavior still require road drives
and .agents/validate_log.py.
"""
import math
import unittest

import numpy as np

from opendbc.car import ACCELERATION_DUE_TO_GRAVITY, DT_CTRL, structs
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.carcontroller import BRAKE_DOMAIN_ENTRY, DOMAIN_HYST_EXIT
from opendbc.car.honda.values import CAR, CarControllerParams
from opendbc.safety.tests.libsafety import libsafety_py

PLATFORM = CAR.HONDA_ODYSSEY_5G_MMR
LongCtrlState = structs.CarControl.Actuators.LongControlState

# honda_tx_hook / HONDA_BOSCH_LONG_LIMITS, in raw signal counts
ACCEL_MIN_COUNTS, ACCEL_MAX_COUNTS = -350, 200
GAS_INACTIVE, GAS_MAX = -30000, 2000
GAS_RAMP_STEP = 60  # MUST track the Odyssey ramp in honda/carcontroller.py.


def _car_params(alpha_long=True):
  return interfaces[PLATFORM].get_params(PLATFORM, {0: {}, 1: {}, 2: {}}, [], alpha_long, False, docs=False)


def _decode_acc_control(dat):
  accel = (dat[3] << 3) | ((dat[4] >> 5) & 0x7)
  if accel >= 1024:
    accel -= 2048
  gas = int.from_bytes(dat[0:2], "big", signed=True)
  # ACC_CONTROL.BRAKE_REQUEST is Motorola start bit 34: byte 4, bit 2. Bit 3 is a
  # different signal and previously made both BRAKE_REQUEST=0 assertions vacuous.
  brake_request = (dat[4] >> 2) & 0x1
  return accel, gas, brake_request


def _run(long_active, accels, pitch, vego, aegos=None):
  """Drive the active longitudinal path and check every frame against the real safety hook."""
  CP = _car_params()
  CI = interfaces[PLATFORM](CP.copy())

  safety = libsafety_py.libsafety
  cfg = CP.safetyConfigs[-1]
  assert safety.set_safety_hooks(cfg.safetyModel.raw, cfg.safetyParam) == 0
  safety.init_tests()
  safety.set_controls_allowed(True)

  CI.update([])   # populates CarState-derived attrs the controller reads (acc_hud, etc.)

  active_values = np.broadcast_to(np.asarray(long_active, dtype=bool), len(accels))
  aego_values = np.zeros(len(accels)) if aegos is None else np.broadcast_to(np.asarray(aegos, dtype=float), len(accels))
  rejects, seen = [], []
  for i, accel in enumerate(accels):
    CI.CS.out = structs.CarState(
      vEgo=vego, vEgoRaw=vego, aEgo=float(aego_values[i]), standstill=vego < 0.1,
      gasPressed=False, brakePressed=False,
      cruiseState=structs.CarState.CruiseState(enabled=True, available=True, speed=25.0),
    )
    cc = structs.CarControl(
      enabled=True, latActive=False, longActive=bool(active_values[i]),
      actuators=structs.CarControl.Actuators(accel=float(accel), longControlState=LongCtrlState.pid),
      orientationNED=[0.0, float(pitch), 0.0],
    )
    _, sendcan = CI.apply(cc.as_reader(), int(i * DT_CTRL * 1e9))
    for addr, dat, bus in sendcan:
      if not safety.safety_tx_hook(libsafety_py.make_CANPacket(addr, bus % 4, dat)):
        rejects.append((i, hex(addr), accel, pitch))
      if addr == 0x1DF:
        seen.append(_decode_acc_control(dat))
  return rejects, seen


# accel authority, plus deliberate overshoot past both rails so a missing clip cannot pass
ACCEL_SWEEP = np.concatenate([
  np.linspace(0.0, -5.0, 250),    # past BOSCH_ACCEL_MIN
  np.linspace(-5.0, 3.0, 250),    # past BOSCH_ACCEL_MAX
  np.linspace(3.0, 0.0, 100),
])


class TestOdysseyLongRails(unittest.TestCase):
  def test_alpha_long_available(self):
    """The tune is unreachable if the platform cannot get openpilot longitudinal."""
    assert _car_params().openpilotLongitudinalControl

  def test_acc_control_within_safety_rails(self):
    """Every ACC_CONTROL frame from the active path passes the panda TX hook.

    Swept across grade and speed because both feed the domain decision: switch_accel picks up
    sin(pitch)*g and the drag curve, and min_gas_accel ramps over 5-10 m/s.
    """
    for pitch in [0.0, -0.05, -0.02, 0.02, 0.05]:
      for vego in [0.0, 3.0, 8.0, 20.0, 31.0]:
        with self.subTest(pitch=pitch, vego=vego):
          rejects, seen = _run(True, ACCEL_SWEEP, pitch, vego)
          assert len(seen) > 100, f"active path emitted almost no ACC_CONTROL ({len(seen)} frames)"
          assert not rejects, f"panda would DROP {len(rejects)} frame(s), e.g. {rejects[:3]}"

          accels = [a for a, _, _ in seen]
          gases = [g for _, g, _ in seen]
          brake_requests = [br for _, _, br in seen]
          assert min(accels) >= ACCEL_MIN_COUNTS, f"ACCEL_COMMAND {min(accels)} under {ACCEL_MIN_COUNTS}"
          assert max(accels) <= ACCEL_MAX_COUNTS, f"ACCEL_COMMAND {max(accels)} over {ACCEL_MAX_COUNTS}"
          assert min(gases) >= GAS_INACTIVE, f"GAS_COMMAND {min(gases)} under {GAS_INACTIVE}"
          assert max(gases) <= GAS_MAX, f"GAS_COMMAND {max(gases)} over {GAS_MAX}"
          assert any(brake_requests), "sweep never exercised BRAKE_REQUEST; its decoder may be wrong"
          assert not any(br and gas != GAS_INACTIVE for (_, gas, br) in seen), \
            "GAS_COMMAND and BRAKE_REQUEST were active together"

  def test_sweep_actually_reaches_both_rails(self):
    """Guards the test itself: if the sweep stopped exercising the clip, the check above is vacuous."""
    _, seen = _run(True, ACCEL_SWEEP, 0.0, 20.0)
    accels = [a for a, _, _ in seen]
    assert min(accels) == ACCEL_MIN_COUNTS, f"sweep never hit the lower rail (min {min(accels)})"
    assert max(accels) == ACCEL_MAX_COUNTS, f"sweep never hit the upper rail (max {max(accels)})"
    self.assertAlmostEqual(CarControllerParams.BOSCH_ACCEL_MIN * 100, ACCEL_MIN_COUNTS, delta=1,
                           msg="BOSCH_ACCEL_MIN no longer matches the safety limit this test asserts")

  def test_inactive_path_commands_nothing(self):
    """longActive=False must park the wire: accel 0, gas at the inactive constant.

    This is the coverage upstream's tx test already has - kept so a regression that leaks command
    into the disengaged path is caught here rather than on the road.
    """
    rejects, seen = _run(False, ACCEL_SWEEP, -0.05, 20.0)
    assert not rejects
    assert len(seen) > 100
    assert {a for a, _, _ in seen} == {0}, "ACCEL_COMMAND nonzero while longActive=False"
    assert {g for _, g, _ in seen} == {GAS_INACTIVE}, "GAS_COMMAND live while longActive=False"
    assert {br for _, _, br in seen} == {0}, "BRAKE_REQUEST live while longActive=False"

  def test_inactive_path_clears_supplemental_brake_state(self):
    """Manual acceleration while disengaged must not prime a brake command for re-engagement.

    This reproduces route 00000034 at 794.78 s: a brake-domain latch survived disengagement,
    brake_pid integrated against the driver's acceleration to about -2 m/s^2, and the first
    re-engaged frames commanded brake while openpilot requested positive acceleration.
    """
    active = np.array([True] * 20 + [False] * 200 + [True] * 10)
    accels = np.array([-0.5] * 20 + [0.0] * 200 + [0.1] * 10)
    aegos = np.array([0.0] * 20 + [2.0] * 200 + [0.0] * 10)

    rejects, seen = _run(active, accels, pitch=0.0, vego=20.0, aegos=aegos)
    assert not rejects
    accel, gas, brake_request = seen[-1]
    assert accel == 10, f"stale brake_pid leaked into re-engagement: ACCEL_COMMAND={accel}"
    assert gas != GAS_INACTIVE, "positive re-engagement request remained in the brake domain"
    assert brake_request == 0, "BRAKE_REQUEST remained latched across disengagement"

  def test_first_live_gas_is_rate_limited_after_brake_and_inactive(self):
    """Only transmitted gas may advance the ramp state.

    Before this regression guard, the internal ramp advanced while GAS_COMMAND was parked at
    -30000. The first live command after brake or disengagement could therefore jump past the
    intended 60-count step even though every frame still passed panda safety.
    """
    scenarios = {
      "brake_to_gas": (
        np.ones(60, dtype=bool),
        np.array([-0.5] * 30 + [2.0] * 30),
      ),
      "inactive_to_active": (
        np.array([False] * 30 + [True] * 30),
        np.full(60, 2.0),
      ),
    }
    for name, (active, accels) in scenarios.items():
      with self.subTest(name=name):
        rejects, seen = _run(active, accels, pitch=0.0, vego=20.0)
        assert not rejects
        gases = np.array([gas for _, gas, _ in seen])
        handoffs = np.flatnonzero((gases[1:] > GAS_INACTIVE) & (gases[:-1] == GAS_INACTIVE)) + 1
        assert len(handoffs) == 1, f"expected one gas handoff, saw {len(handoffs)}: {gases.tolist()}"
        first = int(gases[handoffs[0]])
        assert 0 <= first <= GAS_RAMP_STEP, \
          f"first live GAS_COMMAND jumped to {first}, above the {GAS_RAMP_STEP}-count ramp"

  def test_engaged_stop_releases_brake_for_positive_start(self):
    """An engaged stop must not require more than +0.5 m/s^2 merely to release the brake domain.

    With the full 0.50 hysteresis active at zero speed, the -0.5 stop request latched braking and
    every subsequent +0.1 start request transmitted positive ACCEL_COMMAND with BRAKE_REQUEST=1
    and GAS_COMMAND inactive. Current-code replay over stop-heavy routes found 1.2-1.3 s episodes.
    The exit band is now zero below 5 m/s while retaining its full value at road speed.
    """
    accels = np.array([-0.5] * 20 + [0.1] * 20)

    rejects, seen = _run(True, accels, pitch=0.0, vego=0.0)
    assert not rejects
    for accel, gas, brake_request in seen[-10:]:
      assert accel == 10, f"start ACCEL_COMMAND changed unexpectedly: {accel}"
      assert gas != GAS_INACTIVE, "positive low-speed start request left GAS_COMMAND inactive"
      assert brake_request == 0, "BRAKE_REQUEST remained latched against a positive start request"

  def test_descent_boundary_uses_compensated_force_hysteresis(self):
    """Exercise the grade range where raw request and compensated force have opposite signs."""
    vego = 20.0
    wind_brake = np.interp(vego, [0.0, 13.4, 22.4, 31.3, 40.2], [0.000, 0.049, 0.136, 0.267, 0.441])
    for pitch in [-0.023, -0.026, -0.030]:
      with self.subTest(pitch=pitch):
        force_offset = wind_brake * 0.5 + math.sin(pitch) * ACCELERATION_DUE_TO_GRAVITY
        entry_request = BRAKE_DOMAIN_ENTRY - force_offset
        within_band = entry_request + DOMAIN_HYST_EXIT / 2.0
        release_request = entry_request + DOMAIN_HYST_EXIT + 0.05
        accels = np.array([entry_request - 0.05] * 300 + [within_band] * 100 + [release_request] * 100)

        rejects, seen = _run(True, accels, pitch=pitch, vego=vego)
        assert not rejects
        # ACC_CONTROL is emitted at 50 Hz, so each 100-frame input phase contributes 50 samples.
        for _, gas, brake_request in seen[-100:-50]:
          assert gas == GAS_INACTIVE, "request inside the compensated-force band activated gas"
          assert brake_request == 1, "raw request sign bypassed compensated-force hysteresis"
        for _, gas, brake_request in seen[-25:]:
          assert gas != GAS_INACTIVE, "request above the compensated-force release threshold left gas inactive"
          assert brake_request == 0, "brake domain did not release above its compensated-force threshold"

  def test_lateral_defaults_follow_lka_limit_with_validated_delay(self):
    """Use stock LKA authority while retaining the validated delay correction.

    Stock LKA sends at most 2560; the 3840 RDM command includes brake drag and is not an
    equivalent steering-only operating point. lagd adds 0.20 s to CP.steerActuatorDelay.
    """
    CP = _car_params()
    self.assertEqual(list(CP.lateralParams.torqueBP), [0.0, 2560.0])
    self.assertEqual(list(CP.lateralParams.torqueV), [0.0, 2560.0])
    self.assertAlmostEqual(CP.lateralTuning.torque.latAccelFactor, 0.9)
    self.assertAlmostEqual(CP.steerActuatorDelay, 0.20)
    self.assertAlmostEqual(CP.steerActuatorDelay + 0.20, 0.40)
