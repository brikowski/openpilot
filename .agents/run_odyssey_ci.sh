#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
MODE="${1:-test}"

case "$MODE" in
  lint)
    uv lock --check
    ruff check openpilot opendbc_repo/opendbc/car/honda
    ruff check .agents --ignore ISC002
    ;;
  test)
    "$PYTHON" -m pytest -q \
      opendbc_repo/opendbc/car/honda/tests/test_honda.py \
      opendbc_repo/opendbc/safety/tests/test_honda.py \
      opendbc_repo/opendbc/car/tests/test_lateral_limits.py \
      openpilot/common/tests/test_prefix.py \
      openpilot/system/manager/test/test_auto_update.py \
      openpilot/selfdrive/car/tests/test_cruise_speed.py \
      openpilot/selfdrive/controls/tests/test_controlsd.py \
      openpilot/selfdrive/controls/tests/test_longitudinal_planner.py \
      openpilot/selfdrive/controls/tests/test_departure_alerts.py \
      openpilot/selfdrive/controls/tests/test_honda_steering_range.py \
      openpilot/selfdrive/controls/tests/test_torqued_lat_accel_offset.py \
      openpilot/selfdrive/selfdrived/tests/test_eco_mode.py \
      openpilot/selfdrive/locationd/test/test_pose_kf.py \
      openpilot/selfdrive/locationd/test/test_torqued.py \
      openpilot/selfdrive/ui/tests/test_display_wake.py \
      openpilot/selfdrive/ui/tests/test_screensaver.py \
      openpilot/selfdrive/ui/tests/test_upload_status.py \
      openpilot/selfdrive/ui/tests/test_lead_bar.py \
      openpilot/selfdrive/ui/tests/test_settings.py \
      openpilot/system/ui/lib/tests \
      .agents
    "$PYTHON" .agents/preflash.py
    ;;
  *)
    echo "Usage: $0 [lint|test]" >&2
    exit 2
    ;;
esac
