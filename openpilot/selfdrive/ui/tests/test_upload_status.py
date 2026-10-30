import importlib
import json
from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.selfdrive.ui.tests.test_display_wake import backlight as backlight, display as display
from openpilot.selfdrive.ui.tests.test_screensaver import advance, screen as screen


def write_status(path, state='uploading', *, completed=1, total=4, updated_at=0.):
  path.write_text(json.dumps({'version': 1, 'updated_at': updated_at, 'state': state, 'completed': completed, 'total': total}))


@pytest.fixture
def indicator(monkeypatch, tmp_path):
  monkeypatch.setenv('SCALE', '1')
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  from openpilot.selfdrive.ui.widgets import upload_status as module
  state = SimpleNamespace(started=False, parked=False, sm=object())
  device = SimpleNamespace(awake=True)
  monkeypatch.setattr(module, 'ui_state', state)
  monkeypatch.setattr(module, 'device', device)
  monkeypatch.setattr(module.AlertRenderer, 'get_alert', lambda _: None)
  now = [0.]
  monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
  labels, bars = [], []
  monkeypatch.setattr(module, 'gui_label', lambda rect, text, *a, **kw: labels.append(text))
  monkeypatch.setattr(module.rl, 'draw_rectangle_rounded', lambda rect, *a: bars.append(rect))
  path = tmp_path / 'status.json'
  write_status(path)
  widget = module.UploadStatus(path)
  return SimpleNamespace(module=module, state=state, device=device, now=now, labels=labels, bars=bars, path=path, widget=widget)


def render(indicator):
  indicator.labels.clear()
  indicator.bars.clear()
  indicator.widget._render(rl.Rectangle(300, 0, 1860, 1080))


@pytest.mark.parametrize('started,parked,visible', [(False, False, True), (True, True, True), (True, False, False)])
def test_indicator_is_visible_only_offroad_or_in_confirmed_park(indicator, started, parked, visible):
  indicator.state.started, indicator.state.parked = started, parked
  render(indicator)
  assert bool(indicator.labels) is visible
  assert indicator.widget.enabled is False


def test_driving_hides_cached_status_immediately(indicator):
  render(indicator)
  assert indicator.labels
  indicator.state.started = True
  render(indicator)
  assert not indicator.labels


def test_sleeping_display_and_onroad_alert_hide_indicator(indicator, monkeypatch):
  indicator.device.awake = False
  render(indicator)
  assert not indicator.labels
  indicator.device.awake = True
  indicator.state.started = indicator.state.parked = True
  monkeypatch.setattr(indicator.module.AlertRenderer, 'get_alert', lambda _: object())
  render(indicator)
  assert not indicator.labels


def test_progress_bar_uses_confirmed_log_count(indicator):
  render(indicator)
  assert indicator.labels == ['Uploading logs', '1 of 4 log files']
  assert indicator.bars[-1].width == pytest.approx(indicator.bars[-2].width / 4)
  indicator.now[0] = 1.
  write_status(indicator.path, 'complete', completed=4)
  render(indicator)
  assert indicator.labels == ['Uploads complete', '4 of 4 log files']
  assert indicator.bars[-1].width == indicator.bars[-2].width


@pytest.mark.parametrize('state', ['waiting_wifi', 'sign_in', 'retrying', 'checking', 'pending'])
def test_waiting_states_do_not_show_a_full_progress_bar(indicator, state):
  write_status(indicator.path, state)
  render(indicator)
  assert indicator.labels[0] == indicator.module.LABELS[state][0]
  assert len(indicator.bars) == 2  # Panel and empty track.


@pytest.mark.parametrize('payload', ['{', '[]', '{}', '{"version":2}', '{"version":1,"state":"disabled"}', 'x' * 5000])
def test_missing_disabled_or_malformed_status_is_silent(indicator, payload):
  indicator.path.unlink()
  render(indicator)
  assert not indicator.labels
  indicator.now[0] = 1.
  indicator.path.write_text(payload)
  render(indicator)
  assert not indicator.labels


def test_stale_status_never_claims_uploads_are_complete(indicator):
  write_status(indicator.path, 'complete', completed=4)
  indicator.now[0] = 100.
  render(indicator)
  assert indicator.labels[0] == 'Uploader unavailable'
  assert len(indicator.bars) == 2


@pytest.mark.parametrize('completed,total', [(-1, 4), (5, 4), (True, 4), (1, 4)])
def test_invalid_or_incomplete_counts_cannot_claim_completion(indicator, completed, total):
  write_status(indicator.path, 'complete', completed=completed, total=total)
  render(indicator)
  assert not indicator.labels


@pytest.mark.parametrize('active,settings,visible', [(True, False, True), (False, False, False), (True, True, False)])
def test_big_main_hides_status_under_screensaver_dialogs_and_settings(indicator, monkeypatch, active, settings, visible):
  module = importlib.import_module('openpilot.selfdrive.ui.layouts.main')
  main = module.MainLayout.__new__(module.MainLayout)
  main._sidebar = SimpleNamespace(is_visible=False)
  main._rect = main._content_rect = rl.Rectangle(0, 0, 2160, 1080)
  main._current_mode = module.MainState.SETTINGS if settings else module.MainState.HOME
  main._layouts = {main._current_mode: SimpleNamespace(render=lambda _: None)}
  calls = []
  main._upload_status = SimpleNamespace(render=lambda _: calls.append(True))
  monkeypatch.setattr(module.gui_app, 'get_active_widget', lambda: main if active else object())
  main._render_main_content()
  assert bool(calls) is visible


@pytest.mark.parametrize('active', [True, False])
def test_mici_main_hides_status_under_screensaver_and_dialogs(indicator, monkeypatch, active):
  module = importlib.import_module('openpilot.selfdrive.ui.mici.layouts.main')
  main = module.MiciMainLayout.__new__(module.MiciMainLayout)
  main._setup = True
  main._rect = rl.Rectangle(0, 0, 2160, 1080)
  calls = []
  main._upload_status = SimpleNamespace(render=lambda _: calls.append(True))
  monkeypatch.setattr(module.Scroller, '_render', lambda *args: None)
  monkeypatch.setattr(module.gui_app, 'get_active_widget', lambda: main if active else object())
  main._render(main._rect)
  assert bool(calls) is active


@pytest.mark.parametrize('parked', [False, True])
def test_upload_start_progress_and_completion_do_not_extend_idle_timeouts(display, backlight, screen, monkeypatch, tmp_path, parked):
  from openpilot.selfdrive.ui.layouts import screensaver
  from openpilot.selfdrive.ui.widgets import upload_status
  from openpilot.selfdrive.ui.ui_state import car

  state, device, now = display
  state.started = state.ignition = parked
  state.sm['carState'].gearShifter = car.CarState.GearShifter.park
  state.sm['carState'].standstill = True
  monkeypatch.setattr(screensaver, 'ui_state', state)
  monkeypatch.setattr(screensaver, 'device', device)
  monkeypatch.setattr(upload_status, 'ui_state', state)
  monkeypatch.setattr(upload_status, 'device', device)
  monkeypatch.setattr(upload_status, 'time', SimpleNamespace(monotonic=lambda: now[0]))
  monkeypatch.setattr(upload_status, 'gui_label', lambda *a, **kw: None)
  monkeypatch.setattr(upload_status.rl, 'draw_rectangle_rounded', lambda *a: None)
  path = tmp_path / 'status.json'
  widget = upload_status.UploadStatus(path)
  for timestamp, status in [(0, 'checking'), (9, 'uploading'), (10, 'uploading'), (30, 'complete'), (59, 'uploading'),
                            (60, 'complete'), (62, 'complete'), (100, 'retrying')]:
    now[0] = timestamp
    write_status(path, status, updated_at=timestamp)
    advance(screen, timestamp)
    widget._render(rl.Rectangle(0, 0, 2160, 1080))
    device.update()
    assert device._wake_policy.deadline == 60
    assert device.awake == (timestamp < 62)
    if timestamp >= 10:
      assert screen.app.get_active_widget() is screen.saver
  assert device._brightness_target == 0
  assert backlight[0] == backlight[1] == [(62, False)]
