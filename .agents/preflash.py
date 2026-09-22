#!/usr/bin/env python3
"""Run Odyssey interface and command-rail checks before a device build.

These software checks do not grade ride quality or replace full-rate road validation.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

OPENDBC = Path(__file__).resolve().parent.parent / "opendbc_repo"
PLATFORM = "HONDA_ODYSSEY_5G_MMR"
RAILS_TEST = Path(__file__).resolve().parent / "test_odyssey_long_rails.py"


def run_test_models() -> bool:
  os.environ.setdefault("MAX_EXAMPLES", "1")
  private_tmp = Path("/private/tmp")
  cache_root = private_tmp if private_tmp.is_dir() else Path(tempfile.gettempdir())
  os.environ.setdefault("COMMA_CACHE", str(cache_root / "comma_download_cache"))
  sys.path.insert(0, str(OPENDBC))

  from opendbc.car.tests.test_models import TestCarModelBase, get_test_cases

  cases = [(p, r) for p, r in get_test_cases() if str(p) == PLATFORM]
  if not cases:
    print(f"FAIL: {PLATFORM} has no test route in opendbc/car/tests/routes.py")
    return False

  suite = unittest.TestSuite()
  for i, (platform, route) in enumerate(cases):
    print(f"  route {route.route}")
    cls = type(f"TestCarModel_{i}_{platform}", (TestCarModelBase,),
               {"platform": platform, "test_route": route})
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
  return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


def run_rails() -> bool:
  return subprocess.run([sys.executable, "-m", "pytest", str(RAILS_TEST), "-q"],
                        cwd=OPENDBC.parent).returncode == 0


def main(argv=None) -> int:
  argparse.ArgumentParser(description=__doc__).parse_args(argv)
  results = {}

  print(f"\n=== 1/2  opendbc test_models :: {PLATFORM} ===")
  print("    (CarState / fingerprint / radar / panda safety - NOT the longitudinal tune)")
  results["test_models"] = run_test_models()

  print("\n=== 2/2  Custom Odyssey command/parameter regressions ===")
  print("    (active ACC_CONTROL safety/lifecycle plus tuned parameter semantics)")
  results["long_rails"] = run_rails()

  print("\n=== pre-flash summary ===")
  for name, ok in results.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
  if all(results.values()):
    print("\nSoftware gates passed. Confirm the intended clean build before flashing; road behavior "
          "is still unmeasured.")
    return 0
  print("\nDo NOT flash.")
  return 1


if __name__ == "__main__":
  sys.exit(main())
