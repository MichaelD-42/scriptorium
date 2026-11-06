"""ensure_language.py's --extra parsing: the orchestrator passes the
plugin's ocr_languages option, which Claude Code leaves as a literal
`${user_config.ocr_languages}` placeholder when the option is not set."""

import json

from conftest import load_script

ensure_language = load_script("setup-environment/scripts/ensure_language.py", "ensure_language")


def test_codes_from_a_comma_list():
    assert ensure_language.extra_languages(" deu, fra ,chi_sim,,") == ["deu", "fra", "chi_sim"]


def test_an_unset_option_placeholder_is_ignored_quietly(capsys):
    assert ensure_language.extra_languages("${user_config.ocr_languages}") == []
    assert capsys.readouterr().err == ""


def test_anything_else_that_is_no_language_code_is_dropped_with_a_warning(capsys):
    assert ensure_language.extra_languages("deu,../x,fra;rm -rf") == ["deu"]
    err = capsys.readouterr().err
    assert "warning:" in err and "../x" in err and "fra;rm -rf" in err


def test_a_pack_only_in_the_fallback_dir_is_passed_as_tessdata_prefix(tmp_path, monkeypatch, capsys):
    """pacman machine, system tessdata has eng only, an earlier run downloaded
    deu into the fallback dir: tesseract must be pointed there, or it OCRs
    German as English."""
    system, fallback = tmp_path / "system", tmp_path / "fallback"
    system.mkdir(), fallback.mkdir()
    (system / "eng.traineddata").write_text("x")
    (fallback / "deu.traineddata").write_text("x")
    lib = ensure_language.tesseract_lib
    monkeypatch.setattr(lib, "find_tesseract", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(lib, "tessdata_dir_for", lambda path: system)
    monkeypatch.setattr(lib, "user_tessdata_dir", lambda: fallback)
    monkeypatch.setattr(ensure_language, "detect_script", lambda image: "Latin")
    monkeypatch.setattr(ensure_language, "detect_package_manager", lambda: "pacman")
    monkeypatch.setattr(ensure_language, "installed_languages", lambda: {"eng", "deu"})
    monkeypatch.setattr(ensure_language.sys, "platform", "linux")
    monkeypatch.setattr(ensure_language.sys, "argv", ["ensure_language.py", "page1.png", "--extra", "deu"])

    ensure_language.main()

    result = json.loads(capsys.readouterr().out)
    assert result["lang_flag"] == "deu+eng" and result["tessdata_prefix"] == str(fallback)
    assert (fallback / "eng.traineddata").is_file()  # the prefix dir must hold every language


def test_the_system_tessdata_dir_is_the_one_tesseract_reports(tmp_path):
    """Linux packages keep tessdata in /usr/share, not beside the binary."""
    data = tmp_path / "share" / "tessdata"
    data.mkdir(parents=True)
    binary = tmp_path / "bin" / "tesseract"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\necho \'List of available languages in "{data}/" (1):\'\necho eng\n')
    binary.chmod(0o755)
    assert ensure_language.tesseract_lib.tessdata_dir_for(str(binary)) == data


def _fake_tesseract(tmp_path, monkeypatch, stdout):
    binary = tmp_path / "tesseract"
    binary.write_text(f"#!/bin/sh\ncat <<'OUT'\n{stdout}\nOUT\n")
    binary.chmod(0o755)
    monkeypatch.setattr(ensure_language.tesseract_lib, "find_tesseract", lambda: str(binary))


def test_installed_languages_reads_list_langs_and_the_fallback_dir(tmp_path, monkeypatch):
    _fake_tesseract(tmp_path, monkeypatch, 'List of available languages in "/x/" (3):\neng\nosd\nfra')
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    (fallback / "deu.traineddata").write_text("x")
    monkeypatch.setattr(ensure_language.tesseract_lib, "user_tessdata_dir", lambda: fallback)
    assert ensure_language.installed_languages() == {"eng", "fra", "deu"}


def test_detect_script_reads_osd_and_survives_a_missing_binary(tmp_path, monkeypatch):
    _fake_tesseract(tmp_path, monkeypatch, "Orientation in degrees: 0\nScript: Cyrillic\nScript confidence: 9")
    assert ensure_language.detect_script("page.png") == "Cyrillic"
    monkeypatch.setattr(ensure_language.tesseract_lib, "find_tesseract", lambda: str(tmp_path / "missing"))
    assert ensure_language.detect_script("page.png") is None


def test_install_without_cached_sudo_prints_the_manual_command(monkeypatch, capsys):
    monkeypatch.setattr(ensure_language, "can_sudo", lambda: False)
    assert ensure_language.install_language("deu", "pacman") is False
    assert "sudo pacman -S --noconfirm tesseract-data-deu" in capsys.readouterr().err


def test_install_with_sudo_runs_the_managers_package(monkeypatch):
    calls = []
    monkeypatch.setattr(ensure_language, "can_sudo", lambda: True)
    monkeypatch.setattr(
        ensure_language.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or ensure_language.subprocess.CompletedProcess(cmd, 0),
    )
    assert ensure_language.install_language("deu", "apt-get") is True
    assert ensure_language.install_language("deu", "winget") is False  # Windows: download instead
    assert calls == [["sudo", "-n", "apt-get", "install", "-y", "tesseract-ocr-deu"]]


def test_download_lands_in_the_fallback_dir_and_reports_failure(tmp_path, monkeypatch, capsys):
    fallback = tmp_path / "fallback"
    monkeypatch.setattr(ensure_language.tesseract_lib, "user_tessdata_dir", lambda: fallback)
    urls = []
    monkeypatch.setattr(
        ensure_language.urllib.request,
        "urlretrieve",
        lambda url, target: urls.append(url) or target.write_text("pack"),
    )
    assert ensure_language.download_language("deu") is True
    assert (fallback / "deu.traineddata").read_text() == "pack"
    assert urls == [ensure_language.TESSDATA_URL.format(lang="deu")]

    def offline(url, target):
        raise OSError("no network")

    monkeypatch.setattr(ensure_language.urllib.request, "urlretrieve", offline)
    assert ensure_language.download_language("fra") is False
    assert "download failed for fra" in capsys.readouterr().err


def _main(monkeypatch, capsys, manager, installed_after, install_ok=True):
    """Run main() wanting eng+deu with only eng installed at first."""
    first = iter([{"eng"}])  # before any install; every later call sees installed_after
    downloads = []
    monkeypatch.setattr(ensure_language, "detect_script", lambda image: "Latin")
    monkeypatch.setattr(ensure_language, "detect_package_manager", lambda: manager)
    monkeypatch.setattr(ensure_language, "installed_languages", lambda: next(first, installed_after))
    monkeypatch.setattr(ensure_language, "install_language", lambda lang, m: install_ok)
    monkeypatch.setattr(ensure_language, "download_language", lambda lang: downloads.append(lang) or True)
    monkeypatch.setattr(ensure_language, "resolve_tessdata_override", lambda langs: None)
    monkeypatch.setattr(ensure_language.sys, "platform", "linux")
    monkeypatch.setattr(ensure_language.sys, "argv", ["ensure_language.py", "p.png", "--extra", "deu"])
    ensure_language.main()
    return json.loads(capsys.readouterr().out), downloads


def test_a_package_manager_install_makes_the_language_usable(monkeypatch, capsys):
    result, downloads = _main(monkeypatch, capsys, "pacman", {"eng", "deu"})
    assert (result["newly_installed"], result["lang_flag"], downloads) == (["deu"], "deu+eng", [])


def test_a_failed_install_drops_the_language_instead_of_breaking_ocr(monkeypatch, capsys):
    result, downloads = _main(monkeypatch, capsys, "pacman", {"eng"}, install_ok=False)
    assert (result["still_missing"], result["lang_flag"], downloads) == (["deu"], "eng", [])


def test_no_package_manager_falls_back_to_download(monkeypatch, capsys):
    result, downloads = _main(monkeypatch, capsys, None, {"eng", "deu"})
    assert (downloads, result["newly_installed"], result["lang_flag"]) == (["deu"], ["deu"], "deu+eng")


def test_no_override_when_the_system_dir_has_everything_or_the_fallback_nothing(tmp_path, monkeypatch):
    system, fallback = tmp_path / "system", tmp_path / "fallback"
    system.mkdir()
    (system / "eng.traineddata").write_text("x")
    lib = ensure_language.tesseract_lib
    monkeypatch.setattr(lib, "find_tesseract", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(lib, "tessdata_dir_for", lambda path: system)
    monkeypatch.setattr(lib, "user_tessdata_dir", lambda: fallback)
    assert ensure_language.resolve_tessdata_override(["eng"]) is None
    assert ensure_language.resolve_tessdata_override(["eng", "deu"]) is None  # deu is nowhere
