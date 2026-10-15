import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from private_paths import evidence_root, private_root, rlog_root


def test_discovers_active_cloudstorage_mount_without_symlinks(monkeypatch, tmp_path):
  monkeypatch.setenv("HOME", str(tmp_path))
  for key in ("OPENPILOT_PRIVATE_ROOT", "LOG_ROOT", "ODYSSEY_EVIDENCE_ROOT"):
    monkeypatch.delenv(key, raising=False)
  cloud = tmp_path / "Library/CloudStorage"
  active = cloud / "ProtonDrive-account-folder/Documents/openpilot"
  backup = cloud / "ProtonDrive-account-folder (old)/Documents/openpilot"
  for root in (active, backup):
    (root / "rlogs").mkdir(parents=True)
    (root / "evidence").mkdir()

  assert private_root() == active
  assert rlog_root() == active / "rlogs"
  assert evidence_root() == active / "evidence"

  (cloud / "ProtonDrive-second-folder/Documents/openpilot").mkdir(parents=True)
  with pytest.raises(FileNotFoundError, match="expected one active"):
    private_root()


def test_explicit_private_root_handles_multiple_accounts(monkeypatch, tmp_path):
  root = tmp_path / "selected"
  (root / "rlogs").mkdir(parents=True)
  (root / "evidence").mkdir()
  monkeypatch.setenv("OPENPILOT_PRIVATE_ROOT", str(root))
  monkeypatch.delenv("LOG_ROOT", raising=False)
  monkeypatch.delenv("ODYSSEY_EVIDENCE_ROOT", raising=False)

  assert private_root() == root
  assert rlog_root() == root / "rlogs"
  assert evidence_root() == root / "evidence"
