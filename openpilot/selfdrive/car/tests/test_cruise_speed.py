import itertools
from types import SimpleNamespace
from unittest import mock

from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized_class
from openpilot.cereal import log
from openpilot.selfdrive.car.cruise import VCruiseHelper, V_CRUISE_INITIAL
from opendbc.car.structs import car
from openpilot.common.constants import CV

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type


def run_cruise_simulation(cruise, personality, t_end=20.):
  from openpilot.selfdrive.test.longitudinal_maneuvers.maneuver import Maneuver

  man = Maneuver(
    '',
    duration=t_end,
    initial_speed=max(cruise - 1., 0.0),
    lead_relevancy=True,
    initial_distance_lead=100,
    cruise_values=[cruise],
    prob_lead_values=[0.0],
    breakpoints=[0.],
    personality=personality,
  )
  valid, output = man.evaluate()
  assert valid
  return output[-1, 3]


@parameterized_class(("personality", "speed"), itertools.product(
                      log.LongitudinalPersonality.schema.enumerants, # personality
                      [5,35])) # speed
class TestCruiseSpeed(OpenpilotTestCase):
  def test_cruise_speed(self):
    print(f'Testing {self.speed} m/s')
    cruise_speed = float(self.speed)

    simulation_steady_state = run_cruise_simulation(cruise_speed, self.personality)
    self.assertAlmostEqual(simulation_steady_state, cruise_speed, delta=.01, msg=f'Did not reach {self.speed} m/s')


# TODO: test pcmCruise
@parameterized_class(('pcm_cruise',), [(False,)])
class TestVCruiseHelper(OpenpilotTestCase):
  def setup_method(self):
    self.CP = car.CarParams(pcmCruise=self.pcm_cruise)
    self.v_cruise_helper = VCruiseHelper(self.CP)
    self.reset_cruise_speed_state()

  def reset_cruise_speed_state(self):
    # Two resets previous cruise speed
    for _ in range(2):
      self.v_cruise_helper.update_v_cruise(car.CarState(cruiseState={"available": False}), enabled=False, is_metric=False)

  def enable(self, v_ego):
    # Simulates user pressing set with a current speed
    self.v_cruise_helper.initialize_v_cruise(car.CarState(vEgo=v_ego), V_CRUISE_INITIAL, False)

  def test_adjust_speed(self):
    """
    Asserts speed changes on falling edges of buttons.
    """

    self.enable(V_CRUISE_INITIAL * CV.KPH_TO_MS)

    for btn in (ButtonType.accelCruise, ButtonType.decelCruise):
      for pressed in (True, False):
        CS = car.CarState(cruiseState={"available": True})
        CS.buttonEvents = [ButtonEvent(type=btn, pressed=pressed)]

        self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)
        assert pressed == (self.v_cruise_helper.v_cruise_kph == self.v_cruise_helper.v_cruise_kph_last)

  def test_rising_edge_enable(self):
    """
    Some car interfaces may enable on rising edge of a button,
    ensure we don't adjust speed if enabled changes mid-press.
    """

    # NOTE: enabled is always one frame behind the result from button press in controlsd
    for enabled, pressed in ((False, False),
                             (False, True),
                             (True, False)):
      CS = car.CarState(cruiseState={"available": True})
      CS.buttonEvents = [ButtonEvent(type=ButtonType.decelCruise, pressed=pressed)]
      self.v_cruise_helper.update_v_cruise(CS, enabled=enabled, is_metric=False)
      if pressed:
        self.enable(V_CRUISE_INITIAL * CV.KPH_TO_MS)

      # Expected diff on enabling. Speed should not change on falling edge of pressed
      assert (not pressed) == (self.v_cruise_helper.v_cruise_kph == self.v_cruise_helper.v_cruise_kph_last)

  def test_resume_in_standstill(self):
    """
    Asserts we don't increment set speed if user presses resume/accel to exit cruise standstill.
    """

    self.enable(0)

    for standstill in (True, False):
      for pressed in (True, False):
        CS = car.CarState(cruiseState={"available": True, "standstill": standstill})
        CS.buttonEvents = [ButtonEvent(type=ButtonType.accelCruise, pressed=pressed)]
        self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

        # speed should only update if not at standstill and button falling edge
        should_equal = standstill or pressed
        assert should_equal == (self.v_cruise_helper.v_cruise_kph == self.v_cruise_helper.v_cruise_kph_last)

  def test_set_gas_pressed(self):
    """
    Asserts pressing set while enabled with gas pressed sets
    the speed to the maximum of vEgo and current cruise speed.
    """

    for v_ego, expected_mph in ((0., 24), (20., 45), (30., 67), (50., 90)):
      self.reset_cruise_speed_state()
      self.enable(V_CRUISE_INITIAL * CV.KPH_TO_MS)
      CS = car.CarState(vEgo=float(v_ego), gasPressed=True, cruiseState={"available": True})
      CS.buttonEvents = [ButtonEvent(type=ButtonType.decelCruise, pressed=True)]
      self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)
      CS.buttonEvents = [ButtonEvent(type=ButtonType.decelCruise, pressed=False)]
      self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)
      self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph * CV.KPH_TO_MPH, expected_mph)

  def test_initialize_v_cruise(self):
    """
    Asserts allowed cruise speeds on enabling with SET.
    """

    for initial_speed, cases in (
      (V_CRUISE_INITIAL, ((0., 40), (5., 40), (20., 72), (29.5, 106), (50., 145))),
      (90, ((0., 90), (20., 90), (30., 108), (50., 145))),
    ):
      for v_ego, expected in cases:
        self.reset_cruise_speed_state()
        assert not self.v_cruise_helper.v_cruise_initialized

        self.v_cruise_helper.initialize_v_cruise(car.CarState(vEgo=v_ego), initial_speed, True)
        assert self.v_cruise_helper.v_cruise_kph == expected
        assert self.v_cruise_helper.v_cruise_cluster_kph == expected
        assert self.v_cruise_helper.v_cruise_initialized

  def test_imperial_setpoint_matches_display_and_button_steps(self):
    self.v_cruise_helper.initialize_v_cruise(car.CarState(vEgo=31.1), V_CRUISE_INITIAL, False)
    self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph, 112.65408)
    for button, expected in ((ButtonType.accelCruise, 71), (ButtonType.decelCruise, 70),
                             (ButtonType.decelCruise, 69), (ButtonType.accelCruise, 70)):
      for pressed in (True, False):
        state = car.CarState(cruiseState={"available": True}, buttonEvents=[ButtonEvent(type=button, pressed=pressed)])
        self.v_cruise_helper.update_v_cruise(state, enabled=True, is_metric=False)
      self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph * CV.KPH_TO_MPH, expected)
      self.assertEqual(self.v_cruise_helper.v_cruise_cluster_kph, self.v_cruise_helper.v_cruise_kph)

  def test_imperial_long_press_and_bounds_are_whole_mph(self):
    for initial, button, expected in ((69., ButtonType.accelCruise, 70), (70., ButtonType.accelCruise, 75),
                                      (71., ButtonType.decelCruise, 70), (70., ButtonType.decelCruise, 65),
                                      (89., ButtonType.accelCruise, 90), (6., ButtonType.decelCruise, 5)):
      self.v_cruise_helper.v_cruise_kph = initial * CV.MPH_TO_KPH
      self.v_cruise_helper.button_timers = {ButtonType.accelCruise: 0, ButtonType.decelCruise: 0}
      self.v_cruise_helper.button_timers[button] = 50
      self.v_cruise_helper.button_change_states[button] = {"standstill": False, "enabled": True}
      self.v_cruise_helper.update_v_cruise(car.CarState(cruiseState={"available": True}), True, False)
      self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph * CV.KPH_TO_MPH, expected)

  def test_imperial_initial_limits_resume_and_pcm(self):
    for speed, initial, expected in ((0., 40, 25), (20., 90, 56), (50., 40, 90)):
      self.v_cruise_helper.initialize_v_cruise(car.CarState(vEgo=speed), initial, False)
      self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph * CV.KPH_TO_MPH, expected)
    self.v_cruise_helper.v_cruise_kph_last = 70 * CV.MPH_TO_KPH
    state = car.CarState(buttonEvents=[ButtonEvent(type=ButtonType.accelCruise)])
    self.v_cruise_helper.initialize_v_cruise(state, 40, False)
    self.assertAlmostEqual(self.v_cruise_helper.v_cruise_kph, 112.65408)
    pcm = VCruiseHelper(car.CarParams(pcmCruise=True))
    state = car.CarState(cruiseState={"available": True, "speed": 30., "speedCluster": 31.})
    pcm.update_v_cruise(state, True, False)
    pcm.initialize_v_cruise(state, 40, False)
    self.assertAlmostEqual(pcm.v_cruise_kph, 108.)
    self.assertAlmostEqual(pcm.v_cruise_cluster_kph, 111.6)

  def test_car_publishes_initial_target_in_selected_units(self):
    from openpilot.selfdrive.car import card

    class SubMaster(dict):
      def update(self, _):
        pass

    for metric, expected in ((False, 112.65408), (True, 112.)):
      device = object.__new__(card.Car)
      device.CI = SimpleNamespace(update=lambda _: car.CarState(vEgo=31.1))
      device.RI = SimpleNamespace(update=lambda _: None)
      device.can_sock = None
      device.can_rcv_cum_timeout_counter = 0
      device.sm = SubMaster(carControl=car.CarControl(enabled=True))
      device.CC_prev = car.CarControl(enabled=False)
      device.CS_prev = car.CarState(vEgo=31.1)
      device.v_cruise_helper = VCruiseHelper(car.CarParams(pcmCruise=False))
      device.initial_cruise_speed = 40
      device.is_metric = metric
      with mock.patch.object(card.messaging, 'drain_sock_raw', return_value=[]), mock.patch.object(card, 'can_capnp_to_list', return_value=[]):
        state, _ = device.state_update()
      self.assertAlmostEqual(state.vCruise, expected, places=5)
      self.assertAlmostEqual(state.vCruiseCluster, expected, places=5)
