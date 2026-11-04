"""Passive display of the optional uploader's aggregate, device-local status."""
import json
import math
import time
from pathlib import Path

import raylib_nb as rl

from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.application import FontWeight, TextAlignment
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label

STATUS_PATH = Path('/data/proton-log-backup/status.json')
POLL_INTERVAL = 1.0
STALE_AFTER = 90.0
LABELS = {
  'checking': ('Checking uploads', 'Checking completed logs'),
  'uploading': ('Uploading logs', ''),
  'complete': ('Uploads complete', ''),
  'waiting_wifi': ('Waiting for Wi-Fi', 'Uploads resume automatically'),
  'sign_in': ('Proton sign-in needed', 'Sign in to resume log uploads'),
  'retrying': ('Upload paused', 'Retrying · check connection or Proton sign-in'),
  'pending': ('Waiting to upload', 'Checking again shortly'),
  'unavailable': ('Uploader unavailable', 'Waiting for upload status'),
}

ERROR_DETAILS = {
  'timeout': 'Upload timed out; retrying',
  'proton_unavailable': 'Check connection, Proton sign-in or storage',
  'metadata': 'Cloud verification unavailable',
  'content_mismatch': 'Cloud file differs; keeping the original',
  'local_storage': 'Device storage unavailable',
  'receipt_storage': 'Upload receipt storage unavailable',
  'upload_failed': 'Upload failed; retrying',
}


def read_status(path, now):
  try:
    with path.open() as stream:
      data = json.loads(stream.read(4097))
    if data.get('version') != 1 or data.get('state') not in LABELS:
      return None
    completed, total = data['completed'], data['total']
    updated = data['updated_at']
    if (type(completed) is not int or type(total) is not int or not 0 <= completed <= total or
        not isinstance(updated, (float, int)) or not math.isfinite(updated)):
      return None
    pending = data.get('pending_bytes', 0)
    success = data.get('last_success_at')
    if type(pending) is not int or pending < 0 or data.get('error') not in (None, *ERROR_DETAILS):
      return None
    if success is not None and (type(success) not in (int, float) or not math.isfinite(success) or success <= 0):
      return None
    if data['state'] == 'complete' and (completed != total or pending != 0):
      return None
    if not 0 <= now - updated <= STALE_AFTER:
      return {**data, 'state': 'unavailable'}
    return data
  except (OSError, ValueError, TypeError, KeyError, AttributeError):
    return None


class UploadStatus(Widget):
  def __init__(self, path=STATUS_PATH):
    super().__init__()
    self.set_enabled(False)
    self._path = path
    self._last_poll = float('-inf')
    self._status = None

  def _render(self, rect):
    if not device.awake or (ui_state.started and not ui_state.parked):
      return
    if ui_state.started and AlertRenderer.get_alert(ui_state.sm) is not None:
      return
    now = time.monotonic()
    if now - self._last_poll >= POLL_INTERVAL:
      self._status = read_status(self._path, now)
      self._last_poll = now
    if self._status is None:
      return
    data = self._status
    title, detail = LABELS[data['state']]
    if data['state'] in ('uploading', 'complete'):
      detail = f"{data['completed']} of {data['total']} log files" if data['total'] else 'No logs waiting'
    if data['state'] == 'retrying' and data.get('error') in ERROR_DETAILS:
      detail = ERROR_DETAILS[data['error']]
    if data['state'] in ('uploading', 'pending') and data.get('pending_bytes', 0):
      pending = data['pending_bytes']
      size = f'{pending / 2**30:.1f} GiB' if pending >= 2**30 else f'{max(1, round(pending / 2**20))} MiB'
      detail += f' · {size} queued'
    if data.get('last_success_at') is not None and data['state'] != 'unavailable':
      age = time.time() - data['last_success_at']  # noqa: TID251 -- compare a persisted upload event across boots.
      if age >= 0:
        elapsed = '<1m' if age < 60 else f'{int(age // 60)}m' if age < 3600 else f'{int(age // 3600)}h'
        detail += f' · Last {elapsed} ago'
    active = data['state'] in ('uploading', 'complete')
    fraction = data['completed'] / data['total'] if active and data['total'] else float(data['state'] == 'complete')
    color = rl.Color(86, 202, 145, 255) if data['state'] == 'complete' else rl.Color(91, 162, 255, 255)
    width = min(960, rect.width - 64)
    panel = rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + rect.height - 156, width, 124)
    rl.draw_rectangle_rounded(panel, 0.15, 12, rl.Color(25, 30, 36, 245))
    gui_label(rl.Rectangle(panel.x + 24, panel.y + 12, width - 48, 40), title, 34, font_weight=FontWeight.MEDIUM)
    gui_label(rl.Rectangle(panel.x + 24, panel.y + 53, width - 48, 30), detail, 25,
              color=rl.Color(185, 195, 207, 255), alignment=TextAlignment.LEFT)
    bar = rl.Rectangle(panel.x + 24, panel.y + 99, width - 48, 9)
    rl.draw_rectangle_rounded(bar, 1, 8, rl.Color(66, 75, 86, 255))
    if fraction > 0:
      rl.draw_rectangle_rounded(rl.Rectangle(bar.x, bar.y, bar.width * fraction, bar.height), 1, 8, color)
