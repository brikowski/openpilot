import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.odyssey import OdysseyAnimation


IDLE_TIMEOUT = 10.0


class Screensaver(Widget):
  def __init__(self, *menus: Widget):
    super().__init__()
    self._menus = menus
    self._animation = self._child(OdysseyAnimation())
    self._multi_touch = True
    self._last_interaction = time.monotonic()
    self._alerts = device.offroad_alerts
    self._eligible = not ui_state.started or ui_state.parked
    gui_app.add_nav_stack_tick(self._tick)

  def _tick(self):
    now = time.monotonic()
    top = gui_app.get_active_widget()
    active = top is self
    alerts = device.offroad_alerts
    new_alert = bool(alerts - self._alerts)
    self._alerts = alerts

    onroad_alert = ui_state.started and AlertRenderer.get_alert(ui_state.sm) is not None
    eligible = (not ui_state.started or ui_state.parked) and not onroad_alert
    if eligible != self._eligible:
      self._eligible = eligible
      self._last_interaction = now
    # Driving, alerts, onboarding and dialogs take priority over the animation.
    if not eligible or new_alert or (not active and top not in self._menus):
      self._last_interaction = now
      if active:
        gui_app.pop_widget()
      return

    if active:
      return
    if any(ev.left_down or ev.left_pressed or ev.left_released for ev in gui_app.mouse_events):
      self._last_interaction = now
    elif now - self._last_interaction >= IDLE_TIMEOUT:
      gui_app.push_widget(self)

  def hide_event(self):
    super().hide_event()
    self._last_interaction = time.monotonic()

  def _handle_mouse_press(self, mouse_pos: MousePos):
    # Pop during this widget's input dispatch so the waking press cannot reach the menu.
    if gui_app.get_active_widget() is self:
      gui_app.pop_widget()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    width = min(rect.width * 0.8, rect.height * 1.6)
    height = width / 2
    self._animation.render(rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + (rect.height - height) / 2, width, height))
