import hashlib
import importlib.util
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('odyssey_boot', Path(__file__).with_name('odyssey_boot.py'))
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


def bmp(width=2, height=2, value=0):
  pixels = bytes([value]) * (((width * 3 + 3) // 4 * 4) * height)
  return (struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54) +
          struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0) + pixels)


def splash(frame):
  return b'DDPH\x01\0\0\0' + bytes(boot.BMP_OFFSET - 8) + frame + bytes(128)


def test_splash_preserves_partition_metadata_and_padding():
  original = splash(bmp(value=10))
  candidate = boot.pack_splash(original, bmp(value=20))
  start = boot.BMP_OFFSET + 54
  assert len(candidate) == len(original)
  assert candidate[:start] == original[:start]
  assert candidate[start:start + 16] == bytes([20]) * 16
  assert candidate[start + 16:] == original[start + 16:]


def test_splash_rejects_incompatible_or_truncated_frames():
  original = splash(bmp())
  compressed = bytearray(bmp())
  struct.pack_into('<I', compressed, 30, 1)
  for bad in (bmp(width=3), bmp()[:-1], bytes(compressed)):
    with pytest.raises(ValueError):
      boot.pack_splash(original, bad)
  with pytest.raises(ValueError):
    boot.pack_splash(original[:-1] + b'x', bmp())


def test_background_yields_to_display_clients(monkeypatch):
  source = (boot.PATCHES[0][0] + '\ndef cycle(clients, need_background):\n' + boot.PATCHES[1][0] +
            '\ndef accept_client():\n  while True:\n' + boot.PATCHES[2][0])
  monkeypatch.setattr(boot, 'MAGIC_SHA256', hashlib.sha256(source.encode()).hexdigest())
  events = []
  renderer = SimpleNamespace(animated=True, draw_background=lambda *_: events.append('frame'))
  raylib = SimpleNamespace(begin_drawing=lambda: events.append('begin'), end_drawing=lambda: events.append('end'))
  namespace = {'rl': raylib, '_odyssey': renderer, 'tex': None, 'pos': None, 'power_screen': lambda: events.append('power')}
  exec(boot.patch_magic(source), namespace)
  namespace['cycle']({object()}, True)
  assert events == []
  namespace['cycle'](set(), False)
  assert events == ['begin', 'frame', 'end']
  events.clear()
  namespace['cycle'](set(), True)
  assert events == ['begin', 'frame', 'end', 'power']
  events.clear()
  renderer.animated = False
  namespace['cycle'](set(), False)
  assert events == []


def test_unknown_compositor_is_not_patched():
  with pytest.raises(ValueError, match='unrecognized'):
    boot.patch_magic('unrecognized compositor')
