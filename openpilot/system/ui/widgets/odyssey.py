import time

import pyray as rl

from openpilot.system.ui.lib.application import GL_VERSION, gui_app
from openpilot.system.ui.lib.odyssey_scene import OdysseyScene
from openpilot.system.ui.widgets import Widget


class OdysseyAnimation(Widget):
  def __init__(self):
    super().__init__()
    self._scene = OdysseyScene(gui_app.texture("images/odyssey_sport.png"), GL_VERSION)

  def _render(self, rect: rl.Rectangle):
    self._scene.draw(rect, time.monotonic())
