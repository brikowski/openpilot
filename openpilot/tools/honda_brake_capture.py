#!/usr/bin/env python3
"""Capture parked Odyssey brake diagnostics and native CAN using exclusive Panda access.

Stop openpilot with ignition off, then turn ignition on with Park and parking brake applied.
Turn ignition off again before restarting openpilot to avoid a mid-ignition radar handoff.
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
from opendbc.car.uds import CanClient, IsoTpMessage, get_rx_addr_for_tx_addr

ROOT = Path(__file__).resolve().parents[2]
DBC_NAME = DBC[CAR.HONDA_ODYSSEY_5G_MMR][Bus.pt]
SAFETY = structs.CarParams.SafetyModel
GUARD_SIGNALS = {"ENGINE_DATA": "XMISSION_SPEED", "WHEEL_SPEEDS": "WHEEL_SPEED_FL", "GEARBOX_AUTO": "GEAR_SHIFTER",
                 "SCM_FEEDBACK": "PARKING_BRAKE_ON", "POWERTRAIN_DATA": "BRAKE_PRESSED"}
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
    self.obd = False

  def record(self, kind, **data):
    self.output.write(json.dumps({"type": kind, "mono_ns": time.monotonic_ns(), **data}) + "\n")

  def parked(self):
    now = time.monotonic_ns()
    fresh = all(0 < self.cp.ts_nanos[msg][signal] <= now and
                now - self.cp.ts_nanos[msg][signal] <= 250_000_000
                for msg, signal in GUARD_SIGNALS.items())
    return (self.cp.can_valid and fresh and
            self.cp.vl["SCM_FEEDBACK"]["PARKING_BRAKE_ON"] and
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
      raise TimeoutError("diagnostic read exceeded native-state freshness")
    if frames:
      self.record("can", received_ns=received_ns,
                  connection="obd" if self.obd else "native",
                  frames=[[address, bytes(data).hex(), bus] for address, data, bus in frames])
    if self.active and not self.parked():
      raise RuntimeError("stationary Park or fresh valid CAN lost")
    if not self.obd and any(bus == 1 and address in self.cp.addresses and len(data) != self.cp.message_states[address].size
           for address, data, bus in frames):
      raise RuntimeError("invalid state frame length")
    if not self.obd:
      self.cp.update([(received_ns, frames)])
    if self.active and not self.parked():
      raise RuntimeError("stationary Park or fresh valid CAN lost")
    return frames

  def can_send(self, address, data, bus, **kwargs):
    allowed = {bytes.fromhex("0322") + did.to_bytes(2, "big") + bytes(4)
               for addr, did in READS if addr == address}
    allowed.add(bytes.fromhex("30000a0000000000"))
    if bus != 1 or address not in {addr for addr, _ in READS} or bytes(data) not in allowed:
      raise RuntimeError("only the documented read requests and ISO-TP flow control are permitted")
    require_exclusive_panda()
    self.check(SAFETY.elm327)
    self.record("tx", address=address, data_hex=bytes(data).hex(), bus=bus)
    self.panda.can_send(address, data, bus, **kwargs)

  def qualify(self):
    self.active = False
    self.cp = CANParser(DBC_NAME, [(name, 0) for name in GUARD_SIGNALS], 1)
    self.panda.can_clear(0xFFFF)
    self.panda.can_rx_overflow_buffer = b''
    deadline = time.monotonic() + 3
    while not self.parked() and time.monotonic() < deadline:
      self.can_recv()
      if self.cp.can_valid:
        self.check(SAFETY.noOutput)
      time.sleep(0.005)
    self.check(SAFETY.noOutput)
    self.active = True

  def restore(self):
    self.panda.set_safety_mode(SAFETY.noOutput)
    self.obd = False
    health = self.panda.health()
    self.record("restored", health=health)
    if health["safety_mode"] != SAFETY.noOutput or health["controls_allowed"]:
      raise RuntimeError("Panda noOutput restoration was not confirmed")

  def read(self, address, did):
    require_exclusive_panda()
    self.check(SAFETY.noOutput)
    started_ns = time.monotonic_ns()
    # OBD and native bus 1 share a hardware mux. Never refresh native state from OBD.
    self.read_deadline_ns = min(self.cp.ts_nanos[msg][sig] for msg, sig in GUARD_SIGNALS.items()) + 250_000_000
    try:
      self.panda.set_safety_mode(SAFETY.elm327)
      self.obd = True
      client = CanClient(self.can_send, self.can_recv, address, get_rx_addr_for_tx_addr(address), 1)
      # Match Honda firmware querying's existing 10 ms ISO-TP receive pacing.
      transport = IsoTpMessage(client, timeout=0.2, separation_time=0.01)
      transport.send(b'\x22' + did.to_bytes(2, 'big'))
      response, _ = transport.recv()
      while response == b'\x7f\x22\x78':
        response, _ = transport.recv()
      if response is None or not response.startswith(b'\x62' + did.to_bytes(2, 'big')):
        raise RuntimeError('ECU did not return the requested diagnostic data')
      data = response[3:]
      self.record("uds", started_ns=started_ns, address=address, did=did, data_hex=data.hex())
      self.output.flush()
      if did == 0x4005 and len(data) != 56:
        raise RuntimeError("pressure response differs from the public reference; raw bytes retained")
    finally:
      self.read_deadline_ns = 0
      self.restore()
    # A completed read is usable only with newly received native state on both sides.
    self.qualify()
    self.record("qualified", started_ns=started_ns, address=address, did=did)
    return data


def capture(panda, output, seconds):
  c = Capture(panda, output)
  require_exclusive_panda()
  if panda.health()["safety_mode"] == SAFETY.silent:
    panda.set_safety_mode(SAFETY.noOutput)
  c.qualify()
  c.record("health", health=panda.health())
  try:
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
    c.restore()


def record_metadata(output):
  def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
  output.write(json.dumps({"type": "metadata", "wall_time_ns": time.time_ns(), "mono_ns": time.monotonic_ns(),
                          "parent": git("rev-parse", "HEAD"), "gitlink": git("rev-parse", "HEAD:opendbc_repo"),
                          "opendbc": git("-C", "opendbc_repo", "rev-parse", "HEAD"),
                          "status": git("status", "--porcelain"),
                          "opendbc_status": git("-C", "opendbc_repo", "status", "--porcelain"), "dbc": DBC_NAME}) + "\n")


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
    record_metadata(output)
    try:
      capture(panda, output, args.seconds)
    except BaseException as e:
      output.write(json.dumps({"type": "error", "exception": type(e).__name__,
                               "error": str(e), "mono_ns": time.monotonic_ns()}) + "\n")
      raise


if __name__ == "__main__":
  main()
