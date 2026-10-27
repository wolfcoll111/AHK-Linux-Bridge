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


@pytest.mark.skipif(not HASHFILE.exists(), reason="NatroMacro corpus not installed")
def test_hashfile_does_not_share_its_local_accumulator(tmp_path):
    # HashVal is a function-local accumulator.  Before function scope was
    # modeled, the second call appended to the first digest, so Natro's
    # installedPatternHashes grew 128 -> 256 -> 384 hex chars per pattern.
    script, _ = load_script(str(HASHFILE))
    rt = R.Runtime(script, DryBackend(), allow_processes=False)
    paths = []
    for index in range(3):
        data = (b"pattern-%d\n" % index) * 700
        target = tmp_path / f"pattern-{index}.bin"
        target.write_bytes(data)
        paths.append((target, data))
    for target, data in paths:
        got = rt._eval_expr(f'HashFile("{target}", 6)')
        assert got == hashlib.sha512(data).hexdigest()
        assert len(got) == 128
