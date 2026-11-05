import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import private_paths
from private_paths import evidence_root, private_root, rlog_root


def test_default_archive_is_inside_repository():
  assert private_paths.DEFAULT_ROOT == Path(__file__).resolve().parents[1] / '.private'


def test_defaults_to_local_archive_without_cloud_discovery(monkeypatch, tmp_path):
  for key in ("OPENPILOT_PRIVATE_ROOT", "LOG_ROOT", "ODYSSEY_EVIDENCE_ROOT"):
    monkeypatch.delenv(key, raising=False)
  root = tmp_path / '.private'
  monkeypatch.setattr(private_paths, 'DEFAULT_ROOT', root)
  with pytest.raises(FileNotFoundError):
    private_root()
  (root / 'rlogs').mkdir(parents=True)
  (root / 'evidence').mkdir()
  assert private_root() == root
  assert rlog_root() == root / 'rlogs'
  assert evidence_root() == root / 'evidence'


def test_explicit_private_root_overrides_local_default(monkeypatch, tmp_path):
  root = tmp_path / "selected"
  (root / "rlogs").mkdir(parents=True)
  (root / "evidence").mkdir()
  monkeypatch.setenv("OPENPILOT_PRIVATE_ROOT", str(root))
  monkeypatch.delenv("LOG_ROOT", raising=False)
  monkeypatch.delenv("ODYSSEY_EVIDENCE_ROOT", raising=False)

  assert private_root() == root
  assert rlog_root() == root / "rlogs"
  assert evidence_root() == root / "evidence"
