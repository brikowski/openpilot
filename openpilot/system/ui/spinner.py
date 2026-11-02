#!/usr/bin/env python3
import pyray as rl
import select
import sys

from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.text import wrap_text
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.odyssey import OdysseyAnimation

# Constants
if gui_app.big_ui():
  PROGRESS_BAR_WIDTH = 1000
  PROGRESS_BAR_HEIGHT = 20
  ANIMATION_WIDTH = 1200
  ANIMATION_HEIGHT = 600
  WRAPPED_SPACING = 50
  CENTERED_SPACING = 80
  FONT_SIZE = 96
  LINE_HEIGHT = 104
else:
  PROGRESS_BAR_WIDTH = 268
  PROGRESS_BAR_HEIGHT = 10
  ANIMATION_WIDTH = 320
  ANIMATION_HEIGHT = 160
  WRAPPED_SPACING = 10
  CENTERED_SPACING = 20
  FONT_SIZE = 32
  LINE_HEIGHT = 36
MARGIN_H = 100
DARKGRAY = (55, 55, 55, 255)


def clamp(value, min_value, max_value):
  return max(min(value, max_value), min_value)


class Spinner(Widget):
  def __init__(self):
    super().__init__()
    self._odyssey = self._child(OdysseyAnimation())
    self._progress: int | None = None
    self._wrapped_lines: list[str] = []

  def set_text(self, text: str) -> None:
    if text.isdigit():
      self._progress = clamp(int(text), 0, 100)
      self._wrapped_lines = []
    else:
      self._progress = None
      self._wrapped_lines = wrap_text(text, FONT_SIZE, gui_app.width - MARGIN_H)

  def _render(self, rect: rl.Rectangle):
    spacing = WRAPPED_SPACING if self._wrapped_lines else CENTERED_SPACING
    text_height = len(self._wrapped_lines) * LINE_HEIGHT
    animation_height = min(ANIMATION_HEIGHT, max(0, rect.height - text_height - spacing - 40))
    animation_width = ANIMATION_WIDTH * animation_height / ANIMATION_HEIGHT
    if self._wrapped_lines:
      total_height = animation_height + spacing + text_height
      center_y = rect.y + (rect.height - total_height) / 2.0 + animation_height / 2.0
    else:
      center_y = rect.y + rect.height / 2.0
    y_pos = center_y + animation_height / 2.0 + spacing

    center = rl.Vector2(rect.x + rect.width / 2.0, center_y)
    self._odyssey.render(rl.Rectangle(center.x - animation_width / 2.0, center.y - animation_height / 2.0,
                                      animation_width, animation_height))

    # Display the progress bar or text based on user input
    if self._progress is not None:
      bar = rl.Rectangle(center.x - PROGRESS_BAR_WIDTH / 2.0, y_pos, PROGRESS_BAR_WIDTH, PROGRESS_BAR_HEIGHT)
      rl.draw_rectangle_rounded(bar, 1, 10, DARKGRAY)

      bar.width *= self._progress / 100.0
      rl.draw_rectangle_rounded(bar, 1, 10, rl.WHITE)
    elif self._wrapped_lines:
      for i, line in enumerate(self._wrapped_lines):
        text_size = measure_text_cached(gui_app.font(), line, FONT_SIZE)
        rl.draw_text_ex(gui_app.font(), line, rl.Vector2(center.x - text_size.x / 2, y_pos + i * LINE_HEIGHT),
                        FONT_SIZE, 0.0, rl.WHITE)


def _read_stdin():
  """Non-blocking read of available lines from stdin."""
  lines = []
  while True:
    rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
    if not rlist:
      break
    line = sys.stdin.readline().strip()
    if line == "":
      break
    lines.append(line)
  return lines


def main():
  gui_app.init_window("Spinner")
  spinner = Spinner()
  for _ in gui_app.render():
    text_list = _read_stdin()
    if text_list:
      spinner.set_text(text_list[-1])

    spinner.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))


if __name__ == "__main__":
  main()
