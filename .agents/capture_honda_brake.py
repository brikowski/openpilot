#!/usr/bin/env python3
"""Capture parked Odyssey brake diagnostics and native CAN using exclusive Panda access.

Stop openpilot before running; require ignition on, Park and parking brake applied. Restart afterward.
Write the JSONL outside the checkout. CAN times are host batch reception times; diagnostic
start/end times bracket each read. Returned/rejected TX retain their Panda source flags.
Only firmware identification and VSA 22 4005 are read, without changing ECU sessions.
The pressure response remains raw: its units and broadcast equivalents need qualification.
Reference: https://github.com/OBDb/Honda-Odyssey/blob/f492b26f38adac5a454222c8793b6307332d831d/signalsets/v3/default.json
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from opendbc.can import CANDefine, CANParser
from opendbc.car import Bus, structs
from opendbc.car.honda.values import CAR, DBC
from opendbc.car.uds import UdsClient

ROOT = Path(__file__).resolve().parents[1]
DBC_NAME = DBC[CAR.HONDA_ODYSSEY_5G_MMR][Bus.pt]
SAFETY = structs.CarParams.SafetyModel
GUARD_SIGNALS = {"ENGINE_DATA": "XMISSION_SPEED", "WHEEL_SPEEDS": "WHEEL_SPEED_FL", "GEARBOX_AUTO": "GEAR_SHIFTER"}
READS = {(0x18DA28F1, 0xF181), (0x18DA2BF1, 0xF181), (0x18DA28F1, 0x4005)}


def require_exclusive_panda():
  if subprocess.run(["pidof", "pandad"], capture_output=True).returncode != 1:
    raise RuntimeError("stop openpilot/pandad before this capture")


class Capture:
  def __init__(self, panda, output):
    self.panda, self.output = panda, output
    self.cp = CANParser(DBC_NAME, [(name, 0) for name in GUARD_SIGNALS], 1)
    self.shifter = CANDefine(DBC_NAME).dv["GEARBOX_AUTO"]["GEAR_SHIFTER"]
    self.active = False
    self.read_deadline_ns = 0

  def record(self, kind, **data):
    self.output.write(json.dumps({"type": kind, "mono_ns": time.monotonic_ns(), **data}) + "\n")

  def parked(self):
    now = time.monotonic_ns()
    fresh = all(0 < self.cp.ts_nanos[msg][signal] <= now and
                now - self.cp.ts_nanos[msg][signal] <= 250_000_000
                for msg, signal in GUARD_SIGNALS.items())
    return (self.cp.can_valid and fresh and
            self.shifter.get(self.cp.vl["GEARBOX_AUTO"]["GEAR_SHIFTER"]) == "P" and
            self.cp.vl["ENGINE_DATA"]["XMISSION_SPEED"] == 0 and
            all(self.cp.vl["WHEEL_SPEEDS"][f"WHEEL_SPEED_{wheel}"] == 0 for wheel in ("FL", "FR", "RL", "RR")))

  def check(self, mode):
    health = self.panda.health()
    if (not self.parked() or health["safety_mode"] != mode or health["controls_allowed"] or
        health["faults"] or not (health["ignition_line"] or health["ignition_can"])):
      raise RuntimeError("require fresh valid stationary Park, ignition on and expected inactive safety mode")

  def can_recv(self):
    frames = self.panda.can_recv()
    received_ns = time.monotonic_ns()
    if self.read_deadline_ns and received_ns > self.read_deadline_ns:
      raise TimeoutError("diagnostic read exceeded one second")
    if frames:
      self.record("can", received_ns=received_ns,
                  frames=[[address, bytes(data).hex(), bus] for address, data, bus in frames])
    if self.active and not self.parked():
      raise RuntimeError("stationary Park or fresh valid CAN lost")
    if any(bus == 1 and address in self.cp.addresses and len(data) != self.cp.message_states[address].size
           for address, data, bus in frames):
      raise RuntimeError("invalid state frame length")
    self.cp.update([(received_ns, frames)])
    if self.active and not self.parked():
      raise RuntimeError("stationary Park or fresh valid CAN lost")
    return frames

  def can_send(self, address, data, bus, **kwargs):
    allowed = {bytes.fromhex("0322") + did.to_bytes(2, "big") + bytes(4)
               for addr, did in READS if addr == address}
    allowed.add(bytes.fromhex("3000000000000000"))
    if bus != 1 or address not in {addr for addr, _ in READS} or bytes(data) not in allowed:
      raise RuntimeError("only the documented read requests and ISO-TP flow control are permitted")
    require_exclusive_panda()
    self.check(SAFETY.elm327)
    self.record("tx", address=address, data_hex=bytes(data).hex(), bus=bus)
    self.panda.can_send(address, data, bus, **kwargs)

  def read(self, address, did):
    started_ns = time.monotonic_ns()
    self.read_deadline_ns = started_ns + 1_000_000_000
    try:
      data = UdsClient(self, address, bus=1, timeout=0.5, response_pending_timeout=1).read_data_by_identifier(did)
    finally:
      self.read_deadline_ns = 0
    self.record("uds", started_ns=started_ns, address=address, did=did, data_hex=data.hex())
    self.output.flush()
    if did == 0x4005 and len(data) != 56:
      raise RuntimeError("pressure response differs from the public reference; raw bytes retained")


def capture(panda, output, seconds):
  c = Capture(panda, output)
  require_exclusive_panda()
  if panda.health()["safety_mode"] == SAFETY.silent:
    panda.set_safety_mode(SAFETY.noOutput)  # Receive CAN after the stopped manager's heartbeat expires.
  panda.can_clear(0xFFFF)  # Host reception time cannot date frames queued before this capture.
  deadline = time.monotonic() + 3
  while not c.parked() and time.monotonic() < deadline:
    c.can_recv()
    time.sleep(0.005)
  require_exclusive_panda()
  c.check(SAFETY.noOutput)
  c.record("health", health=panda.health())
  try:
    panda.set_safety_mode(SAFETY.elm327, 1)  # Keep bus 1 on the harness F-CAN, without OBD multiplexing.
    c.active = True
    c.check(SAFETY.elm327)
    for address in (0x18DA28F1, 0x18DA2BF1):
      c.read(address, 0xF181)
    deadline = time.monotonic() + seconds
    next_read = time.monotonic()
    while time.monotonic() < deadline:
      c.can_recv()
      if time.monotonic() >= next_read:
        c.read(0x18DA28F1, 0x4005)
        next_read = time.monotonic() + 1
      time.sleep(0.005)
  finally:
    panda.set_safety_mode(SAFETY.noOutput)
    health = panda.health()
    c.record("restored", health=health)
    if health["safety_mode"] != SAFETY.noOutput or health["controls_allowed"]:
      raise RuntimeError("Panda noOutput restoration was not confirmed")


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("output", type=Path)
  parser.add_argument("--seconds", type=int, default=30)
  args = parser.parse_args(argv)
  if not 1 <= args.seconds <= 120:
    parser.error("capture duration must be 1–120 seconds")
  if args.output.resolve().is_relative_to(ROOT):
    parser.error("write private captures outside the checkout")
  require_exclusive_panda()
  from panda import Panda
  with args.output.open("x") as output, Panda() as panda:
    def git(*args):
      return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    metadata = {"type": "metadata", "wall_time_ns": time.time_ns(), "mono_ns": time.monotonic_ns(),
                "parent": git("rev-parse", "HEAD"), "gitlink": git("rev-parse", "HEAD:opendbc_repo"),
                "opendbc": git("-C", "opendbc_repo", "rev-parse", "HEAD"),
                "status": git("status", "--porcelain"),
                "opendbc_status": git("-C", "opendbc_repo", "status", "--porcelain"), "dbc": DBC_NAME}
    output.write(json.dumps(metadata) + "\n")
    try:
      capture(panda, output, args.seconds)
    except BaseException as e:
      output.write(json.dumps({"type": "error", "exception": type(e).__name__,
                               "error": str(e), "mono_ns": time.monotonic_ns()}) + "\n")
      raise


if __name__ == "__main__":
  main()
