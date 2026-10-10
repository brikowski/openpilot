import time
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import device
from openpilot.system.ui.lib.application import gui_app, TextAlignment
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button
from openpilot.system.ui.widgets.label import Label
from openpilot.tools.honda_brake_test import MODE, STATUS, cancel_test


class BrakeTestLayout(Widget):
  def __init__(self):
    super().__init__()
    self.params = Params()
    self.title = Label('', font_size=64, text_alignment=TextAlignment.CENTER)
    self.instruction = Label('', font_size=52, text_alignment=TextAlignment.CENTER)
    self.footer = Label('Stay parked • Keep the parking brake set', font_size=36, text_alignment=TextAlignment.CENTER)
    self.cancel = Button('Cancel test', click_callback=lambda: cancel_test(self.params))
    self.next_update = 0.

  def update(self):
    if time.monotonic() < self.next_update:
      return
    self.next_update = time.monotonic() + 0.2
    mode = self.params.get(MODE)
    if mode:
      if not gui_app.widget_in_stack(self):
        gui_app.push_widget(self)
      device.set_override_interactive_timeout(300)
      status = self.params.get(STATUS) or {}
      title = status.get('title', 'Brake diagnostic test')
      instruction = status.get('instruction', 'Turn the car fully off. Wait for the next instruction.')
      if mode != 'requested' and time.monotonic_ns() - status.get('mono_ns', 0) > 3_000_000_000:
        title, instruction = 'Brake test waiting', 'Turn the car fully off. Normal operation resumes after cleanup.'
      self.title.set_text(title)
      self.instruction.set_text(instruction)
    elif gui_app.get_active_widget() is self:
      gui_app.pop_widget()
      device.set_override_interactive_timeout(None)

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.Color(25, 30, 40, 255))
    inset = rect.width * 0.06
    self.title.render(rl.Rectangle(rect.x + inset, rect.y + rect.height * 0.08, rect.width - 2 * inset, rect.height * 0.22))
    self.instruction.render(rl.Rectangle(rect.x + inset, rect.y + rect.height * 0.32, rect.width - 2 * inset, rect.height * 0.30))
    self.footer.render(rl.Rectangle(rect.x + inset, rect.y + rect.height * 0.65, rect.width - 2 * inset, rect.height * 0.10))
    self.cancel.render(rl.Rectangle(rect.x + rect.width * 0.32, rect.y + rect.height * 0.80, rect.width * 0.36, rect.height * 0.13))
