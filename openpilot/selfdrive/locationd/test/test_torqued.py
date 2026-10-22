import numpy as np

from opendbc.car import gen_empty_fingerprint
from opendbc.car.honda.hondacan import CanBus as HondaCanBus
from opendbc.car.honda.interface import CarInterface as HondaInterface
from opendbc.car.honda.values import CAR
from opendbc.car.structs import car
from openpilot.cereal import log, messaging
from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.torqued import TorqueEstimator


class TestTorqued(OpenpilotTestCase):
  def test_expanded_range_preserves_physical_learning_samples_and_fit(self):
    current = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    stock = current.as_reader().as_builder()
    stock.carFingerprint = 'mock'
    stock.lateralTuning.torque.latAccelFactor = .9
    stock.lateralTuning.torque.friction = .2
    baseline, candidate = (TorqueEstimator(cp) for cp in (stock, current))
    rng = np.random.default_rng(42)
    for torque, noise in zip(np.linspace(-.8, .8, 20000), rng.normal(0., .03, 20000), strict=True):
      response = .9 * torque + .1 * np.sign(torque) + noise
      baseline.filtered_points.add_point(torque, response)
      candidate.filtered_points.add_point(torque / 1.5, response)
    assert baseline.filtered_points.is_valid() and candidate.filtered_points.is_valid()
    for old, new in zip(baseline.filtered_points.buckets.values(), candidate.filtered_points.buckets.values(), strict=True):
      np.testing.assert_allclose(old.arr[:, 0], new.arr[:, 0] * 1.5, atol=1e-14)
      np.testing.assert_array_equal(old.arr[:, 1:], new.arr[:, 1:])
    baseline.filtered_points._rng = np.random.default_rng(1)
    candidate.filtered_points._rng = np.random.default_rng(1)
    factor, offset, friction = baseline.estimate_params()
    np.testing.assert_allclose(candidate.estimate_params(), [factor * 1.5, offset, friction / 1.5], atol=1e-14)
    published = candidate.get_msg(with_points=True).lateralTorqueParameters
    np.testing.assert_allclose(np.asarray(published.points)[:, 0], candidate.filtered_points.get_points()[:, 0], atol=1e-7)

  def test_minimum_learning_torque_remains_in_physical_counts(self):
    cp = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    for count in (-52, -50, 50, 52):
      est = TorqueEstimator(cp)
      for key in ('carControl_t', 'carOutput_t', 'carState_t'):
        est.raw_points[key].extend(np.linspace(0., 5., est.hist_len))
      est.raw_points['lat_active'].extend([True] * est.hist_len)
      est.raw_points['steer_override'].extend([False] * est.hist_len)
      est.raw_points['vego'].extend([20.] * est.hist_len)
      est.raw_points['steer_torque'].extend([count / 3840] * est.hist_len)
      event = messaging.new_message('deviceMotion').deviceMotion
      event.timestamp = 5_000_000_000
      event.inputsOK = event.sensorsOK = event.posenetOK = True
      for name in ('orientationNED', 'velocityDevice', 'accelerationDevice', 'angularVelocityDevice'):
        value = getattr(event, name)
        value.z = .01 if name == 'angularVelocityDevice' else 0.
        value.xStd = value.yStd = value.zStd = .01
        value.valid = True
      est.handle_log(5., 'deviceMotion', event)
      assert len(est.filtered_points) == int(abs(count) == 52)

  def test_previous_fit_version_cannot_restore_with_matching_seed(self):
    cp = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    self.cache_params(cp)
    params = Params()
    with log.Event.from_bytes(params.get('LiveTorqueParameters')) as reader:
      cache = reader.as_builder()
    cache.lateralTorqueParameters.version = 1
    params.put('LiveTorqueParameters', cache.to_bytes(), block=True)
    assert len(TorqueEstimator(cp).filtered_points) == 0
    assert params.get('LiveTorqueParameters') is None

  @staticmethod
  def cache_params(CP):
    params = Params()
    cp_bytes = CP.to_bytes()
    params.put("CarParamsPrevRoute", cp_bytes, block=True)
    msg = messaging.new_message('lateralTorqueParameters')
    torque = msg.lateralTorqueParameters
    torque.version = TorqueEstimator(CP).version
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

  def test_odyssey_expanded_range_rejects_stock_normalization_cache(self):
    current = HondaInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], True, False, False)
    previous = current.as_reader().as_builder()
    previous.lateralTuning.torque.latAccelFactor = .9
    previous.lateralTuning.torque.friction = .2
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
