import numpy as np
import pytest

from opendbc.car import Bus, DT_CTRL, gen_empty_fingerprint, structs
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.carstate import CarState
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, DBC
from opendbc.car.vehicle_model import VehicleModel
from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque


@pytest.mark.parametrize('speed', [5., 15., 30.])
@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('econ', [False, True])
@pytest.mark.parametrize('alpha_long', [False, True])
def test_count_gain_below_stock_cap_and_added_headroom(speed, direction, econ, alpha_long):
  """Exercise the controller-to-wire path with identical physical state and requests."""
  candidate = CarInterface.get_params(CAR.HONDA_ODYSSEY_5G_MMR, gen_empty_fingerprint(), [], alpha_long, False, False)
  stock = candidate.as_reader().as_builder()
  stock.lateralTuning.torque.latAccelFactor = .9
  stock.lateralTuning.torque.friction = .2
  arms = []
  for cp in (stock, candidate):
    ci = CarInterface(cp)
    wire = CarController({Bus.pt: DBC[cp.carFingerprint][Bus.pt]}, cp)
    state = CarState(cp)
    state.update(state.get_can_parsers(cp))
    state.out = structs.CarState(vEgo=speed, canValid=True, ecoModeValid=True, ecoMode=econ)
    arms.append((LatControlTorque(cp.as_reader(), ci, DT_CTRL), VehicleModel(cp), wire, state))
  arms[0][2].params.STEER_MAX = 2560
  arms[0][2].params.STEER_DELTA_UP = arms[0][2].params.STEER_DELTA_DOWN = 3
  vp = log.VehicleParameters(roll=0., angleOffsetDeg=.1)
  trace = []
  for frame, demand in enumerate(np.r_[.15 + .01 * np.sin(np.arange(300) / 30), np.full(150, 2.)]):
    counts = []
    for lat, vm, wire, state in arms:
      observed = 0. if frame < 35 else direction * .15
      state.out.steeringAngleDeg = float(np.degrees(vm.get_steer_from_curvature(-observed / speed**2, speed, vp.roll)) + .1)
      torque, _, _ = lat.update(True, state.out, vm, vp, False, direction * demand / speed**2, False, .35)
      cc = structs.CarControl(enabled=True, latActive=True)
      cc.actuators.torque = float(torque)
      output, sends = wire.update(cc.as_reader(), state, frame * 10_000_000)
      raw = next(dat for addr, dat, _ in sends if addr == 0xE4)
      count = int.from_bytes(raw[:2], 'big', signed=True)
      assert count == output.torqueOutputCan
      assert output.torque == pytest.approx(-count / wire.params.STEER_MAX, abs=1e-7)
      counts.append(count)
    trace.append(counts)
  trace = np.asarray(trace)
  assert np.max(np.abs(trace[:300, 0] - trace[:300, 1])) <= 1
  assert np.max(np.abs(trace[:300])) < 2560
  assert abs(trace[-1, 0]) == 2560
  assert abs(trace[-1, 1]) == 3840
  assert np.max(np.abs(np.diff(trace, axis=0))) <= 77
