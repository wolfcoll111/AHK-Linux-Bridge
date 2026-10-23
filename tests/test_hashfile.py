"""Corpus-backed HashFile() regression: CryptoAPI hashing is real."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.includes import load_script

CORPUS = Path(os.path.expanduser("~/Games/NatroMacro/src"))
HASHFILE = CORPUS / "lib" / "HashFile.ahk"


@pytest.mark.skipif(not HASHFILE.exists(), reason="NatroMacro corpus not installed")
@pytest.mark.parametrize("hash_type,algorithm", [(2, "md5"), (6, "sha512")])
def test_hashfile_uses_real_hashing(tmp_path, hash_type, algorithm):
    data = (b"AHK-Linux-Bridge HashFile test\n" * 60000) + bytes(range(256))
    target = tmp_path / "hashme.bin"
    target.write_bytes(data)
    script, _ = load_script(str(HASHFILE))
    rt = R.Runtime(script, DryBackend(), allow_processes=False)
    got = rt._eval_expr(f'HashFile("{target}", {hash_type})')
    assert got == hashlib.new(algorithm, data).hexdigest()
