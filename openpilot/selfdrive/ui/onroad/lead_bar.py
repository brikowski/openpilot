import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.shader_polygon import draw_polygon


class LeadBar:
  def __init__(self):
    self.bar = np.empty((0, 2), dtype=np.float32)
    self.d_filter = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps, initialized=False)
    self.y_filter = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps, initialized=False)
    self.fade_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)

  def project(self, transform, lane, height, d_rel, y_rel, max_length=12.0):
    # Follow the road behind the lead, with a screen-space thickness limit.
    x = np.array([d_rel, d_rel - min(6.0, 0.25 * d_rel)])
    y = np.interp(x, lane[:, 0], lane[:, 1]) - np.interp(d_rel, lane[:, 0], lane[:, 1]) - y_rel
    z = np.interp(x, lane[:, 0], lane[:, 2]) + height
    corners = np.vstack((np.column_stack((x, y + .9, z)), np.column_stack((x, y - .9, z))[::-1]))
    pts = transform @ corners.T
    if not np.isfinite(pts).all() or np.any(pts[2] <= 1e-6):
      return np.empty((0, 2), dtype=np.float32)
    bar = (pts[:2] / pts[2]).T
    far, near = bar[[0, 3]], bar[[1, 2]]
    length = np.linalg.norm(near.mean(axis=0) - far.mean(axis=0))
    if length <= 1e-6:
      return np.empty((0, 2), dtype=np.float32)
    bar[[1, 2]] = far + (near - far) * np.clip(length, max_length / 4, max_length) / length
    return bar.astype(np.float32)

  def draw(self, rect, offset=(0., 0.)):
    if not len(self.bar) or self.fade_filter.x < 1e-3:
      return
    points = self.bar + np.asarray(offset, dtype=np.float32)
    alpha = self.fade_filter.x
    draw_polygon(rect, points + [0., rect.height / 120], rl.Color(0, 0, 0, int(255 * .3 * alpha)))
    draw_polygon(rect, points, rl.Color(255, 255, 255, int(255 * alpha)))
