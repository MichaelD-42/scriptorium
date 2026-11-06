"""setup-environment/scripts/check_env.sh: the orchestrator stops only on
exit 1, so every fatal failure must exit 1."""

import os
import subprocess

from conftest import TOOLS_ROOT


def test_a_failed_uv_sync_is_fatal(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\n[ "$1" = sync ] && exit 2\necho "uv 0.0.0"\n')
    uv.chmod(0o755)
    result = subprocess.run(
        ["sh", str(TOOLS_ROOT / "setup-environment/scripts/check_env.sh"), str(tmp_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FATAL" in result.stdout
