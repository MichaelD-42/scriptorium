"""setup-environment/scripts/check_env.sh: the orchestrator stops only on
exit 1, so every fatal failure must exit 1. A missing tool is never fatal:
the script says how to get it without root and records what it found in
runs/env.json."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import wsl
from conftest import PLUGIN_ROOT, TOOLS_ROOT

CHECK_ENV = TOOLS_ROOT / "setup-environment/scripts/check_env.sh"


def _stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def test_a_failed_uv_sync_is_fatal(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\n[ "$1" = sync ] && exit 2\necho "uv 0.0.0"\n')
    uv.chmod(0o755)
    result = subprocess.run(
        ["sh", str(CHECK_ENV), str(tmp_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FATAL" in result.stdout


@pytest.mark.skipif(wsl.is_wsl(), reason="WSL finds the Windows installs this test assumes are missing")
class TestTools:
    """Only the stubs are on PATH: uv runs the real resolver with this
    interpreter, and sudo/apt-get never reach the system."""

    def _run(self, tmp_path, *, sudo=False, **env):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        python = Path(sys.executable).as_posix()
        _stub(bin_dir, "uv", f'case "$1" in sync) exit 0 ;; run) shift 4; exec "{python}" "$@" ;; *) echo "uv 0.0.0" ;; esac')
        _stub(bin_dir, "apt-get", "exit 1")
        if sudo:  # cached credentials; the install itself fails
            _stub(bin_dir, "sudo", f'[ "$2" = true ] && exit 0\nprintf "%s\\n" "$@" >> "{(tmp_path / "sudo.log").as_posix()}"\nexit 1')
        # No home, scoop or AppData install of the real machine may count.
        home = {k: str(tmp_path) for k in ("HOME", "USERPROFILE", "SCOOP", "LOCALAPPDATA")}
        clean = {k: v for k, v in os.environ.items() if not k.startswith("SCRIPTORIUM_") and not k.lower().endswith("_proxy")}
        result = subprocess.run(
            [shutil.which("sh"), str(CHECK_ENV), str(PLUGIN_ROOT)],
            env={**clean, **home, "PATH": str(bin_dir), **env},
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout, json.loads((tmp_path / "runs" / "env.json").read_text())

    def test_without_sudo_it_names_the_options_that_need_no_root(self, tmp_path):
        out, env = self._run(tmp_path)
        assert env == {"tesseract": None, "soffice": None}
        assert "SCRIPTORIUM_TESSERACT" in out and "micromamba" in out
        assert "SCRIPTORIUM_SOFFICE" in out and "work/<doc>/<doc>.pdf" in out
        assert "sudo sh -c 'apt-get update && apt-get install -y libreoffice'" in out

    @pytest.mark.parametrize("names", [("http_proxy", "https_proxy"), ("HTTP_PROXY", "HTTPS_PROXY")])
    def test_sudo_gets_the_proxy_and_apt_refreshes_first(self, tmp_path, names):
        self._run(tmp_path, sudo=True, **{name: "http://proxy.invalid:3128" for name in names})
        log = (tmp_path / "sudo.log").read_text()
        assert "http_proxy=http://proxy.invalid:3128" in log
        assert "https_proxy=http://proxy.invalid:3128" in log
        assert "apt-get update && apt-get install -y tesseract-ocr" in log

    def test_a_tool_set_by_env_var_is_reported_and_not_installed(self, tmp_path):
        soffice = tmp_path / "LibreOffice" / "soffice.exe"
        soffice.parent.mkdir()
        soffice.write_bytes(b"")
        out, env = self._run(tmp_path, sudo=True, SCRIPTORIUM_SOFFICE=str(soffice))
        assert env == {"tesseract": None, "soffice": str(soffice)}
        assert f"soffice: ok, Windows install at {soffice}" in out
        assert "libreoffice" not in (tmp_path / "sudo.log").read_text()
