#!/usr/bin/env python3
"""Workshop-root wrapper delegating to canonical templates/blobster-sculptor/workspace/scripts/compile_blobster_pack.py."""
from __future__ import annotations

import sys
import types
from pathlib import Path

_CANONICAL = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "blobster-sculptor"
    / "workspace"
    / "scripts"
    / "compile_blobster_pack.py"
)

_mod = types.ModuleType("_canonical_compile_blobster_pack")
_mod.__file__ = str(_CANONICAL)
exec(compile(_CANONICAL.read_bytes(), str(_CANONICAL), "exec"), _mod.__dict__)

__doc__ = _mod.__doc__
for _k, _v in vars(_mod).items():
    if not _k.startswith("__"):
        globals()[_k] = _v


if __name__ == "__main__":
    sys.exit(_mod.main())
