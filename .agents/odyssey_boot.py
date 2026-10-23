#!/usr/bin/env python3
"""Early Odyssey background for AGNOS, with a validated static splash-image packer."""
import argparse
import hashlib
import struct
import time
from pathlib import Path

MAGIC_SHA256 = 'c4416e66b127b31c17d08e6723ad46d12af7683e56626512d66c708b5f347ac9'
BMP_OFFSET = 16384
PATCHES = (
  (
    '''def show_background(tex, pos):
  rl.begin_drawing()
  rl.draw_texture(tex, int(pos.x), int(pos.y), rl.WHITE)
  rl.end_drawing()
  power_screen()
''',
    '''def show_background(tex, pos, power=True):
  rl.begin_drawing()
  _odyssey.draw_background(tex, pos)
  rl.end_drawing()
  if power:
    power_screen()
''',
  ),
  (
    '    if not clients and need_background:\n      need_background = False\n      show_background(tex, pos)\n',
    '''    if not clients and (need_background or _odyssey.animated):
      show_background(tex, pos, power=need_background)
      need_background = False
''',
  ),
  (
    '    try:\n      client, _ = server.accept()\n    except Exception:\n      continue\n',
    '''    try:
      server.settimeout(1 / 30 if not clients and _odyssey.animated else 0.1)
      client, _ = server.accept()
    except Exception:
      continue
''',
  ),
)


def patch_magic(source: str) -> str:
  if hashlib.sha256(source.encode()).hexdigest() != MAGIC_SHA256:
    raise ValueError('unrecognized AGNOS compositor; retaining the stock background')
  for old, new in PATCHES:
    if source.count(old) != 1:
      raise ValueError('AGNOS compositor hook is not unique')
    source = source.replace(old, new)
  return source


class EarlyBackground:
  def __init__(self):
    self._scene = None
    self._attempted = False

  @property
  def animated(self) -> bool:
    return self._scene is not None

  def draw_background(self, texture, position):
    import pyray as rl
    if not self._attempted:
      self._attempted = True
      try:
        from odyssey_scene import OdysseyScene
        image = rl.load_texture(str(Path(__file__).with_name('odyssey_sport.png')))
        scene = OdysseyScene(image, '#version 300 es\nprecision highp float;\n')
        if not scene.shader_ready:
          raise RuntimeError('Odyssey wheel shader did not link')
        self._scene = scene
        print('Odyssey early boot animation ready', flush=True)
      except Exception as exc:
        print(f'Odyssey early boot: {exc}; retaining stock background', flush=True)
    if self._scene is not None:
      try:
        width = min(1200.0, rl.get_screen_width() * 0.6)
        rect = rl.Rectangle((rl.get_screen_width() - width) / 2, (rl.get_screen_height() - width / 2) / 2, width, width / 2)
        rl.clear_background(rl.BLACK)
        self._scene.draw(rect, time.monotonic())
        return
      except Exception as exc:
        print(f'Odyssey early boot: {exc}; retaining stock background', flush=True)
        self._scene = None
    rl.draw_texture_ex(texture, position, 0.0, 1.0, rl.WHITE)


def bmp_pixels(data: bytes) -> tuple[int, int, int, bytes]:
  if len(data) < 54 or data[:2] != b'BM':
    raise ValueError('expected a complete BMP')
  file_size, offset, header, width, height, planes, bpp, compression = struct.unpack_from('<I4xIIiiHHI', data, 2)
  if header != 40 or offset != 54 or width <= 0 or height <= 0 or planes != 1 or bpp != 24 or compression != 0:
    raise ValueError('expected an uncompressed, bottom-up 24-bit BMP')
  size = ((width * 3 + 3) // 4 * 4) * height
  if file_size != offset + size or file_size > len(data):
    raise ValueError('BMP payload size does not match its dimensions')
  return width, height, offset, data[offset:file_size]


def pack_splash(original: bytes, frame: bytes) -> bytes:
  if original[:8] != b'DDPH\x01\0\0\0' or any(original[8:BMP_OFFSET]):
    raise ValueError('expected a single-image DDPH v1 splash')
  width, height, offset, pixels = bmp_pixels(original[BMP_OFFSET:])
  frame_width, frame_height, _, frame_pixels = bmp_pixels(frame)
  if (width, height) != (frame_width, frame_height):
    raise ValueError('replacement dimensions differ from the original splash')
  end = BMP_OFFSET + offset + len(pixels)
  if any(original[end:]):
    raise ValueError('unexpected extra splash data')
  # Keep the partition layout, image metadata, and all padding byte-for-byte intact.
  return original[:BMP_OFFSET + offset] + frame_pixels + original[end:]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--pack-splash', nargs=3, metavar=('ORIGINAL', 'BMP_FRAME', 'OUTPUT'))
  args = parser.parse_args()
  if args.pack_splash:
    original, frame, output = map(Path, args.pack_splash)
    candidate = pack_splash(original.read_bytes(), frame.read_bytes())
    output.write_bytes(candidate)
    print(f'{output}: {len(candidate)} bytes, sha256={hashlib.sha256(candidate).hexdigest()}')
    return
  original = Path('/usr/comma/magic.py')
  source = original.read_text()
  try:
    source = patch_magic(source)
  except ValueError as exc:
    print(f'Odyssey early boot: {exc}', flush=True)
  namespace = {'__name__': '__main__', '__file__': str(original), '_odyssey': EarlyBackground()}
  exec(compile(source, str(original), 'exec'), namespace)


if __name__ == '__main__':
  main()
