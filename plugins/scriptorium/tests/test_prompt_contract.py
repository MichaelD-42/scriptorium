"""The command and agent prompts call scripts by path, subcommand and flag.
Nothing runs that prose in CI, so check it against the scripts: every
script named in a code span exists, and every subcommand and --flag written
after it is one the script's argparse defines."""

import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
PROMPTS = sorted([*PLUGIN.glob("commands/*.md"), *PLUGIN.glob("agents/*.md")])
SCRIPTS = sorted(PLUGIN.glob("tools/*/scripts/*.py"))
# `<input_format>-triage/scripts/triage.py` and similar placeholders.
SCRIPT_REF = re.compile(
    r"(?:(<[a-z_]+>|[a-z]+)?-?([a-z-]*)/scripts/)?\b([a-z_]+\.py)\b"
)
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")


def code_spans(text: str):
    """(span, gap): each fenced line is a span with gap None; an inline span
    (it may wrap across lines) comes with the prose since the previous span
    of its paragraph, or None if it opens the paragraph."""
    for part in re.split(r"(^```[^\n]*\n.*?^```)", text, flags=re.M | re.S):
        if part.startswith("```"):
            for line in part.splitlines()[1:-1]:
                yield line, None
            continue
        for paragraph in re.split(r"\n\s*\n", part):
            prev_end = None
            for m in re.finditer(r"`([^`]+)`", paragraph):
                gap = None if prev_end is None else paragraph[prev_end : m.start()]
                prev_end = m.end()
                yield m.group(1), gap


def resolve(ref: re.Match) -> list[Path]:
    prefix, rest, name = ref.groups()
    candidates = [s for s in SCRIPTS if s.name == name]
    if prefix and not prefix.startswith("<"):
        folder = f"{prefix}-{rest}" if rest else prefix
        candidates = [s for s in candidates if s.parent.parent.name == folder]
    elif prefix:  # a placeholder: every <format>-<rest> folder
        candidates = [s for s in candidates if s.parent.parent.name.endswith(f"-{rest}")]
    return candidates


def calls() -> list[tuple[str, re.Match, str]]:
    """(prompt, script reference, the text after it up to the next reference).
    A flag span right after a script's span, joined by a short connector
    (`... --pages <list>`, plus `--ocr-lang <x>`), continues that script's call."""
    out = []
    for prompt in PROMPTS:
        last = None
        for span, gap in code_spans(prompt.read_text(encoding="utf-8")):
            refs = list(SCRIPT_REF.finditer(span))
            joined = gap is not None and len(gap) <= 20 and not re.search(r"[.;]", gap)
            if not refs and span.startswith("--") and last and joined:
                out.append((prompt.name, last, span))
                continue
            last = refs[-1] if refs else None
            for i, ref in enumerate(refs):
                end = refs[i + 1].start() if i + 1 < len(refs) else len(span)
                out.append((prompt.name, ref, span[ref.end() : end]))
    return out


CALLS = calls()


def test_the_prompts_name_scripts():
    assert len(CALLS) > 60  # the parser still finds the prompts' calls


@pytest.mark.parametrize(
    "prompt,ref,args", CALLS, ids=[f"{p}:{r.group(0)}" for p, r, _ in CALLS]
)
def test_script_subcommand_and_flags_exist(prompt, ref, args):
    scripts = resolve(ref)
    assert scripts, f"{prompt}: {ref.group(0)} names no script under tools/"
    words = args.replace('"', " ").split()
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        if (
            words
            and re.fullmatch(r"[a-z][a-z-]*", words[0])
            and "add_subparsers" in source
        ):
            assert f'"{words[0]}"' in source, (
                f"{prompt}: {script.name} has no subcommand {words[0]}"
            )
        for flag in FLAG.findall(args):
            assert f'"{flag}"' in source, f"{prompt}: {script.name} has no {flag}"
