import math

import pyray as rl



# Both stages need the same GLSL version; raylib's device default vertex shader uses GLES 2.
WHEEL_VERTEX_SHADER = """
in vec3 vertexPosition;
in vec2 vertexTexCoord;
in vec4 vertexColor;
uniform mat4 mvp;
out vec2 fragTexCoord;
out vec4 fragColor;

void main() {
  fragTexCoord = vertexTexCoord;
  fragColor = vertexColor;
  gl_Position = mvp * vec4(vertexPosition, 1.0);
}
"""

# Cover the complete tires in the 1774x887 artwork, including the outer spokes and tread.
WHEEL_SHADER = """
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform float rotation;
out vec4 finalColor;

void main() {
  vec2 size = vec2(textureSize(texture0, 0));
  vec2 pixel = fragTexCoord * size;
  vec2 centers[2] = vec2[2](vec2(392.0, 623.0), vec2(1431.0, 623.0));
  vec2 radii = vec2(162.0, 156.0);
  float c = cos(rotation);
  float s = sin(rotation);
  for (int i = 0; i < 2; i++) {
    vec2 offset = (pixel - centers[i]) / radii;
    if (length(offset) < 1.0) {
      pixel = centers[i] + (mat2(c, -s, s, c) * offset) * radii;
      break;
    }
  }
  finalColor = texture(texture0, pixel / size) * fragColor;
}
"""


class OdysseyScene:
  def __init__(self, texture: rl.Texture, gl_version: str):
    self._texture = texture
    rl.gen_texture_mipmaps(self._texture)
    rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
    self._shader = rl.load_shader_from_memory(gl_version + WHEEL_VERTEX_SHADER, gl_version + WHEEL_SHADER)
    self._rotation_loc = rl.get_shader_location(self._shader, "rotation")
    self._rotation = rl.ffi.new("float[1]")

  @property
  def shader_ready(self) -> bool:
    return self._shader.id != rl.rl_get_shader_id_default()

  def draw(self, rect: rl.Rectangle, elapsed: float):
    scale = rect.width / self._texture.width
    # Scene coordinates follow the source artwork; tire contact is at y=780.
    distance = elapsed * 420.0
    road_y = rect.y + 776.0 * scale
    road = rl.Rectangle(rect.x, road_y, rect.width, 100.0 * scale)
    rl.draw_rectangle_rounded(road, 0.5, 12, (16, 19, 24, 255))

    rl.begin_scissor_mode(int(road.x), int(road.y), math.ceil(road.width), math.ceil(road.height))
    for i in range(math.ceil(self._texture.width / 260.0) + 1):
      x = rect.x + (i * 260.0 - distance % 260.0) * scale
      rl.draw_rectangle_rec(rl.Rectangle(x, road_y + 60.0 * scale, 130.0 * scale, 7.0 * scale), (118, 124, 134, 255))
    rl.end_scissor_mode()

    bob = math.sin(elapsed * math.tau) * 1.5 * scale
    car = rl.Rectangle(rect.x, rect.y + bob, rect.width, self._texture.height * scale)
    source = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    # A right-facing vehicle rolls clockwise at the same speed as the passing road.
    self._rotation[0] = (distance / 160.0) % math.tau
    rl.set_shader_value(self._shader, self._rotation_loc, self._rotation, rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT)
    rl.begin_shader_mode(self._shader)
    rl.draw_texture_pro(self._texture, source, car, rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_shader_mode()
