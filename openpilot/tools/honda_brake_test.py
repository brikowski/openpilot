"""Guided, parked-only Odyssey brake diagnostics. Never sends actuator commands."""
from pathlib import Path
import signal
import time

from opendbc.car.honda.values import CAR
from opendbc.car import structs
from openpilot.cereal import log, messaging
from openpilot.common.params import Params
from openpilot.tools.honda_brake_capture import Capture, SAFETY, record_metadata, require_exclusive_panda

MODE = "HondaBrakeTest"
STATUS = "HondaBrakeTestStatus"


def can_request_test(cp, sm):
  if cp is None or cp.carFingerprint != CAR.HONDA_ODYSSEY_5G_MMR:
    return False
  def fresh(service):
    return (sm.valid[service] and sm.alive[service] and
            0 <= time.monotonic_ns() - sm.logMonoTime[service] < 1_000_000_000)
  states = sm['pandaStates']
  if not fresh('pandaStates') or not states or any(p.controlsAllowed or p.faults or p.pandaType == 0 for p in states):
    return False
  if not any(p.ignitionLine or p.ignitionCan for p in states):
    return True
  cs = sm['carState']
  return (fresh('carState') and fresh('carControl') and not sm['carControl'].enabled and
          cs.canValid and not cs.gasPressed and cs.gearShifter == structs.CarState.GearShifter.park and
          cs.vEgoRaw == 0 and cs.vEgo == 0 and cs.parkingBrake)


def manage_brake_test(params, sm, procs):
  """Transfer Panda ownership only with fresh ignition-off evidence, in both directions.

  Persist active ownership across manager restarts; a crashed test must not start card.
  """
  mode = params.get(MODE)
  states = sm['pandaStates']
  off = (sm.valid['pandaStates'] and sm.alive['pandaStates'] and len(states) > 0 and
         0 <= time.monotonic_ns() - sm.logMonoTime['pandaStates'] < 1_000_000_000 and
         all(p.pandaType != 0 and not (p.ignitionLine or p.ignitionCan or p.controlsAllowed) for p in states))
  if mode == 'requested' and off and not sm['deviceState'].started:
    params.put(MODE, 'active', block=True)
    procs['pandad'].stop(block=True)
    mode = 'active'
  elif mode == 'restore' and off and not sm['deviceState'].started:
    procs['honda_brake_test'].stop(block=True)
    params.remove(MODE)
    mode = None
  return mode not in (None, 'requested')


def request_test(params):
  params.put(STATUS, {'title': 'Brake diagnostic test armed',
                      'instruction': 'Turn the car fully off. Wait for the next instruction before turning it on.'}, block=True)
  params.put(MODE, 'requested', block=True)


def cancel_test(params):
  if params.get(MODE) == 'requested':
    params.remove(MODE)
  elif params.get(MODE):
    params.put(MODE, 'cancel', block=True)


class GuidedTest:
  def __init__(self, panda, output, params):
    self.panda, self.params = panda, params
    self.capture = Capture(panda, output)
    self.pm = messaging.PubMaster(['pandaStates', 'peripheralState'])
    self.sm = messaging.SubMaster(['deviceState'])
    self.panda_type = panda.get_type()[0]
    self.last_health = 0.
    self.current_prompt = None
    self.last_prompt_time = 0.

  def prompt(self, title, instruction):
    changed = (title, instruction) != self.current_prompt
    if not changed and time.monotonic() - self.last_prompt_time < 1:
      return
    self.params.put(STATUS, {'title': title, 'instruction': instruction, 'mono_ns': time.monotonic_ns()}, block=True)
    if changed:
      self.capture.record('instruction', title=title, instruction=instruction)
    self.capture.output.flush()
    self.current_prompt = (title, instruction)
    self.last_prompt_time = time.monotonic()

  def health(self):
    h = self.panda.health()
    now = time.monotonic()
    if now - self.last_health >= 0.1:
      msg = messaging.new_message('pandaStates', 1, valid=True)
      msg.pandaStates[0] = {'pandaType': self.panda_type, 'ignitionLine': h['ignition_line'],
                           'ignitionCan': h['ignition_can'], 'controlsAllowed': h['controls_allowed'],
                           'safetyModel': h['safety_mode'], 'harnessStatus': h['car_harness_status'],
                           'faults': [name for name, bit in log.PandaState.FaultType.schema.enumerants.items()
                                      if h['faults'] & (1 << bit)]}
      self.pm.send('pandaStates', msg)
      peripheral = messaging.new_message('peripheralState', valid=True)
      peripheral.peripheralState = {'pandaType': self.panda_type, 'voltage': h['voltage'], 'current': h['current']}
      self.pm.send('peripheralState', peripheral)
      self.sm.update(0)
      if self.sm.valid['deviceState'] and self.sm.alive['deviceState']:
        self.panda.set_fan_power(self.sm['deviceState'].fanSpeedPercentDesired)
      self.last_health = now
      if self.current_prompt:
        self.prompt(*self.current_prompt)
    return h

  def wait_ignition(self, on):
    while True:
      if on and self.params.get(MODE) != 'active':
        raise RuntimeError('test cancelled')
      h = self.health()
      if h['controls_allowed'] or h['safety_mode'] != SAFETY.noOutput:
        raise RuntimeError('unexpected Panda safety state')
      if bool(h['ignition_line'] or h['ignition_can']) == on:
        return
      self.panda.can_recv()
      time.sleep(0.02)

  def sequence(self):
    c = self.capture
    cp_bytes = self.params.get('CarParamsPersistent')
    if not cp_bytes:
      raise RuntimeError('no identified Odyssey')
    with structs.CarParams.from_bytes(cp_bytes) as cp:
      if cp.carFingerprint != CAR.HONDA_ODYSSEY_5G_MMR:
        raise RuntimeError('this test is only for the Bosch Odyssey')
    # Revalidate ownership after a process restart; never resume a partial pedal sequence.
    if self.health()['ignition_line'] or self.health()['ignition_can']:
      raise RuntimeError('test started with ignition on; turn off before retrying')
    c.restore()
    self.prompt('Ready for the brake test', 'Keep Park and the parking brake set. Turn the car on and stay parked.')
    self.wait_ignition(True)
    self.prompt('Checking the car', 'Stay in Park with the parking brake set. Keep your foot off the accelerator.')
    c.qualify()
    for address in (0x18DA28F1, 0x18DA2BF1):
      c.read(address, 0xF181)
    c.read(0x18DA28F1, 0x4005)
    # Pressure units are unqualified. Use the native pedal switch for readiness, not an invented pressure target.
    for index, (instruction, pressed) in enumerate((
      ('Release the brake pedal.', False),
      ('Press the brake lightly and hold it steady.', True),
      ('Release the brake pedal.', False),
      ('Press the brake a little more firmly and hold it steady.', True),
      ('Release the brake pedal.', False),
    ), 1):
      self.prompt(f'Step {index} of 5', instruction + ' Keep Park and the parking brake set.')
      ready_since = None
      samples = 0
      next_read = 0.
      deadline = time.monotonic() + 30
      while time.monotonic() < deadline:
        if self.params.get(MODE) != 'active':
          raise RuntimeError('test cancelled')
        self.health()
        c.can_recv()
        c.check(SAFETY.noOutput)
        ready = bool(c.cp.vl['POWERTRAIN_DATA']['BRAKE_PRESSED']) == pressed
        if not ready:
          ready_since, samples = None, 0
        else:
          if ready_since is None:
            ready_since = time.monotonic()
          if time.monotonic() >= next_read:
            c.read(0x18DA28F1, 0x4005)
            if bool(c.cp.vl['POWERTRAIN_DATA']['BRAKE_PRESSED']) != pressed:
              ready_since, samples = None, 0
              continue
            samples += 1
            next_read = time.monotonic() + 1
          remaining = max(0, 5 - int(time.monotonic() - ready_since))
          self.prompt(f'Step {index} of 5 — hold {remaining}s', instruction)
          if time.monotonic() - ready_since >= 5 and samples >= 4:
            break
        time.sleep(0.02)
      else:
        raise TimeoutError('pedal step timed out')

  def run(self):
    try:
      self.sequence()
      self.prompt('Brake test complete — data saved', 'Turn the car fully off. Wait for the normal screen, then restart normally.')
    except Exception as e:
      self.capture.record('error', exception=type(e).__name__, error=str(e))
      self.prompt('Brake test stopped — partial data saved', f'{e}. Turn the car fully off; wait for the normal screen before restarting.')
    finally:
      self.capture.active = False
      self.capture.restore()
    self.wait_ignition(False)
    self.params.put(MODE, 'restore', block=True)
    # Manager stops this process before allowing pandad/card to return.
    while True:
      self.health()
      self.panda.can_recv()
      time.sleep(0.02)


def main():
  from panda import Panda
  params = Params()
  def interrupt(*_):
    raise KeyboardInterrupt
  signal.signal(signal.SIGTERM, interrupt)
  require_exclusive_panda()
  directory = Path('/data/media/0/honda-brake-tests')
  directory.mkdir(parents=True, exist_ok=True)
  path = directory / f'{time.time_ns()}.jsonl'
  with path.open('x') as output, Panda() as panda:
    record_metadata(output)
    test = GuidedTest(panda, output, params)
    try:
      test.run()
    finally:
      test.capture.restore()


if __name__ == '__main__':
  main()
