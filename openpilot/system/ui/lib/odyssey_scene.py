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

# Fit each rim's ellipse in the 1774x887 artwork; leave the tires and body intact.
WHEEL_SHADER = """
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform float distance;
out vec4 finalColor;

void main() {
  vec2 size = vec2(textureSize(texture0, 0));
  vec2 pixel = fragTexCoord * size;
  vec4 color = texture(texture0, fragTexCoord);
  vec2 centers[2] = vec2[2](vec2(207.0, 580.0), vec2(1020.0, 606.0));
  vec2 radii[2] = vec2[2](vec2(98.0, 138.0), vec2(149.0, 159.0));
  float tilts[2] = float[2](0.15, 0.10);
  float tireRadii[2] = float[2](188.0, 224.0);
  for (int i = 0; i < 2; i++) {
    float ct = cos(tilts[i]);
    float st = sin(tilts[i]);
    mat2 basis = mat2(ct, st, -st, ct);
    vec2 offset = (transpose(basis) * (pixel - centers[i])) / radii[i];
    if (length(offset) < 1.0) {
      float angle = distance / tireRadii[i];
      float c = cos(angle);
      float s = sin(angle);
      pixel = centers[i] + basis * ((mat2(c, -s, s, c) * offset) * radii[i]);
      // Feather into the stationary rim lip where the drawn fenders obscure its edge.
      color = mix(color, texture(texture0, pixel / size), 1.0 - smoothstep(0.85, 1.0, length(offset)));
      break;
    }
  }
  finalColor = color * fragColor;
}
"""


class OdysseyScene:
  def __init__(self, texture: rl.Texture, gl_version: str):
    self._texture = texture
    rl.gen_texture_mipmaps(self._texture)
    rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
    self._shader = rl.load_shader_from_memory(gl_version + WHEEL_VERTEX_SHADER, gl_version + WHEEL_SHADER)
    self._distance_loc = rl.get_shader_location(self._shader, "distance")
    self._distance = rl.ffi.new("float[1]")

  @property
  def shader_ready(self) -> bool:
    return self._shader.id != rl.rl_get_shader_id_default()

  def draw(self, rect: rl.Rectangle, elapsed: float):
    scale = rect.width / self._texture.width
    # The road follows the two contact patches in the three-quarter perspective.
    distance = elapsed * 420.0
    def road_point(x, depth):
      return rl.Vector2(rect.x + x * scale, rect.y + (745.0 + 0.055 * x + depth) * scale)

    end = float(self._texture.width)
    rl.draw_triangle(road_point(0.0, 0.0), road_point(0.0, 44.0), road_point(end, 0.0), (16, 19, 24, 255))
    rl.draw_triangle(road_point(end, 0.0), road_point(0.0, 44.0), road_point(end, 44.0), (16, 19, 24, 255))
    rl.begin_scissor_mode(int(rect.x), int(rect.y), math.ceil(rect.width), math.ceil(rect.height))
    for i in range(math.ceil(self._texture.width / 260.0) + 1):
      x = i * 260.0 - distance % 260.0
      rl.draw_line_ex(road_point(x, 33.0), road_point(x + 130.0, 33.0), 7.0 * scale, (118, 124, 134, 255))
    rl.end_scissor_mode()

    bob = math.sin(elapsed * math.tau) * 1.5 * scale
    car = rl.Rectangle(rect.x, rect.y + bob, rect.width, self._texture.height * scale)
    source = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    # Each right-facing wheel rolls clockwise at the passing road's speed.
    self._distance[0] = distance % (math.tau * 188.0 * 224.0)
    rl.set_shader_value(self._shader, self._distance_loc, self._distance, rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT)
    rl.begin_shader_mode(self._shader)
    rl.draw_texture_pro(self._texture, source, car, rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_shader_mode()
