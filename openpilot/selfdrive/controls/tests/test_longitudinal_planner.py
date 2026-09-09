import pytest

from openpilot.selfdrive.controls.lib.longitudinal_planner_helpers import effective_allow_throttle


@pytest.mark.parametrize("fingerprint, experimental, speed, coast, expected", [
  ("HONDA_ODYSSEY_5G_MMR", False, 18.0, -0.10, False),
  ("HONDA_ODYSSEY_5G_MMR", False, 18.0, -0.20, True),
  ("HONDA_ODYSSEY_5G_MMR", False, 18.0, -0.41, True),
  ("HONDA_ODYSSEY_5G_MMR", False, 4.9, -0.10, True),
  ("HONDA_ODYSSEY_5G_MMR", True, 18.0, -0.10, True),
  ("OTHER", False, 18.0, -0.10, True),
])
def test_effective_allow_throttle(fingerprint, experimental, speed, coast, expected):
  assert effective_allow_throttle(fingerprint, experimental, speed, True, coast) is expected


def test_effective_allow_throttle_preserves_model_disable():
  assert not effective_allow_throttle("HONDA_ODYSSEY_5G_MMR", False, 18.0, False, -0.41)
