#!/usr/bin/env bash
# Recover the comma device to the official Sunnypilot staging branch.
#
# This is intentionally separate from the ody-op deploy path. Switching with op.sh is destructive
# on the device (it discards local changes and resets submodules), and staging is prebuilt-safe, so
# this helper does not build a local candidate. Use it as a known-good fallback between experiments.

set -euo pipefail

DEVICE="${ODYSSEY_DEVICE:-192.168.1.200}"
SSH_KEY="${ODYSSEY_SSH_KEY:-/Users/travisbadgley/.ssh/id_ed25519}"
STAGING_REMOTE="https://github.com/sunnypilot/sunnypilot.git"

usage() {
  cat <<'EOF'
Usage: tools/deploy_staging.sh <deploy|verify>

Commands:
  deploy  Discard device-local changes, switch /data/openpilot to origin/staging,
          set UpdaterTargetBranch=staging and AlphaLongitudinalEnabled=1, reboot,
          and verify after reconnecting.
  verify  Check the device branch, remotes, nested checkout, updater parameters,
          and failed services without changing anything.

Environment:
  ODYSSEY_DEVICE   Device address (default: 192.168.1.200)
  ODYSSEY_SSH_KEY   SSH identity file (default: /Users/travisbadgley/.ssh/id_ed25519)

The deploy command is destructive to device-local source changes and intentionally does not build:
official Sunnypilot staging is the reliable prebuilt fallback. It does not change this checkout.
EOF
}

ssh_cmd() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 -i "$SSH_KEY" "comma@$DEVICE" "$@"
}

remote() {
  # Pass one shell script as one remote argument while preserving its quoting.
  local command=$1
  ssh_cmd "bash -l -c $(printf '%q' "$command")"
}

verify_device() {
  remote "
set -euo pipefail
cd /data/openpilot
branch=\$(git branch --show-current)
origin=\$(git remote get-url origin)
sunnypilot=\$(git remote get-url sunnypilot 2>/dev/null || true)
printf '%s\\n' \"branch=\$branch\" \"origin=\$origin\" \"sunnypilot=\$sunnypilot\"
printf '%s\\n' \"parent_commit=\$(git rev-parse HEAD)\"
printf '%s\\n' \"opendbc_commit=\$(git -C opendbc_repo rev-parse HEAD)\"
printf '%s\\n' \"opendbc_branch=\$(git -C opendbc_repo branch --show-current)\"
printf '%s\\n' \"parent_status=\$(git status --porcelain)\"
printf '%s\\n' \"opendbc_status=\$(git -C opendbc_repo status --porcelain)\"
for key in UpdaterTargetBranch UpdaterState UpdateAvailable LastUpdateException AlphaLongitudinalEnabled ExperimentalMode; do
  value=\$(cat \"/data/params/d/\$key\" 2>/dev/null || true)
  printf '%s=%s\\n' \"\$key\" \"\$value\"
done
failed=\$(systemctl --failed --no-legend)
printf '%s\\n' \"failed_services=\$failed\"
test \"\$branch\" = staging
test \"\$origin\" = '$STAGING_REMOTE'
test \"\$(cat /data/params/d/UpdaterTargetBranch 2>/dev/null || true)\" = staging
test \"\$(cat /data/params/d/UpdaterState 2>/dev/null || true)\" = idle
test \"\$(cat /data/params/d/UpdateAvailable 2>/dev/null || true)\" = 0
test -z \"\$failed\"
"
}

deploy_device() {
  local marker="ODY_STAGING_SWITCH_COMPLETE"
  local command="
set -euo pipefail
cd /data/openpilot
if git remote get-url origin >/dev/null 2>&1; then git remote set-url origin '$STAGING_REMOTE'; else git remote add origin '$STAGING_REMOTE'; fi
if git remote get-url sunnypilot >/dev/null 2>&1; then git remote set-url sunnypilot '$STAGING_REMOTE'; else git remote add sunnypilot '$STAGING_REMOTE'; fi
tools/op.sh switch origin staging
/data/openpilot/.venv/bin/python -c 'from openpilot.common.params import Params; p = Params(); p.put("UpdaterTargetBranch", "staging", block=True); p.put_bool("AlphaLongitudinalEnabled", True, block=True)'
printf '%s\\n' '$marker'
(sudo reboot &) && exit 0
"
  local output rc
  set +e
  output=$(remote "$command" 2>&1)
  rc=$?
  set -e
  printf '%s\\n' "$output"
  if ! printf '%s\\n' "$output" | rg -q "$marker"; then
    echo "staging switch did not complete; refusing to treat the device as recovered" >&2
    if (( rc == 0 )); then
      return 1
    fi
    return "$rc"
  fi

  echo "Waiting for the device to reconnect..."
  local attempt
  for attempt in $(seq 1 45); do
    if ssh_cmd true >/dev/null 2>&1; then
      verify_device
      return 0
    fi
    sleep 2
  done
  echo "device did not reconnect within 90 seconds" >&2
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
