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
