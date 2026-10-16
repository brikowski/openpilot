#!/usr/bin/env python3
"""Require a newly published offroad state before switching or rebooting a device."""
import time

from openpilot.cereal import messaging
from openpilot.common.params import Params


def main():
  started_at = time.monotonic_ns()
  sm = messaging.SubMaster(["deviceState"])
  sm.update(3000)
  if (not sm.updated["deviceState"] or not sm.valid["deviceState"] or not sm.alive["deviceState"] or
      sm.logMonoTime["deviceState"] < started_at):
    raise SystemExit("refusing: no fresh valid deviceState")
  if sm["deviceState"].started or not Params().get_bool("IsOffroad"):
    raise SystemExit("refusing: device is not confirmed offroad")
  print("offroad confirmed")


if __name__ == "__main__":
  main()
