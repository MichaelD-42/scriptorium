"""lib/office.py, lib/tesseract.py and lib/wsl.py: finding soffice and
tesseract, including a Windows install seen from WSL, and handing a Windows
program Windows paths."""

import sys

import pytest
import pytesseract.pytesseract as pt

import office
import paths
import tesseract as tesseract_lib
import wsl
from conftest import EXAMPLES_ROOT, fake_command, load_script

render = load_script("render-pages/scripts/render.py", "render_pages_tools")

# Maps a directory to C:\w\<its name>, like `wslpath -w` would to some Windows path.
FAKE_WSLPATH = 'import sys\nprint("C:\\\\w\\\\" + sys.argv[2].replace("\\\\", "/").rstrip("/").split("/")[-1])\n'


@pytest.fixture
def no_tools(tmp_path, monkeypatch):
    """Nothing on PATH, no override, not WSL."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv(office.ENV_VAR, raising=False)
    monkeypatch.delenv(tesseract_lib.ENV_VAR, raising=False)
    monkeypatch.setattr(wsl, "is_wsl", lambda: False)


@pytest.fixture
def fake_wsl(tmp_path, monkeypatch, no_tools):
    """WSL with C:\\ at tmp_path/c and a stub wslpath."""
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl, "DRIVE", tmp_path / "c")
    monkeypatch.setattr(wsl, "WSLPATH", str(fake_command(tmp_path / "bin", "wslpath", FAKE_WSLPATH)))
    return tmp_path / "c"


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


class TestFindSoffice:
    def test_the_env_var_wins(self, no_tools, monkeypatch):
        monkeypatch.setenv(office.ENV_VAR, "/opt/lo/soffice")
        assert office.find_soffice() == "/opt/lo/soffice"

    def test_nothing_found_is_none(self, no_tools):
        assert office.find_soffice() is None

    def test_wsl_finds_a_scoop_install_on_windows(self, fake_wsl):
        exe = _touch(fake_wsl / "Users/someone/scoop/apps/libreoffice/current/LibreOffice/program/soffice.exe")
        assert office.find_soffice() == str(exe)


class TestPdfCommand:
    def test_a_windows_soffice_from_wsl_gets_windows_paths(self, fake_wsl):
        cmd = office.pdf_command("/mnt/c/lo/soffice.exe", "/tmp/in/deck.pptx", "/tmp/x", "/tmp/x/profile")
        assert cmd == [
            "/mnt/c/lo/soffice.exe", "-env:UserInstallation=file:///C:/w/x/profile", "--headless",
            "--convert-to", "pdf", "--outdir", r"C:\w\tmp\x", r"C:\w\in\deck.pptx",
        ]

    def test_a_linux_soffice_gets_the_paths_as_they_are(self, tmp_path, no_tools):
        cmd = office.pdf_command("/usr/bin/soffice", tmp_path / "deck.pptx", tmp_path, tmp_path / "profile")
        assert cmd[1] == f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}"
        assert cmd[-2:] == [str(tmp_path), str(tmp_path / "deck.pptx")]


class TestRenderPptx:
    @pytest.mark.parametrize("override", [None, "missing-soffice-binary"])
    def test_no_soffice_is_one_actionable_line(self, pptx_doc, no_tools, monkeypatch, capsys, override):
        if override:
            monkeypatch.setenv(office.ENV_VAR, override)
        monkeypatch.setattr(sys, "argv", ["render.py", "--doc", pptx_doc])
        with pytest.raises(SystemExit) as exit_info:
            render.main()
        assert exit_info.value.code == 1
        err = capsys.readouterr().err.strip()
        assert "\n" not in err
        assert office.ENV_VAR in err and f"{pptx_doc}.pdf" in err

    def test_the_env_var_soffice_renders_the_slides(self, pptx_doc, tmp_path, no_tools, monkeypatch, capsys):
        stub = fake_command(tmp_path / "bin", "soffice", (
            "import shutil, sys\n"
            "out = sys.argv[sys.argv.index('--outdir') + 1]\n"
            f"shutil.copyfile(r'{EXAMPLES_ROOT / 'sample.pdf'}', out + '/' + sys.argv[-1].replace(chr(92), '/').split('/')[-1].rsplit('.', 1)[0] + '.pdf')\n"
        ))
        monkeypatch.setenv(office.ENV_VAR, str(stub))
        monkeypatch.setattr(sys, "argv", ["render.py", "--doc", pptx_doc, "--pages", "1"])
        render.main()
        assert paths.page_png(pptx_doc, 1).read_bytes()[:4] == b"\x89PNG"


class TestFindTesseract:
    def test_the_env_var_wins(self, no_tools, monkeypatch):
        monkeypatch.setenv(tesseract_lib.ENV_VAR, "/opt/t/tesseract")
        assert tesseract_lib.find_tesseract() == "/opt/t/tesseract"

    def test_wsl_finds_a_windows_install(self, fake_wsl, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        exe = _touch(fake_wsl / "Program Files/Tesseract-OCR/tesseract.exe")
        assert tesseract_lib.find_tesseract() == str(exe)

    def test_a_windows_tesseract_from_wsl_gets_windows_paths(self, fake_wsl, monkeypatch):
        calls = []
        monkeypatch.setattr(pt, "run_tesseract", lambda *a, **kw: calls.append((a, kw)))
        monkeypatch.setattr(pt, "tesseract_cmd", pt.tesseract_cmd)

        tesseract_lib.use_tesseract("/mnt/c/t/tesseract.exe")
        pt.run_tesseract(
            input_filename="/tmp/a/in.png", output_filename_base="/tmp/a/out",
            extension="tsv", lang="eng", config='--tessdata-dir "/home/u/td"',
        )

        assert pt.tesseract_cmd == "/mnt/c/t/tesseract.exe"
        assert calls == [((r"C:\w\a\in.png", r"C:\w\a\out", ), {
            "extension": "tsv", "lang": "eng", "config": r"--tessdata-dir 'C:\w\u\td'",
        })]
