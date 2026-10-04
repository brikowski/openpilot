import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common.hardware.hw import Paths
from openpilot.common import prefix


@pytest.mark.parametrize("raise_inside", [False, True])
@pytest.mark.parametrize("restore_archive_inside", [False, True])
def test_host_prefix_preserves_analysis_archive(monkeypatch, tmp_path, raise_inside, restore_archive_inside):
  archive = tmp_path / "archive"
  archive.mkdir()
  sentinel = archive / "rlog.zst"
  sentinel.write_bytes(b"private log")
  monkeypatch.setenv("LOG_ROOT", str(archive))
  monkeypatch.setattr(prefix, "PC", True)
  monkeypatch.setattr(Paths, "comma_home", lambda: str(tmp_path / ("home" + os.environ.get("OPENPILOT_PREFIX", ""))))
  monkeypatch.setattr(Paths, "download_cache_root", lambda: str(tmp_path / "cache"))
  monkeypatch.setattr(prefix, "Params", lambda: SimpleNamespace(get_param_path=lambda: str(tmp_path / "absent-params")))
  context = prefix.OpenpilotPrefix()
  context.msgq_path = str(tmp_path / "msgq")

  def run():
    with context:
      log_root = Path(Paths.log_root())
      assert log_root != archive
      (log_root / "test-log").write_bytes(b"temporary")
      if restore_archive_inside:
        os.environ["LOG_ROOT"] = str(archive)
      if raise_inside:
        raise RuntimeError("test exception")

  if raise_inside:
    with pytest.raises(RuntimeError, match="test exception"):
      run()
  else:
    run()

  assert sentinel.read_bytes() == b"private log"
  assert os.environ["LOG_ROOT"] == str(archive)
  assert not (tmp_path / ("home" + context.prefix)).exists()
