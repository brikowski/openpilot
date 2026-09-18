#!/usr/bin/env bash
# Publish, deploy, and verify the single Odyssey experiment/rollback line.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="${ODYSSEY_DEVICE:-192.168.1.200}"
SSH_KEY="${ODYSSEY_SSH_KEY:-/Users/travisbadgley/.ssh/id_ed25519}"
BRANCH=ody-op
DEVICE_REMOTE=https://github.com/brikowski/openpilot.git
DEVICE_UV_CACHE=/data/uv-cache
DEVICE_UV_PYTHON=/data/uv-python

usage() {
  cat <<'EOF'
Usage: tools/deploy_ody_op.sh <deploy|verify>

Commands:
  deploy  Verify and publish the paired ody-op source, switch/build the offroad
          device with Alpha Long disabled, reboot, and verify exact state.
  verify  Read-only comparison of the device against this checkout's ody-op pair.

Environment:
  ODYSSEY_DEVICE   Device address (default: 192.168.1.200)
  ODYSSEY_SSH_KEY  SSH identity file (default: /Users/travisbadgley/.ssh/id_ed25519)
EOF
}

ssh_cmd() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 -i "$SSH_KEY" "comma@$DEVICE" "$@"
}

remote() {
  local command=$1
  ssh_cmd "bash -l -c $(printf '%q' "$command")"
}

local_pair() {
  cd "$ROOT_DIR"
  if test "$(git branch --show-current)" != "$BRANCH"; then
    echo "refusing: parent checkout is not $BRANCH" >&2
    return 1
  fi
  if test -n "$(git status --porcelain)"; then
    echo "refusing: parent checkout is dirty" >&2
    return 1
  fi
  if test -n "$(git -C opendbc_repo status --porcelain)"; then
    echo "refusing: nested opendbc checkout is dirty" >&2
    return 1
  fi
  if test "$(git -C opendbc_repo branch --show-current)" != "$BRANCH"; then
    echo "refusing: nested opendbc checkout is not $BRANCH" >&2
    return 1
  fi

  PARENT_SHA=$(git rev-parse HEAD)
  OPENDBC_SHA=$(git -C opendbc_repo rev-parse HEAD)
  if test "$(git ls-tree HEAD opendbc_repo | awk '{print $3}')" != "$OPENDBC_SHA"; then
    echo "refusing: parent gitlink does not match the nested checkout" >&2
    return 1
  fi
  export PARENT_SHA OPENDBC_SHA
}

verify_device() {
  local_pair
  remote "
set -euo pipefail
cd /data/openpilot
branch=\$(git branch --show-current)
parent=\$(git rev-parse HEAD)
gitlink=\$(git ls-tree HEAD opendbc_repo | awk '{print \$3}')
opendbc=\$(git -C opendbc_repo rev-parse HEAD)
origin=\$(git remote get-url origin)
parent_status=\$(git status --porcelain)
opendbc_status=\$(git -C opendbc_repo status --porcelain)
alpha=\$(cat /data/params/d/AlphaLongitudinalEnabled 2>/dev/null || true)
failed=\$(systemctl --failed --no-legend)
printf '%s\n' \
  \"branch=\$branch\" \"parent_commit=\$parent\" \"gitlink_commit=\$gitlink\" \
  \"opendbc_commit=\$opendbc\" \"origin=\$origin\" \
  \"parent_status=\$parent_status\" \"opendbc_status=\$opendbc_status\" \
  \"AlphaLongitudinalEnabled=\${alpha:-missing}\" \
  \"UpdaterTargetBranch=\$(cat /data/params/d/UpdaterTargetBranch 2>/dev/null || true)\" \
  \"UpdaterState=\$(cat /data/params/d/UpdaterState 2>/dev/null || true)\" \
  \"UpdateAvailable=\$(cat /data/params/d/UpdateAvailable 2>/dev/null || true)\" \
  \"LastUpdateException=\$(cat /data/params/d/LastUpdateException 2>/dev/null || true)\" \
  \"comma_service=\$(systemctl is-active comma.service)\" \
  \"manager_processes=\$(ps -C python3 -o args= | grep -c '^python3 ./manager.py$')\" \
  \"pandad_processes=\$(pgrep -xc pandad)\" \"failed_services=\$failed\"
test \"\$branch\" = '$BRANCH'
test \"\$parent\" = '$PARENT_SHA'
test \"\$gitlink\" = '$OPENDBC_SHA'
test \"\$opendbc\" = '$OPENDBC_SHA'
test \"\$origin\" = '$DEVICE_REMOTE'
test -z \"\$parent_status\"
test -z \"\$opendbc_status\"
test -z \"\$alpha\" || test \"\$alpha\" = 0
test ! -e /data/params/d/IsOnroad
test \"\$(cat /data/params/d/UpdaterTargetBranch 2>/dev/null || true)\" = '$BRANCH'
test \"\$(cat /data/params/d/UpdaterState 2>/dev/null || true)\" = idle
test \"\$(cat /data/params/d/UpdateAvailable 2>/dev/null || true)\" = 0
test \"\$(systemctl is-active comma.service)\" = active
test \"\$(ps -C python3 -o args= | grep -c '^python3 ./manager.py$')\" -ge 1
test \"\$(pgrep -xc pandad)\" -ge 1
test -z \"\$failed\"
"
}

deploy_device() {
  local_pair
  cd "$ROOT_DIR"
  git diff --check
  git -C opendbc_repo diff --check
  .venv/bin/python .agents/preflash.py
  git -C opendbc_repo push origin "$BRANCH"
  git push origin "$BRANCH"

  local marker=ODY_OP_DEPLOY_COMPLETE
  local command="
set -euo pipefail
cd /data/openpilot
test ! -e /data/params/d/IsOnroad
alpha=\$(cat /data/params/d/AlphaLongitudinalEnabled 2>/dev/null || true)
test -z \"\$alpha\" || test \"\$alpha\" = 0
if git remote get-url origin >/dev/null 2>&1; then git remote set-url origin '$DEVICE_REMOTE'; else git remote add origin '$DEVICE_REMOTE'; fi
tools/op.sh switch origin '$BRANCH'
UV_CACHE_DIR='$DEVICE_UV_CACHE' UV_PYTHON_INSTALL_DIR='$DEVICE_UV_PYTHON' \
  UV_PYTHON_PREFERENCE=managed uv sync --frozen --all-extras
PYTHONPATH=/data/openpilot UV_CACHE_DIR='$DEVICE_UV_CACHE' \
  UV_PYTHON_INSTALL_DIR='$DEVICE_UV_PYTHON' UV_PYTHON_PREFERENCE=managed tools/op.sh build
test \"\$(git rev-parse HEAD)\" = '$PARENT_SHA'
test \"\$(git ls-tree HEAD opendbc_repo | awk '{print \$3}')\" = '$OPENDBC_SHA'
test \"\$(git -C opendbc_repo rev-parse HEAD)\" = '$OPENDBC_SHA'
test -z \"\$(git status --porcelain)\"
test -z \"\$(git -C opendbc_repo status --porcelain)\"
printf '%s\n' '$marker'
(sudo reboot &) && exit 0
"

  local output rc
  set +e
  output=$(remote "$command" 2>&1)
  rc=$?
  set -e
  printf '%s\n' "$output"
  if ! printf '%s\n' "$output" | rg -q "$marker"; then
    echo "ody-op build did not complete; refusing to treat the device as deployed" >&2
    if (( rc == 0 )); then
      return 1
    fi
    return "$rc"
  fi

  echo "Waiting for the device to reconnect..."
  local attempt verify_output
  for attempt in $(seq 1 45); do
    if ssh_cmd true >/dev/null 2>&1; then
      if verify_output=$(verify_device 2>&1); then
        printf '%s\n' "$verify_output"
        return 0
      fi
    fi
    sleep 2
  done
  echo "device did not verify within 90 seconds" >&2
  return 1
}

main() {
  case "${1:-}" in
    deploy)
      deploy_device
      ;;
    verify)
      verify_device
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
