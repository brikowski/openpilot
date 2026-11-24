#!/usr/bin/env python3
"""Require newly published vehicle state before offroad device operations."""
import argparse
import time

from openpilot.cereal import log, messaging
from openpilot.common.params import Params


def main(ignition_off=False):
  started_at = time.monotonic_ns()
  services = ["deviceState", "pandaStates"] if ignition_off else ["deviceState"]
  sm = messaging.SubMaster(services)
  deadline = started_at + 3_000_000_000
  while (remaining := deadline - time.monotonic_ns()) > 0:
    sm.update(max(1, remaining // 1_000_000))
    if sm.updated["deviceState"] and all(sm.valid[s] and sm.alive[s] and sm.logMonoTime[s] >= started_at for s in services):
      break
  else:
    raise SystemExit(f"refusing: no fresh valid {' and '.join(services)}")
  if sm["deviceState"].started or not Params().get_bool("IsOffroad"):
    raise SystemExit("refusing: device is not confirmed offroad")
  if ignition_off:
    pandas = sm["pandaStates"]
    # Startup can be blocked while the vehicle ignition is still on.
    if not pandas or any(p.pandaType == log.PandaState.PandaType.unknown or p.ignitionLine or p.ignitionCan for p in pandas):
      raise SystemExit("refusing: vehicle ignition is not confirmed off")
  print("offroad confirmed")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ignition-off", action="store_true", help="also verify fresh Panda ignition state")
  main(parser.parse_args().ignition_off)
