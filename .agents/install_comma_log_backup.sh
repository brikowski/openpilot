#!/usr/bin/env bash
# Run as comma from /data/proton-log-backup after copying the reviewed tools and client.
set -euo pipefail
select_backup_python() {
  local interpreter
  for interpreter in /data/openpilot/.venv/bin/python /usr/local/venv/bin/python3; do
    if test -x "$interpreter" && PYTHONPATH=/data/openpilot "$interpreter" -c 'from openpilot.cereal import messaging' >/dev/null 2>&1; then
      printf '%s\n' "$interpreter"
      return 0
    fi
  done
  echo 'No usable Python environment for Proton log backup' >&2
  return 1
}

cd /data/openpilot
ody_backup_python=$(select_backup_python)
PYTHONPATH=/data/openpilot "$ody_backup_python" tools/check_offroad.py
cd /data/proton-log-backup
umask 077
test -x bin/proton-drive
test -x gnupg-runtime/usr/bin/gpg
test -x gnupg-runtime/usr/bin/pass
mkdir -p bin gnupg password-store client
chmod 700 . bin gnupg password-store client
{
  printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail'
  declare -f select_backup_python
  cat <<'BACKUP_RUNNER'
cd /data/proton-log-backup
ody_backup_python=$(select_backup_python)
export PYTHONPATH=/data/openpilot
exec "$ody_backup_python" /data/proton-log-backup/comma_log_backup.py "$@"
BACKUP_RUNNER
} > run_backup.sh
chmod 700 run_backup.sh

cat > bin/gpg <<'GPG'
#!/usr/bin/env bash
exec /data/proton-log-backup/gnupg-runtime/usr/bin/gpg \
  --agent-program /data/proton-log-backup/gnupg-runtime/usr/bin/gpg-agent \
  --pinentry-mode loopback "$@"
GPG
chmod 700 bin/gpg
ln -sfn ../gnupg-runtime/usr/bin/pass bin/pass
export PATH="/data/proton-log-backup/bin:/usr/bin:/bin"
export GNUPGHOME=/data/proton-log-backup/gnupg
export PASSWORD_STORE_DIR=/data/proton-log-backup/password-store
export PASSWORD_STORE_ENABLE_EXTENSIONS=false
if ! test -f password-store/.gpg-id; then
  gpg --batch --passphrase '' --quick-generate-key 'Proton log backup session' future-default default 0
  pass init 'Proton log backup session'
fi
# Exercise encryption/decryption without putting a real account session in the installer output.
printf '%s\n' 'credential-store-check' | pass insert -f -m .install-check
test "$(pass show .install-check)" = credential-store-check
pass rm -f .install-check

if ! test -e config.json; then
  printf '%s\n' '{"enabled":false,"destination":"/my-files/Documents/openpilot/rlogs"}' > config.json
fi
chmod 600 config.json

# Keep the optional service outside both OpenPilot trees. Preserve the existing startup hook.
sudo /usr/bin/python3 - <<'PY'
import os
from pathlib import Path

hook = Path('/data/continue.sh')
text = hook.read_text()
marker = '# BEGIN optional Proton log backup'
original = '''# BEGIN optional Proton log backup
sudo systemctl link --runtime /data/proton-log-backup/proton-log-backup.service
sudo systemctl start --no-block proton-log-backup.service
# END optional Proton log backup

'''
previous = original.replace(
  'sudo systemctl start --no-block',
  'sudo systemctl set-property --runtime proton-log-backup.service MemoryMax=512M\nsudo systemctl start --no-block',
)
block = original.replace(
  'sudo systemctl link --runtime',
  'sudo mkdir -p /run/systemd/system/proton-log-backup.service.d\n'
  'sudo ln -sfn /dev/null /run/systemd/system/proton-log-backup.service.d/background.conf\n'
  'sudo systemctl link --runtime',
)
updated = text
if block in text and text.count(marker) == 1:
  pass
elif previous in text and text.count(marker) == 1:
  updated = text.replace(previous, block)
elif original in text and text.count(marker) == 1:
  updated = text.replace(original, block)
elif marker not in text:
  if text.count('cd /data/openpilot\n') != 1:
    raise SystemExit('unrecognized continue.sh; refusing to replace the startup hook')
  updated = text.replace('cd /data/openpilot\n', block + 'cd /data/openpilot\n')
else:
  raise SystemExit('unrecognized Proton backup block; refusing to replace the startup hook')
if updated != text:
  stat = hook.stat()
  temporary = hook.with_suffix('.proton-backup.tmp')
  temporary.write_text(updated)
  os.chmod(temporary, stat.st_mode)
  os.chown(temporary, stat.st_uid, stat.st_gid)
  temporary.replace(hook)
PY
sudo mkdir -p /run/systemd/system/proton-log-backup.service.d
sudo ln -sfn /dev/null /run/systemd/system/proton-log-backup.service.d/background.conf
sudo systemctl link --runtime /data/proton-log-backup/proton-log-backup.service
sudo systemctl daemon-reload
sudo systemctl start proton-log-backup.service
./run_backup.sh status
