#!/usr/bin/env python3
"""Require a newly published offroad state before switching or rebooting a device."""
import time

from openpilot.cereal import messaging
from openpilot.common.params import Params


def main():
  started_at = time.monotonic_ns()
  sm = messaging.SubMaster(["deviceState"])
  deadline = started_at + 3_000_000_000
  while (remaining := deadline - time.monotonic_ns()) > 0:
    sm.update(max(1, remaining // 1_000_000))
    if (sm.updated["deviceState"] and sm.valid["deviceState"] and sm.alive["deviceState"] and
        sm.logMonoTime["deviceState"] >= started_at):
      break
  else:
    raise SystemExit("refusing: no fresh valid deviceState")
  if sm["deviceState"].started or not Params().get_bool("IsOffroad"):
    raise SystemExit("refusing: device is not confirmed offroad")
  print("offroad confirmed")


if __name__ == "__main__":
  main()
