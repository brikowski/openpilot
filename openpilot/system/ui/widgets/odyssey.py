import math

import pyray as rl

from openpilot.system.ui.lib.application import GL_VERSION, gui_app
from openpilot.system.ui.widgets import Widget


# Wheel centers and the 120-pixel rim radius refer to the original 1774x887 illustration.
# Rotate only the rims, preserving the tire and body contours.
WHEEL_SHADER = GL_VERSION + """
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform float rotation;
out vec4 finalColor;

void main() {
  vec2 size = vec2(textureSize(texture0, 0));
  vec2 pixel = fragTexCoord * size;
  vec2 centers[2] = vec2[2](vec2(392.0, 623.0), vec2(1431.0, 623.0));
  float c = cos(rotation);
  float s = sin(rotation);
  for (int i = 0; i < 2; i++) {
    vec2 offset = pixel - centers[i];
    if (length(offset) < 120.0) {
      pixel = centers[i] + mat2(c, -s, s, c) * offset;
    }
  }
  finalColor = texture(texture0, pixel / size) * fragColor;
}
"""


class OdysseyAnimation(Widget):
  def __init__(self):
    super().__init__()
    self._texture = gui_app.texture("images/odyssey_sport.png")
    rl.gen_texture_mipmaps(self._texture)
    rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
    self._shader = rl.load_shader_from_memory(rl.ffi.NULL, WHEEL_SHADER)
    self._rotation_loc = rl.get_shader_location(self._shader, "rotation")
    self._rotation = rl.ffi.new("float[1]")
    self._elapsed = 0.0

  def _render(self, rect: rl.Rectangle):
    self._elapsed += rl.get_frame_time()
    scale = rect.width / self._texture.width
    # Scene coordinates follow the source artwork; tire contact is at y=780.
    distance = self._elapsed * 420.0
    road_y = rect.y + 776.0 * scale
    road = rl.Rectangle(rect.x, road_y, rect.width, 100.0 * scale)
    rl.draw_rectangle_rounded(road, 0.5, 12, (16, 19, 24, 255))

    rl.begin_scissor_mode(int(road.x), int(road.y), math.ceil(road.width), math.ceil(road.height))
    for i in range(math.ceil(self._texture.width / 260.0) + 1):
      x = rect.x + (i * 260.0 - distance % 260.0) * scale
      rl.draw_rectangle_rec(rl.Rectangle(x, road_y + 60.0 * scale, 130.0 * scale, 7.0 * scale), (118, 124, 134, 255))
    rl.end_scissor_mode()

    bob = math.sin(self._elapsed * math.tau) * 1.5 * scale
    car = rl.Rectangle(rect.x, rect.y + bob, rect.width, self._texture.height * scale)
    source = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    # A right-facing vehicle rolls clockwise at the same speed as the passing road.
    self._rotation[0] = (distance / 160.0) % math.tau
    rl.set_shader_value(self._shader, self._rotation_loc, self._rotation, rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT)
    rl.begin_shader_mode(self._shader)
    rl.draw_texture_pro(self._texture, source, car, rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_shader_mode()
