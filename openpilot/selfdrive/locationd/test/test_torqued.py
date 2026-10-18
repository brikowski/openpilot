from opendbc.car import gen_empty_fingerprint
from opendbc.car.honda.hondacan import CanBus as HondaCanBus
from opendbc.car.honda.interface import CarInterface as HondaInterface
from opendbc.car.honda.values import CAR
from opendbc.car.structs import car
from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.torqued import TorqueEstimator, VERSION


class TestTorqued(OpenpilotTestCase):
  @staticmethod
  def cache_params(CP):
    params = Params()
    cp_bytes = CP.to_bytes()
    params.put("CarParamsPrevRoute", cp_bytes, block=True)
    msg = messaging.new_message('lateralTorqueParameters')
    torque = msg.lateralTorqueParameters
    torque.version = VERSION
    torque.valid = True
    torque.latAccelFactorFiltered = CP.lateralTuning.torque.latAccelFactor * 1.1
    torque.frictionCoefficientFiltered = CP.lateralTuning.torque.friction * 1.1
    torque.latAccelOffsetFiltered = .1
    torque.decay = 100.
    torque.points = [[-.1, -.1], [.1, .1]]
    params.put("LiveTorqueParameters", msg.to_bytes(), block=True)
    return cp_bytes

  def test_stale_cache_cannot_return_after_a_short_route(self):
    CP = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    self.cache_params(CP)
    changed = CP.as_reader().as_builder()
    changed.lateralTuning.torque.latAccelFactor *= 1.2
    assert len(TorqueEstimator(changed).filtered_points) == 0
    assert Params().get("LiveTorqueParameters") is None

    # A route can update CarParams without reaching the learner's periodic cache write.
    Params().put("CarParamsPrevRoute", changed.to_bytes(), block=True)
    estimator = TorqueEstimator(changed)
    assert len(estimator.filtered_points) == 0
    assert estimator.filtered_params['latAccelFactor'].x == changed.lateralTuning.torque.latAccelFactor

  def test_odyssey_stock_range_rejects_trial_normalization_cache(self):
    current = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    previous = current.as_reader().as_builder()
    previous.lateralTuning.torque.latAccelFactor = 1.35
    previous.lateralTuning.torque.friction = .2 / 1.5
    self.cache_params(previous)
    params = Params()
    unrelated = ('CalibrationParams', 'LiveParametersV2', 'LiveDelay')
    for key in unrelated:
      params.put(key, b'preserved', block=True)

    estimator = TorqueEstimator(current)
    assert len(estimator.filtered_points) == 0
    assert estimator.filtered_params['latAccelFactor'].x == current.lateralTuning.torque.latAccelFactor
    assert estimator.filtered_params['frictionCoefficient'].x == current.lateralTuning.torque.friction
    assert params.get('LiveTorqueParameters') is None
    for key in unrelated:
      assert params.get(key) == b'preserved'

  def test_honda_steering_path_change_discards_cached_params(self):
    for previous_alpha in (False, True):
      with self.subTest(previous_alpha=previous_alpha):
        previous, current = [HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], alpha, False, False)
                             for alpha in (previous_alpha, not previous_alpha)]
        assert HondaCanBus(previous).lkas != HondaCanBus(current).lkas
        self.cache_params(previous)
        estimator = TorqueEstimator(current)
        assert len(estimator.filtered_points) == 0
        assert estimator.filtered_params['latAccelFactor'].x == current.lateralTuning.torque.latAccelFactor
        assert Params().get("LiveTorqueParameters") is None

  def test_cache_without_previous_configuration_is_discarded(self):
    CP = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    cp_bytes = self.cache_params(CP)
    Params().remove("CarParamsPrevRoute")
    assert len(TorqueEstimator(CP).filtered_points) == 0
    assert Params().get("LiveTorqueParameters") is None
    Params().put("CarParamsPrevRoute", cp_bytes, block=True)
    assert len(TorqueEstimator(CP).filtered_points) == 0

  def test_unchanged_honda_steering_path_retains_cached_params(self):
    for model, previous_alpha, current_alpha in (
      (CAR.HONDA_ODYSSEY_5G_MMR, False, False),
      (CAR.HONDA_ODYSSEY_5G_MMR, True, True),
      (CAR.HONDA_CITY_7G, False, True),
      (CAR.HONDA_CITY_7G, True, False),
    ):
      with self.subTest(model=model, previous_alpha=previous_alpha, current_alpha=current_alpha):
        previous, current = [HondaInterface.get_params(model, gen_empty_fingerprint(), [], alpha, False, False)
                             for alpha in (previous_alpha, current_alpha)]
        assert HondaCanBus(previous).lkas == HondaCanBus(current).lkas
        self.cache_params(previous)
        estimator = TorqueEstimator(current)
        assert len(estimator.filtered_points) == 2
        assert estimator.filtered_params['latAccelFactor'].x != current.lateralTuning.torque.latAccelFactor
        assert Params().get("LiveTorqueParameters") is not None

  def test_other_brand_longitudinal_switch_retains_cached_params(self):
    previous = car.CarParams(carFingerprint="mock", brand="toyota")
    previous.lateralTuning.init('torque')
    previous.lateralTuning.torque.latAccelFactor = 1.
    previous.lateralTuning.torque.friction = .1
    self.cache_params(previous)
    current = previous.as_reader().as_builder()
    current.openpilotLongitudinalControl = not previous.openpilotLongitudinalControl
    estimator = TorqueEstimator(current)
    assert len(estimator.filtered_points) == 2
    assert estimator.filtered_params['latAccelFactor'].x != current.lateralTuning.torque.latAccelFactor

  def test_cal_percent(self):
    est = TorqueEstimator(car.CarParams())
    msg = est.get_msg()
    assert msg.lateralTorqueParameters.calPerc == 0

    for (low, high), min_pts in zip(est.filtered_points.buckets.keys(),
                                    est.filtered_points.buckets_min_points.values(), strict=True):
      for _ in range(int(min_pts)):
        est.filtered_points.add_point((low + high) / 2.0, 0.0)

    # enough bucket points, but not enough total points
    msg = est.get_msg()
    assert msg.lateralTorqueParameters.calPerc == (len(est.filtered_points) / est.min_points_total * 100 + 100) / 2

    # add enough points to bucket with most capacity
    key = list(est.filtered_points.buckets)[0]
    for _ in range(est.min_points_total - len(est.filtered_points)):
      est.filtered_points.add_point((key[0] + key[1]) / 2.0, 0.0)

    msg = est.get_msg()
    assert msg.lateralTorqueParameters.calPerc == 100
