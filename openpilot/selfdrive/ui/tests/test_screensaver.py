from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.selfdrive.ui.display_wake import DISPLAY_TIMEOUT
from openpilot.selfdrive.ui.tests.test_display_wake import backlight as backlight, display as display

@pytest.fixture
def screen(monkeypatch, tmp_path):
  monkeypatch.setenv('SCALE', '1')
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  from openpilot.selfdrive.ui.layouts import screensaver as module
  from openpilot.system.ui import widgets
  from openpilot.system.ui.widgets import Widget

  class Menu(Widget):
    def _render(self, rect):
      pass

  app = module.gui_app
  monkeypatch.setattr(app, '_nav_stack', [])
  monkeypatch.setattr(app, '_nav_stack_ticks', [])
  monkeypatch.setattr(app, '_mouse_events', [])
  monkeypatch.setattr(module, 'OdysseyAnimation', Menu)
  monkeypatch.setattr(module.rl, 'draw_rectangle_rec', lambda *_: None)
  now = [0.0]
  monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
  state = SimpleNamespace(started=False)
  device = SimpleNamespace(awake=True, offroad_alerts=frozenset(), active=False)
  device.set_screensaver_active = lambda active: setattr(device, 'active', active)
  monkeypatch.setattr(module, 'ui_state', state)
  monkeypatch.setattr(module, 'device', device)
  monkeypatch.setattr(widgets, 'device', device)
  menu, settings, dialog = Menu(), Menu(), Menu()
  app.push_widget(menu)
  saver = module.OffroadScreensaver(menu, settings)
  return SimpleNamespace(app=app, saver=saver, state=state, device=device, now=now, menu=menu, settings=settings, dialog=dialog)


def touch(*, down=False, press=False, release=False, slot=0):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  return MouseEvent(pos=MousePos(100, 100), left_pressed=press, left_released=release, left_down=down, slot=slot, t=0.)


def advance(screen, now, events=()):
  screen.now[0] = now
  screen.app._mouse_events = list(events)
  for tick in screen.app._nav_stack_ticks:
    tick()


def test_menu_enters_after_ten_seconds_and_stays_active(screen):
  advance(screen, 9.999)
  assert screen.app.get_active_widget() is screen.menu
  advance(screen, 10)
  assert screen.app.get_active_widget() is screen.saver
  assert screen.device.active
  advance(screen, 3600)
  assert screen.app.get_active_widget() is screen.saver


def test_touch_hold_and_release_restart_the_idle_countdown(screen):
  for now, event in [(9, touch(down=True, press=True)), (100, touch(down=True)), (101, touch(release=True))]:
    advance(screen, now, [event])
    assert screen.app.get_active_widget() is screen.menu
  advance(screen, 110.999)
  assert screen.app.get_active_widget() is screen.menu
  advance(screen, 111)
  assert screen.app.get_active_widget() is screen.saver


@pytest.mark.parametrize('layers', [1, 2])
@pytest.mark.parametrize('slot', [0, 1])
def test_waking_press_is_consumed_and_returns_to_the_same_menu(screen, layers, slot):
  clicks = []
  screen.settings.set_click_callback(lambda: clicks.append('clicked'))
  screen.app.push_widget(screen.settings)
  advance(screen, 10)
  rect = rl.Rectangle(0, 0, 2160, 1080)

  def render():
    for widget in screen.app._nav_stack[-layers:]:
      widget.render(rect)

  advance(screen, 11, [touch(down=True, press=True, slot=slot)])
  render()
  assert screen.app.get_active_widget() is screen.settings
  assert not screen.device.active
  advance(screen, 12, [touch(release=True, slot=slot)])
  render()
  assert not clicks
  advance(screen, 21.999)
  assert screen.app.get_active_widget() is screen.settings
  advance(screen, 22)
  assert screen.app.get_active_widget() is screen.saver

  # A subsequent deliberate menu tap works normally.
  advance(screen, 23, [touch(down=True, press=True)])
  render()
  advance(screen, 24, [touch(release=True)])
  render()
  advance(screen, 25, [touch(down=True, press=True)])
  render()
  advance(screen, 26, [touch(release=True)])
  render()
  assert clicks == ['clicked']


def test_onroad_immediately_removes_screensaver_and_cannot_reenter(screen):
  advance(screen, 10)
  screen.state.started = True
  advance(screen, 10.01)
  assert screen.app.get_active_widget() is screen.menu
  assert not screen.device.active
  advance(screen, 100)
  assert screen.app.get_active_widget() is screen.menu
  screen.state.started = False
  advance(screen, 101)
  advance(screen, 109.999)
  assert screen.app.get_active_widget() is screen.menu
  advance(screen, 110)
  assert screen.app.get_active_widget() is screen.saver


def test_onboarding_or_modal_is_not_covered(screen):
  screen.app.push_widget(screen.dialog)
  advance(screen, 100)
  assert screen.app.get_active_widget() is screen.dialog
  screen.app.pop_widget()
  advance(screen, 109.999)
  assert screen.app.get_active_widget() is screen.menu
  advance(screen, 110)
  assert screen.app.get_active_widget() is screen.saver


def test_new_offroad_alert_reveals_menu_for_another_ten_seconds(screen):
  advance(screen, 10)
  screen.device.offroad_alerts = frozenset({'UpdateAvailable'})
  advance(screen, 11)
  assert screen.app.get_active_widget() is screen.menu
  assert not screen.device.active
  advance(screen, 20.999)
  assert screen.app.get_active_widget() is screen.menu
  advance(screen, 21)
  assert screen.app.get_active_widget() is screen.saver


def test_screensaver_holds_offroad_display_and_restores_normal_timeout(display, backlight):
  state, device, now = display
  state.started = state.ignition = False
  device.set_screensaver_active(True)
  device.update()
  now[0] = 3600
  device.update()
  assert device.awake and device._brightness_target > 0
  device.set_screensaver_active(False)
  now[0] += DISPLAY_TIMEOUT - 0.01
  device.update()
  assert device.awake
  now[0] += 4
  device.update()
  assert not device.awake and device._brightness_target == 0


def test_screensaver_cannot_hold_onroad_display(display, backlight):
  _, device, now = display
  device.set_screensaver_active(True)
  device.update()
  now[0] = DISPLAY_TIMEOUT + 3
  device.update()
  assert not device.awake and device._brightness_target == 0
