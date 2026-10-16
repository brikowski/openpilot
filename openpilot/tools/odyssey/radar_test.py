"""Parked, read-only Honda ECU capture. Started locally from Developer settings."""
import argparse
import bz2
import datetime
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from opendbc.can import CANDefine, CANParser
from opendbc.car import Bus, structs
from opendbc.car.honda.values import CAR, DBC
from opendbc.car.uds import UdsClient, MessageTimeoutError, NegativeResponseError
from openpilot.cereal import messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.selfdrive.pandad import can_capnp_to_list, can_list_to_can_capnp

ACTIVE = "OdysseyRadarTest"
STOP = "OdysseyRadarTestStop"
STATUS = "OdysseyRadarTestStatus"
ECUS = (("radar", 0x18DAB0F1), ("camera", 0x18DAB5F1))
# F112 is Honda's existing firmware query. F191 is a standard hardware-number read;
# a negative response or timeout is evidence, not proof the ECU lacks a feature.
DIDS = (0xF181, 0xF112, 0xF191)
MESSAGES = (("GEARBOX_AUTO", 50), ("SCM_FEEDBACK", 10), ("ENGINE_DATA", 100),
            ("WHEEL_SPEEDS", 50), ("STANDSTILL", 50), ("ACC_HUD", 10), ("ACC_CONTROL", 50))
ROAD_PROCESSES = {"card", "controlsd", "selfdrived", "joystickd", "maneuversd", "lateral_maneuversd"}


class TestStopped(Exception):
  pass


def supported(params):
  value = params.get("CarParamsPersistent")
  if value is None:
    return False
  try:
    with structs.CarParams.from_bytes(value) as cp:
      return cp.carFingerprint == CAR.HONDA_ODYSSEY_5G_MMR
  except Exception:
    return False


def start_allowed(params, sm, offroad):
  return offroad and not params.get_bool(ACTIVE) and supported(params) and ignition_off(sm, time.monotonic())


def request_start(params, sm, offroad):
  if not start_allowed(params, sm, offroad):
    return False
  params.put_bool(STOP, False, block=True)
  params.put(STATUS, {"phase": "requested", "message": "Preparing parked capture...", "monotonic": time.monotonic()}, block=True)
  params.put_bool(ACTIVE, True, block=True)
  return True


def parked_error(cp, now):
  for message, _ in MESSAGES:
    timestamp = next(iter(cp.ts_nanos[message].values())) / 1e9
    if not 0 <= now - timestamp <= 0.5:
      return f"Missing or stale {message}"
  if not cp.can_valid:
    return "Invalid vehicle CAN"
  if CANDefine(cp.dbc_name).dv["GEARBOX_AUTO"]["GEAR_SHIFTER"].get(cp.vl["GEARBOX_AUTO"]["GEAR_SHIFTER"]) != "P":
    return "Vehicle must remain in Park"
  if not cp.vl["SCM_FEEDBACK"]["PARKING_BRAKE_ON"]:
    return "Set the parking brake"
  # Odyssey wheel reporting has a 2 km/h floor. Transmission speed and Park are
  # independent stationary guards; do not interpret that floor as actual motion.
  if cp.vl["ENGINE_DATA"]["XMISSION_SPEED"] > 0 or any(v > 2.0 for k, v in cp.vl["WHEEL_SPEEDS"].items() if k.startswith("WHEEL_SPEED_")):
    return "Vehicle motion detected"
  if any(cp.vl["STANDSTILL"][k] for k in ("BRAKE_ERROR_1", "BRAKE_ERROR_2")):
    return "Honda brake fault reported; turn the vehicle off"
  if any(cp.vl["ACC_HUD"][k] for k in ("ACC_PROBLEM", "FCM_PROBLEM")):
    return "Honda ACC/FCM fault reported; turn the vehicle off"
  return None


def control_error(sm, now):
  for service in ("pandaStates", "managerState", "deviceState"):
    if not fresh(sm, service, now, 2.5):
      return f"Missing or stale {service}"
  if sm["deviceState"].started:
    return "OpenPilot must remain offroad"
  processes = {p.name: p.running for p in sm["managerState"].processes}
  if not processes.get("pandad") or any(processes.get(name, True) for name in ROAD_PROCESSES):
    return "Waiting for OpenPilot controllers to stop"
  pandas = sm["pandaStates"]
  if len(pandas) != 1 or pandas[0].pandaType == "unknown":
    return "One connected Panda is required"
  ps = pandas[0]
  if ps.safetyModel != structs.CarParams.SafetyModel.elm327 or ps.safetyParam != 1 or ps.controlsAllowed:
    return "Waiting for diagnostic-only Panda mode"
  if ps.faults or ps.heartbeatLost or ps.rxBufferOverflow or ps.txBufferOverflow or ps.safetyTxBlocked:
    return "Panda fault, overflow, heartbeat loss or rejected transmission"
  if ps.harnessStatus == "notConnected" or any(s.busOff or s.totalRxLostCnt or s.totalTxLostCnt for s in (ps.canState0, ps.canState1, ps.canState2)):
    return "Panda harness or CAN transport fault"
  return None


def ignition_off(sm, now):
  pandas = sm["pandaStates"]
  return (fresh(sm, "pandaStates", now, 0.5) and len(pandas) == 1
          and pandas[0].pandaType != "unknown" and not (pandas[0].ignitionLine or pandas[0].ignitionCan))


def fresh(sm, service, now, limit):
  return (sm.valid[service] and 0 <= now - sm.recv_time[service] < limit
          and 0 <= now - sm.logMonoTime[service] / 1e9 < limit)


class Capture:
  def __init__(self, params, folder):
    self.params = params
    self.folder = folder
    self.sm = messaging.SubMaster(["pandaStates", "managerState", "deviceState"])
    self.can = messaging.sub_sock("can", timeout=20)
    self.sendcan = messaging.pub_sock("sendcan")
    self.cp = CANParser(DBC[CAR.HONDA_ODYSSEY_5G_MMR][Bus.pt], list(MESSAGES), 1)
    self.log = bz2.open(folder / "traffic.rlog.bz2", "wb")
    self.events = (folder / "events.jsonl").open("w")
    self.deadline = time.monotonic() + 300
    self.query_deadline = float("inf")
    self.frames = 0
    self.status_value = {}
    self.last_status = 0

  def status(self, phase, message, **extra):
    value = {"phase": phase, "message": message, "capture": str(self.folder), "frames": self.frames,
             "monotonic": time.monotonic(), **extra}
    self.params.put(STATUS, value, block=True)
    self.status_value = value
    self.last_status = time.monotonic()
    self.events.write(json.dumps(value) + "\n")
    self.events.flush()

  def can_recv(self):
    self.sm.update(0)
    # Preserve original CAN events at full rate, including Panda's TX echoes.
    raw = messaging.drain_sock_raw(self.can, wait_for_one=True)
    for event in raw:
      self.log.write(event)
    packets = can_capnp_to_list(raw)
    self.cp.update(packets)
    for service in self.sm.services:
      if self.sm.updated[service]:
        event = messaging.new_message(service, len(self.sm[service]) if service == "pandaStates" else None)
        event.logMonoTime = self.sm.logMonoTime[service]
        event.valid = self.sm.valid[service]
        setattr(event, service, self.sm[service])
        self.log.write(event.to_bytes())
    self.frames += sum(len(frames) for _, frames in packets)
    if time.monotonic() - self.last_status >= 1 and self.status_value:
      self.status(self.status_value["phase"], self.status_value["message"])
      self.log.flush()
    return [frame for _, frames in packets for frame in frames]

  def guard(self):
    now = time.monotonic()
    if self.params.get_bool(STOP) or not self.params.get_bool(ACTIVE):
      raise TestStopped("Stopped")
    if now >= min(self.deadline, self.query_deadline):
      raise TestStopped("Capture or query time limit reached")
    if error := control_error(self.sm, now) or parked_error(self.cp, now):
      raise TestStopped(error)

  def can_send(self, address, data, bus, **kwargs):
    self.can_recv()
    self.guard()
    if not frame_allowed(address, data, bus):
      raise TestStopped("Rejected a request outside the read-only allowlist")
    event = can_list_to_can_capnp([(address, data, bus)], msgtype="sendcan")
    self.log.write(event)
    self.log.flush()
    self.sendcan.send(event)

  def recv_guarded(self):
    frames = self.can_recv()
    self.guard()
    return frames

  def record(self, duration):
    end = time.monotonic() + duration
    while time.monotonic() < end:
      self.can_recv()
      self.guard()

  def run(self):
    self.status("ignition_off", "Turn the vehicle OFF and keep it off for five seconds.")
    off_since = None
    while True:
      self.can_recv()
      now = time.monotonic()
      if self.params.get_bool(STOP) or now >= self.deadline:
        raise TestStopped("Stopped before the baseline")
      off_since = (off_since or now) if ignition_off(self.sm, now) and not control_error(self.sm, now) else None
      if off_since is not None and now - off_since >= 5:
        break
    self.status("ignition_on", "Turn ignition ON. Stay in Park with parking brake set; do not drive.")
    ready_since = None
    while True:
      self.can_recv()
      now = time.monotonic()
      if self.params.get_bool(STOP) or now >= self.deadline:
        raise TestStopped("Stopped while waiting for parked vehicle")
      error = control_error(self.sm, now) or parked_error(self.cp, now)
      off = ignition_off(self.sm, now)
      message = "Turn ignition ON. Stay in Park with parking brake set." if off else (error or "Confirming parked vehicle...")
      if self.status_value["message"] != message:
        self.status("ignition_on", message)
      ready = not off and not error
      ready_since = (ready_since or now) if ready else None
      if ready_since is not None and now - ready_since >= 2:
        break
    self.status("baseline", "Recording stock CAN baseline. Stay in Park.")
    self.record(10)
    # The stock ACC source must actually be present, not merely a cached CP.
    for name, address in ECUS:
      for did in DIDS:
        self.status("identification", f"Reading {name} identifier {did:04X}. Stay in Park.")
        self.query_deadline = time.monotonic() + 3
        client = UdsClient(SimpleNamespace(can_send=self.can_send, can_recv=self.recv_guarded), address, bus=1,
                           timeout=0.8, response_pending_timeout=0.8)
        try:
          data = client.read_data_by_identifier(did)
          self.status("reply", f"{name} {did:04X}: reply received", ecu=name, did=did, data_hex=data.hex())
        except (MessageTimeoutError, NegativeResponseError) as e:
          self.status("reply", f"{name} {did:04X}: {type(e).__name__}", ecu=name, did=did, error=str(e))
        finally:
          self.query_deadline = float("inf")
    self.status("after_reads", "Recording CAN after identification reads. Stay in Park.")
    self.record(10)
    self.status("complete", "Capture complete. Turn vehicle OFF to exit. CMBS function is not validated.")


def frame_allowed(address, data, bus):
  if bus != 1 or address not in {a for _, a in ECUS} or len(data) != 8:
    return False
  return data == b"\x30\x00\x00\x00\x00\x00\x00\x00" or any(data == bytes([3, 0x22, did >> 8, did & 255, 0, 0, 0, 0]) for did in DIDS)


def provenance(params):
  if not supported(params):
    raise TestStopped("This test is only for a previously identified Bosch Odyssey")
  def git(*args):
    return subprocess.check_output(["git", *args], cwd=BASEDIR, text=True).strip()
  if git("branch", "--show-current") != "ody-op-test" or git("status", "--porcelain"):
    raise TestStopped("A clean ody-op-test installation is required")
  child = git("-C", "opendbc_repo", "rev-parse", "HEAD")
  if child != git("rev-parse", "HEAD:opendbc_repo"):
    raise TestStopped("opendbc revision differs from its gitlink")
  return {"parent": git("rev-parse", "HEAD"), "opendbc": child,
          "alpha_long_enabled": params.get_bool("AlphaLongitudinalEnabled"), "ecus": ECUS, "dids": DIDS}


def recover(params, sm):
  # Never resume Alpha Long while ignition remains on, including after cancellation.
  off_since = None
  last_status = 0
  while True:
    sm.update(100)
    now = time.monotonic()
    off_since = (off_since or now) if ignition_off(sm, now) else None
    if now - last_status >= 1:
      params.put(STATUS, {**(params.get(STATUS) or {}), "monotonic": now}, block=True)
      last_status = now
    if off_since is not None and now - off_since >= 5:
      status = params.get(STATUS) or {}
      params.put(STATUS, {**status, "message": "Test exited with ignition OFF. Ready for normal startup.",
                          "result": status.get("message", ""),
                          "monotonic": now}, block=True)
      params.put_bool(ACTIVE, False, block=True)
      break


def main():
  params = Params()
  os.umask(0o077)
  folder = Path("/data/odyssey/radar-tests") / datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
  capture = None
  try:
    folder.mkdir(parents=True)
    (folder / "source.json").write_text(json.dumps(provenance(params), indent=2) + "\n")
    capture = Capture(params, folder)
    if params.get_bool(STOP) or (params.get(STATUS) or {}).get("phase") != "requested":
      raise TestStopped("Interrupted test. Turn vehicle OFF to exit.")
    capture.run()
  except Exception as e:
    message = f"{e}. Turn vehicle OFF to exit."
    if capture is not None:
      capture.status("stopped", message)
    else:
      params.put(STATUS, {"phase": "stopped", "message": message}, block=True)
  finally:
    params.put_bool(STOP, True, block=True)
    if capture is not None:
      capture.log.close()
      capture.events.close()
    recover(params, capture.sm if capture is not None else messaging.SubMaster(["pandaStates"]))


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--monitor", action="store_true", help="watch the UI-started test over existing SSH")
  parser.add_argument("--stop", action="store_true", help="stop reads; hold offroad until ignition is off")
  args = parser.parse_args()
  params = Params()
  if args.stop:
    params.put_bool(STOP, True, block=True)
  if args.monitor:
    previous = None
    while True:
      status = {"active": params.get_bool(ACTIVE), "status": params.get(STATUS)}
      if status != previous:
        print(json.dumps(status), flush=True)
        previous = status
      if not params.get_bool(ACTIVE):
        break
      time.sleep(0.5)
  elif not args.stop:
    parser.error("Start the test locally from OpenPilot Developer settings")
