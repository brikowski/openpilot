import math
import time

import numpy as np
import raylib_nb as rl

from openpilot.system.ui.lib.application import ASSETS_DIR, gui_app
from openpilot.system.ui.widgets import Widget


class OdysseyAnimation(Widget):
  def __init__(self):
    super().__init__()
    self._texture = gui_app.texture("images/odyssey_sport.png")
    image = gui_app._load_image_from_path((ASSETS_DIR / "images/odyssey_sport.png").as_posix())
    pixels = np.frombuffer(image.to_bytes(image.width * image.height * 4), dtype=np.uint8).reshape(image.height, image.width, 4)
    self._wheels = []
    # Extract the tires once; the renderer rotates ordinary textures without a shader.
    for x in (392, 1431):
      wheel = pixels[467:779, x - 162:x + 162].copy()
      yy, xx = np.mgrid[:312, :324]
      wheel[..., 3] *= ((xx + .5 - 162) / 162) ** 2 + ((yy + .5 - 156) / 156) ** 2 < 1
      texture = rl.load_texture_from_image(rl.Image(None, 324, 312, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8))
      rl.update_texture(texture, wheel)
      rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      self._wheels.append((x, texture))
    rl.unload_image(image)

  def _render(self, rect: rl.Rectangle):
    elapsed = time.monotonic()
    scale = rect.width / self._texture.width
    # Scene coordinates follow the source artwork; tire contact is at y=780.
    distance = elapsed * 420.0
    road_y = rect.y + 776.0 * scale
    road = rl.Rectangle(rect.x, road_y, rect.width, 100.0 * scale)
    rl.draw_rectangle_rounded(road, 0.5, 12, rl.Color(16, 19, 24, 255))

    rl.begin_scissor_mode(int(road.x), int(road.y), math.ceil(road.width), math.ceil(road.height))
    for i in range(math.ceil(self._texture.width / 260.0) + 1):
      x = rect.x + (i * 260.0 - distance % 260.0) * scale
      rl.draw_rectangle_rec(rl.Rectangle(x, road_y + 60.0 * scale, 130.0 * scale, 7.0 * scale), rl.Color(118, 124, 134, 255))
    rl.end_scissor_mode()

    bob = math.sin(elapsed * math.tau) * 1.5 * scale
    car = rl.Rectangle(rect.x, rect.y + bob, rect.width, self._texture.height * scale)
    source = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    # A right-facing vehicle rolls clockwise at the same speed as the passing road.
    rl.draw_texture_pro(self._texture, source, car, rl.Vector2(0, 0), 0.0, rl.WHITE)
    for x, texture in self._wheels:
      wheel = rl.Rectangle(rect.x + x * scale, car.y + 623 * scale, 324 * scale, 312 * scale)
      rl.draw_texture_pro(texture, rl.Rectangle(0, 0, 324, 312), wheel,
                          rl.Vector2(162 * scale, 156 * scale), math.degrees(distance / 160.0) % 360, rl.WHITE)
