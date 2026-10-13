"""Find private analysis data in the active Proton Drive mount on this Mac."""

import os
from pathlib import Path


def private_root() -> Path:
  if configured := os.environ.get("OPENPILOT_PRIVATE_ROOT"):
    root = Path(configured).expanduser()
  else:
    cloud = Path.home() / "Library/CloudStorage"
    matches = [p for p in cloud.glob("ProtonDrive-*-folder/Documents/openpilot") if p.is_dir()]
    if len(matches) != 1:
      raise FileNotFoundError(f"expected one active Proton Drive openpilot folder under {cloud}; "
                              "set OPENPILOT_PRIVATE_ROOT if needed")
    root = matches[0]
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def rlog_root() -> Path:
  root = Path(os.environ["LOG_ROOT"]).expanduser() if os.environ.get("LOG_ROOT") else private_root() / "rlogs"
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def evidence_root() -> Path:
  root = (Path(os.environ["ODYSSEY_EVIDENCE_ROOT"]).expanduser()
          if os.environ.get("ODYSSEY_EVIDENCE_ROOT") else private_root() / "evidence")
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def evidence_path(name: str) -> Path:
  try:
    return evidence_root() / name
  except FileNotFoundError:
    # Pure metric tests can import the tools without a private archive. CLI entry points
    # require evidence_root() before they read or write route data.
    return Path(__file__).with_name(name)
