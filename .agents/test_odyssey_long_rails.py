"""Odyssey active-longitudinal panda-rail and command regressions.

The archived upstream Odyssey route does not exercise openpilot longitudinal. These tests drive
the active path across accel, speed, and grade; require each ACC_CONTROL frame to pass the Honda TX
hook; and separately guard the Odyssey command domains and gas/brake mutual exclusion. They do not
grade road behavior.
"""
import unittest

import numpy as np

from opendbc.car import DT_CTRL, structs
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import (
  CAR,
  CarControllerParams,
  ODYSSEY_GAS_FACTOR_SPEED_BP,
  ODYSSEY_GAS_FACTOR_SPEED_V,
)
from opendbc.safety.tests.libsafety import libsafety_py

PLATFORM = CAR.HONDA_ODYSSEY_5G_MMR
LongCtrlState = structs.CarControl.Actuators.LongControlState

# honda_tx_hook / HONDA_BOSCH_LONG_LIMITS, in raw signal counts
ACCEL_MIN_COUNTS, ACCEL_MAX_COUNTS = -350, 200
GAS_INACTIVE, GAS_MAX = -30000, 2000


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


def _run(long_active, accels, pitch, vego, aegos=None, long_control_state=LongCtrlState.pid):
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
      actuators=structs.CarControl.Actuators(accel=float(accel), longControlState=long_control_state),
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
  def test_gas_factor_seed_is_per_car_parameter_data(self):
    """The Odyssey powertrain seed must not remain shared controller-module state."""
    params = CarControllerParams(_car_params())
    assert params.GAS_FACTOR_SPEED_BP == ODYSSEY_GAS_FACTOR_SPEED_BP
    assert params.GAS_FACTOR_SPEED_V == ODYSSEY_GAS_FACTOR_SPEED_V
    assert not hasattr(CarControllerParams, "GAS_FACTOR_SPEED_BP")
    assert not hasattr(CarControllerParams, "GAS_FACTOR_SPEED_V")

  def test_brake_command_matches_request_without_supplement_or_shaping(self):
    for name, vego, state, pitch in (
      ("road", 20.0, LongCtrlState.pid, 0.0),
      ("descent", 20.0, LongCtrlState.pid, -0.05),
      ("low_speed", 8.0, LongCtrlState.pid, 0.0),
      ("stopping", 20.0, LongCtrlState.stopping, 0.0),
    ):
      with self.subTest(name=name):
        accels = np.array([0.5] * 20 + [-0.6] * 100)
        # Positive aEgo would make the former supplemental integrator add braking.
        aegos = np.array([0.0] * 20 + [2.0] * 100)
        rejects, seen = _run(True, accels, pitch=pitch, vego=vego, aegos=aegos, long_control_state=state)
        assert not rejects
        brake = np.array([br for _, _, br in seen], dtype=bool)
        entry = np.flatnonzero(brake & ~np.roll(brake, 1))[0]
        assert {accel for accel, _, _ in seen[entry:]} == {-60}, \
          f"{name} brake command diverged from the -0.60 m/s^2 request"

  def test_road_speed_coasts_through_raw_split_chatter(self):
    """Small negative requests must not alternate Honda's gas and friction-brake domains."""
    for vego in (5.0, 20.0, 31.0):
      for pitch in (-0.05, 0.0, 0.05):
        with self.subTest(vego=vego, pitch=pitch):
          # These requests bracket the upstream -0.20 split in the failed route. They must remain
          # neutral; a stronger request still gets immediate brake authority and positive gets gas.
          accels = np.array(([-0.18] * 4 + [-0.23] * 4) * 20 + [-0.31] * 20 + [-0.49] * 20 + [-0.51] * 20 + [0.10] * 20)
          rejects, seen = _run(True, accels, pitch=pitch, vego=vego)
          assert not rejects
          assert {-18, -23, -31, -49, -51, 10}.issubset({accel for accel, _, _ in seen})
          for accel, gas, brake_request in seen:
            if accel in (-18, -23):
              assert gas == GAS_INACTIVE, "negative road request left GAS_COMMAND active"
              assert brake_request == 0, "raw -0.20 crossing still toggled BRAKE_REQUEST"
            elif accel == -51:
              assert gas == GAS_INACTIVE
              assert brake_request == 1, "stronger road request did not select brake immediately"
            elif accel in (-31, -49):
              assert gas == GAS_INACTIVE
              assert brake_request == 0, "mild road request did not remain in coast"
            elif accel == 10:
              assert gas != GAS_INACTIVE, "positive road request did not select gas"
              assert brake_request == 0

  def test_road_speed_brake_domain_releases_for_positive_request(self):
    """A settling brake request may cross the coast band, but positive gas releases immediately."""
    accels = np.array([-0.6] * 20 + [-0.55] * 20 + [0.10] * 20)
    rejects, seen = _run(True, accels, pitch=0.0, vego=20.0)
    assert not rejects
    brake = np.array([br for _, _, br in seen], dtype=bool)
    gas = np.array([gas for _, gas, _ in seen])
    # The state is intentionally narrow: negative coast requests do not re-arm/release the
    # friction-brake domain, while a positive request still gets gas on the next command.
    assert brake[:10].all()
    assert brake[10:20].all()
    assert not brake[-10:].any()
    assert (gas[-10:] != GAS_INACTIVE).all()

  def test_road_speed_gas_domain_does_not_pulse_at_zero(self):
    """Gas stays active through zero, but re-enters only after a material request following coast."""
    accels = np.array([0.10] * 20 + [-0.19] * 20 + [-0.21] * 20 + [-0.10] * 20 +
                      [0.01] * 20 + [0.03] * 20)
    rejects, seen = _run(True, accels, pitch=0.0, vego=20.0)
    assert not rejects
    gases = np.array([gas for _, gas, _ in seen])
    brake = np.array([br for _, _, br in seen], dtype=bool)
    assert (gases[:20] != GAS_INACTIVE).all(), "stock gas range pulsed inactive"
    assert (gases[20:40] == GAS_INACTIVE).all(), "gas re-entered for a non-positive request"
    assert (gases[80:100] == GAS_INACTIVE).all(), "tiny road request re-entered gas"
    assert (gases[-10:] != GAS_INACTIVE).all(), "material road request did not re-enter gas"
    assert not brake.any(), "gas release hysteresis unexpectedly selected the brake domain"

  def test_gas_command_does_not_add_unverified_grade_or_drag(self):
    """The gas wire must not change solely because the recorded pitch changes."""
    accels = np.full(40, 0.10)
    _, level = _run(True, accels, pitch=0.0, vego=31.0)
    _, downhill = _run(True, accels, pitch=-0.05, vego=31.0)
    level_gas = np.array([gas for _, gas, _ in level])
    downhill_gas = np.array([gas for _, gas, _ in downhill])
    np.testing.assert_array_equal(downhill_gas, level_gas)

  def test_unidentified_windfactor_is_not_production_state(self):
    """Keep unidentified drag learning offline until it has an attributable command benefit."""
    CP = _car_params()
    controller = interfaces[PLATFORM](CP.copy()).CC
    for attribute in ("windfactor", "windfactor_before_brake", "windfactor_before_gasmax"):
      assert not hasattr(controller, attribute), f"dead production learner state remains: {attribute}"

  def test_low_speed_nonpositive_request_never_selects_gas(self):
    """A lead-stop request may relax above -0.20 but must keep brake authority below 5 m/s."""
    for vego in (0.0, 1.0, 4.99):
      with self.subTest(vego=vego):
        accels = np.array([-0.21] * 20 + [-0.18] * 20 + [0.0] * 20 + [0.10] * 20)
        rejects, seen = _run(True, accels, pitch=0.0, vego=vego)
        assert not rejects
        for accel, gas, brake_request in seen[:30]:
          assert accel <= 0
          assert gas == GAS_INACTIVE, "non-positive low-speed request selected gas"
          assert brake_request == 1, "non-positive low-speed request released brake"
        for accel, gas, brake_request in seen[-10:]:
          assert accel == 10
          assert gas != GAS_INACTIVE, "positive low-speed start request did not select gas"
          assert brake_request == 0, "positive low-speed start request left brake active"

  def test_low_speed_brake_command_matches_request(self):
    """Honda's low-speed brake domain must not reshape the controller request."""
    accels = np.array([-0.21] * 30 + [-0.17] * 50)
    aegos = np.array([-0.21] * 10 + [0.5] * 70)
    rejects, seen = _run(True, accels, pitch=0.0, vego=1.0, aegos=aegos)
    assert not rejects
    commands = np.array([accel for accel, _, _ in seen])
    np.testing.assert_array_equal(commands[:15], np.full(15, -21))
    np.testing.assert_array_equal(commands[15:], np.full(25, -17))

  def test_low_speed_positive_reengagement_has_no_stale_brake(self):
    """An inactive interval must not leave stale braking on positive re-engagement."""
    active = np.array([True] * 60 + [False] * 20 + [True] * 20)
    accels = np.array([-0.21] * 60 + [0.0] * 20 + [0.1] * 20)
    aegos = np.array([0.5] * 60 + [2.0] * 20 + [0.0] * 20)
    rejects, seen = _run(active, accels, pitch=0.0, vego=1.0, aegos=aegos)
    assert not rejects
    reengaged = seen[-10:]
    assert {accel for accel, _, _ in reengaged} == {10}
    assert all(gas != GAS_INACTIVE and brake == 0 for _, gas, brake in reengaged)

  def test_alpha_long_available(self):
    """The tune is unreachable if the platform cannot get openpilot longitudinal."""
    assert _car_params().openpilotLongitudinalControl

  def test_acc_control_within_safety_rails(self):
    """Every ACC_CONTROL frame from the active path passes the panda TX hook.

    Speed affects the Odyssey gas calibration; grade is intentionally diagnostic-only. Sweep both
    dimensions even though domain selection uses only the raw request and speed.
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

  def test_positive_reengagement_has_no_stale_brake_command(self):
    """Manual acceleration while disengaged must not affect the re-engagement command.

    This preserves the observable route-34 regression guard after removing the stateful domain
    latch and supplemental integrator that caused it.
    """
    active = np.array([True] * 20 + [False] * 200 + [True] * 10)
    accels = np.array([-0.5] * 20 + [0.0] * 200 + [0.1] * 10)
    aegos = np.array([0.0] * 20 + [2.0] * 200 + [0.0] * 10)

    rejects, seen = _run(active, accels, pitch=0.0, vego=20.0, aegos=aegos)
    assert not rejects
    accel, gas, brake_request = seen[-1]
    assert accel == 10, f"stale braking leaked into re-engagement: ACCEL_COMMAND={accel}"
    assert gas != GAS_INACTIVE, "positive re-engagement request remained in the brake domain"
    assert brake_request == 0, "BRAKE_REQUEST remained latched across disengagement"

  def test_first_live_gas_is_not_artificially_delayed_after_brake_and_inactive(self):
    """A positive request must receive its calculated gas command on the first eligible frame."""
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
        live = gases[handoffs[0]:]
        assert live[0] > 0, "positive request produced a non-positive first live GAS_COMMAND"
        assert abs(live[0] - np.median(live[-5:])) <= 10, \
          f"first live GAS_COMMAND {live[0]} was delayed below the settled command {np.median(live[-5:])}"

  def test_engaged_stop_releases_brake_for_positive_start(self):
    """A positive start request must immediately select gas after an engaged stop."""
    accels = np.array([-0.5] * 20 + [0.1] * 20)

    rejects, seen = _run(True, accels, pitch=0.0, vego=0.0)
    assert not rejects
    for accel, gas, brake_request in seen[-10:]:
      assert accel == 10, f"start ACCEL_COMMAND changed unexpectedly: {accel}"
      assert gas != GAS_INACTIVE, "positive low-speed start request left GAS_COMMAND inactive"
      assert brake_request == 0, "BRAKE_REQUEST remained latched against a positive start request"

  def test_lateral_defaults_follow_stock_lka_tune(self):
    """Use the Odyssey stock-LKA torque range and stock lateral calibration."""
    CP = _car_params()
    self.assertEqual(list(CP.lateralParams.torqueBP), [0.0, 2560.0])
    self.assertEqual(list(CP.lateralParams.torqueV), [0.0, 2560.0])
    self.assertAlmostEqual(CP.lateralTuning.torque.latAccelFactor, 0.9)
    self.assertAlmostEqual(CP.steerActuatorDelay, 0.15)
    self.assertAlmostEqual(CP.steerActuatorDelay + 0.20, 0.35)
