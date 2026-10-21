import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from openpilot.common.basedir import BASEDIR


@pytest.mark.parametrize("target", ["program", "directory"])
def test_cached_generated_cpp_tracks_header_layout(tmp_path, target):
  if shutil.which("c++") is None:
    pytest.skip("C++ compiler is required")

  # Exercise the actual progress walker in a small native build with generated source.
  source = (Path(BASEDIR) / "SConstruct").read_text()
  walker = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "get_scons_nodes")
  (tmp_path / "SConstruct").write_text(f'''
import os
import SCons.Node.FS
env = Environment(ENV=os.environ, CPPPATH=['include'])
CacheDir('cache')
generated = env.Command('generated.cpp', 'template.txt', Copy('$TARGET', '$SOURCE'))
program = env.Program('layout', generated)
{ast.get_source_segment(source, walker)}
get_scons_nodes(program if {target!r} == 'program' else [Dir('.')])
''')
  (tmp_path / "template.txt").write_text('#include "layout.h"\n#include <cstdio>\nint main() { printf("%zu\\n", sizeof(Layout)); }\n')
  (tmp_path / "include").mkdir()
  header = tmp_path / "include/layout.h"

  def build():
    result = subprocess.run([sys.executable, "-c", "from SCons.Script import main; main()", "-Q"],
                            cwd=tmp_path, env=os.environ, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout

  def layout_size():
    return int(subprocess.check_output([str(tmp_path / "layout")], text=True))

  header.write_text("class Layout { public: int padding; int value; };\n")
  build()
  assert layout_size() == 8

  # A new checkout retains the shared build cache but has no generated files or signatures.
  for name in ("generated.cpp", "generated.o", "layout", ".sconsign.dblite"):
    (tmp_path / name).unlink()
  header.write_text("class Layout { public: int value; };\n")
  output = build()
  assert "Retrieved `generated.cpp' from cache" in output
  assert layout_size() == 4
