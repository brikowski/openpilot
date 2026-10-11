from types import SimpleNamespace

import numpy as np

import extract
from extract import plan_to_control, select_lead_field


def test_plan_to_control_holds_published_target_until_next_plan():
  grid = np.array([-0.01, 0.01, 0.02, 0.03, 0.04])
  plan_t = np.array([0.00, 0.03])
  a_target = np.array([-0.40, 0.80])

  np.testing.assert_array_equal(plan_to_control(grid, plan_t, a_target), [np.nan, -0.40, -0.40, 0.80, 0.80])
  assert np.isnan(plan_to_control(grid, [], [])).all()


def test_model_commands_and_learned_boost_follow_publication_without_blending(monkeypatch):
  from openpilot.cereal import log

  messages = []
  for i in range(100):
    m = log.Event.new_message(logMonoTime=1_000_000_000 + i * 10_000_000)
    m.init('carControl')
    messages.append(m)
  for timestamp, accel, curvature in ((1_010_000_000, -.4, .001), (1_060_000_000, .8, .003)):
    m = log.Event.new_message(logMonoTime=timestamp)
    action = m.init('modelV2').action
    action.desiredAcceleration, action.desiredCurvature = accel, curvature
    messages.append(m)
  for timestamp, boost in ((1_020_000_000, .00125), (1_070_000_000, .0025), (1_120_000_000, None)):
    m = log.Event.new_message(logMonoTime=timestamp)
    plan = m.init('longitudinalPlan')
    plan.aTarget = -.2
    if boost is not None:
      plan.accelBoost = boost
    messages.append(m)
  monkeypatch.setattr(extract, 'LogReader', lambda _: iter(sorted(messages, key=lambda m: m.logMonoTime)))
  monkeypatch.setattr(extract, '_segments', lambda _: ('synthetic', ['rlog']))
  out = extract._build('synthetic')
  assert np.isnan(out['e2e_accel'][0]) and np.isnan(out['des_curvature'][0])
  np.testing.assert_allclose(out['e2e_accel'][1:8], [-.4] * 5 + [.8] * 2)
  np.testing.assert_allclose(out['des_curvature'][1:8], [.001] * 5 + [.003] * 2)
  assert np.isnan(out['accel_boost'][:2]).all() and np.isnan(out['atarget'][:2]).all()
  np.testing.assert_allclose(out['accel_boost'][2:12], [.00125] * 5 + [.0025] * 5)
  assert np.all(out['accel_boost'][12:] == 0.)  # Older messages default this schema field to zero.
  np.testing.assert_allclose(out['atarget'][2:], -.2)
  assert not np.any(out['request'])


def test_select_lead_field_follows_published_mpc_source():
  source = np.array([1, 2, 0, 4, 2])
  lead_one = np.array([10., 11., 12., 13., 14.])
  lead_two = np.array([20., 21., 22., 23., 24.])

  selected = select_lead_field(source, lead_one, lead_two)

  np.testing.assert_array_equal(selected[:2], [10., 21.])
  assert np.isnan(selected[2])
  assert np.isnan(selected[3])
  assert selected[4] == 24.


def test_select_lead_field_does_not_substitute_lead_one_for_non_lead_plan():
  selected = select_lead_field(np.array([0]), np.array([10.]), np.array([20.]))

  assert np.isnan(selected[0])


def test_extract_acc_parser_sees_only_bus_one_acc_control(monkeypatch):
  updates = []

  class FakeParser:
    def __init__(self, *_args):
      self.vl = {"ACC_CONTROL": {"GAS_COMMAND": 123, "ACCEL_COMMAND": 0.5, "BRAKE_REQUEST": 0}}

    def update(self, batches):
      updates.extend(batches)
      return {extract.ACC_CONTROL_ADDR}

  def msg(t, address, src):
    frame = SimpleNamespace(address=address, dat=b"\x00" * 8, src=src)
    return SimpleNamespace(logMonoTime=t, which=lambda: "sendcan", sendcan=[frame])

  monkeypatch.setattr("opendbc.can.parser.CANParser", FakeParser)
  monkeypatch.setattr(extract, "LogReader", lambda _paths: iter([
    msg(1, 0xE4, 0), msg(2, 0xE4, 1),
    msg(3, extract.ACC_CONTROL_ADDR, 0), msg(4, extract.ACC_CONTROL_ADDR, 1),
  ]))

  _, _, _, _, _, sc, _, _, _, _ = extract._decode(["synthetic-rlog"])

  assert len(updates) == 1
  assert updates[0][0] == 4
  assert updates[0][1][0][:3] == (extract.ACC_CONTROL_ADDR, b"\x00" * 8, 1)
  assert sc["t"] == [4e-9]
  assert sc["gas"] == [123.]


def test_received_can_keeps_independent_verified_updates_and_missing_signals(monkeypatch):
  from opendbc.can import CANPacker
  packer = CANPacker(extract.ODYSSEY_PT_DBC)

  def event(t, frames):
    return SimpleNamespace(logMonoTime=t, which=lambda: "can",
                           can=[SimpleNamespace(address=a, dat=d, src=b) for a, d, b in frames])

  gear = packer.make_can_msg('GEARBOX_AUTO', 1, {'TRANS_TARGET_GEAR': 7, 'TRANS_SHIFT_ACTIVITY': 119, 'COUNTER': 1})
  torque = packer.make_can_msg('GAS_PEDAL_2', 1, {'ENGINE_TORQUE_ESTIMATE': 90, 'ENGINE_TORQUE_REQUEST': 110, 'COUNTER': 1})
  bad_gear = (gear[0], gear[1][:-1] + bytes([gear[1][-1] ^ 1]), 1)
  messages = [event(1_000_000_000, [gear]), event(1_010_000_000, [torque]),
              event(1_020_000_000, [(gear[0], gear[1], 0)]), event(1_030_000_000, [bad_gear])]
  monkeypatch.setattr(extract, 'LogReader', lambda _: iter(messages))
  rx = extract._decode(['synthetic-rlog'])[6]
  assert rx['gear'] == {'t': [1.], 'value': [7.]}
  assert rx['shift_activity'] == {'t': [1.], 'value': [119.]}
  assert rx['engine_torque_request'] == {'t': [1.01], 'value': [110.]}
  assert rx['eps_output_disabled'] == {'t': [], 'value': []}


def test_received_can_cache_holds_samples_and_reports_age_without_future_values(monkeypatch):
  def control(t):
    a = SimpleNamespace(accel=0., longControlState='pid', torque=0.)
    c = SimpleNamespace(actuators=a, orientationNED=[], longActive=True, latActive=False)
    return SimpleNamespace(logMonoTime=t, which=lambda: 'carControl', carControl=c)

  from opendbc.can import CANPacker
  packer = CANPacker(extract.ODYSSEY_PT_DBC)
  messages = [control(1_000_000_000 + i * 10_000_000) for i in range(100)]
  for t, activity, counter in ((1_020_000_000, 110, 1), (1_040_000_000, 102, 2)):
    a, d, b = packer.make_can_msg('GEARBOX_AUTO', 1, {'TRANS_TARGET_GEAR': 6, 'TRANS_SHIFT_ACTIVITY': activity, 'COUNTER': counter})
    messages.append(SimpleNamespace(logMonoTime=t, which=lambda: 'can', can=[SimpleNamespace(address=a, dat=d, src=b)]))
  monkeypatch.setattr(extract, 'LogReader', lambda _: iter(sorted(messages, key=lambda m: m.logMonoTime)))
  monkeypatch.setattr(extract, '_segments', lambda _: ('synthetic', ['rlog']))
  out = extract._build('synthetic')
  assert np.isnan(out['shift_activity'][0])
  np.testing.assert_array_equal(out['shift_activity'][2:5], [110., 110., 102.])
  np.testing.assert_allclose(out['shift_activity_age'][2:5], [0., .01, 0.], atol=1e-8)
  assert out['shift_activity_age'][-1] > .9
  assert np.isnan(out['eps_motor_torque']).all()
  assert np.isnan(out['eps_motor_torque_age']).all()


def test_cruise_setpoint_changes_do_not_invent_overspeed_before_publication(monkeypatch):
  from opendbc.car.structs import car

  messages = [SimpleNamespace(logMonoTime=1_000_000_000 + i * 10_000_000,
                             which=lambda: 'carControl', carControl=car.CarControl.new_message())
              for i in range(100)]
  for timestamp, setpoint in ((1_010_000_000, 80.), (1_050_000_000, 60.)):
    messages.append(SimpleNamespace(logMonoTime=timestamp, which=lambda: 'carState',
                                   carState=car.CarState.new_message(vCruise=setpoint, vEgo=20.)))
  monkeypatch.setattr(extract, 'LogReader', lambda _: iter(sorted(messages, key=lambda m: m.logMonoTime)))
  monkeypatch.setattr(extract, '_segments', lambda _: ('synthetic', ['rlog']))
  out = extract._build('synthetic')
  assert np.isnan(out['vcruise'][0])
  np.testing.assert_array_equal(out['vcruise'][1:6], [80., 80., 80., 80., 60.])
  assert np.all(out['vego'][1:5] < out['vcruise'][1:5] / 3.6)
  assert out['vego'][5] > out['vcruise'][5] / 3.6
