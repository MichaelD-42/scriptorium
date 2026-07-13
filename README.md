# Scriptorium

[![CI](https://github.com/MichaelD-42/scriptorium/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelD-42/scriptorium/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](plugins/scriptorium/pyproject.toml)

A Claude Code plugin that turns your documents into clean, structured text —
tables, pictures and all — that you can actually read, search, or hand to
another tool. Feed it a PDF, a Word doc, a PowerPoint deck, an Excel sheet, an
HTML page, or even a plain scanned image; it reads the thing so you don't have
to squint at it.

Under the hood it's a small team of AI agents checking each other's work
(more on that later, for the curious). From where you're standing, it's just:
drop a file in, get a tidy document out.

## What goes in, what comes out

| You give it | It gives you back |
|---|---|
| PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), HTML, or an image (`.png`/`.jpg`/`.jpeg`/`.webp`/`.tiff`) | Markdown, HTML, an OKF bundle, or ReqIF — your pick |

Not sure which output to pick? A quick cheat sheet:

- **Markdown** (default) — the safe, everyday choice. Readable anywhere, easy
  to skim, easy to paste into other tools.
- **HTML** — same content, browser-ready, diagrams render inline.
- **OKF bundle** — the document split into small linked files instead of one
  big one. Handy if the doc is huge or you're feeding it into a search/RAG
  pipeline later.
- **ReqIF** (`.reqif`/`.reqifz`) — the standard requirements-interchange
  format. Only reach for this if you're feeding a requirements-management tool
  (DOORS, Polarion, etc.) — otherwise it's more format than you need.

## How to use it

You don't need to memorize commands. Just talk to Claude:

1. Drop your file(s) into the project's `input/` folder.
2. Tell Claude something like *"extract the text from spec.pdf"* — it'll run
   the extraction pipeline for you.
3. Open `output/<your-file>/` and there's your result.

Nothing to install by hand — the plugin sets up its own environment (Python,
OCR engine, the works) the first time it runs. If you'd rather drive it
yourself instead of asking Claude, the direct command is
`/scriptorium:extract` (see [Command reference](#command-reference) below for
the flags) — but for day-to-day use, just asking Claude is the easier path.

## Reading your results

Once a document finishes, `output/<your-file>/` contains:

- **`<your-file>.md`** (or `.html` / `.reqif`, depending on the format you
  picked) — your actual document, extracted and cleaned up.
- **`assets/`** — every picture and diagram it pulled out, referenced from
  the document above.
- **`grade-report.json`** — the pipeline's own quality check. You don't need
  to read this unless something looks off; it's there so you can trust a
  passing result without re-checking it by hand.

Run the extraction again later and already-finished documents are simply
skipped — only new or retrying ones get processed.

## "It said `needs-human` — now what?"

Every document is checked by an independent reviewer step before it's handed
back to you — it's not just trusting the first attempt. Most documents pass
on the first or second try. Occasionally one doesn't: the pipeline tried its
best techniques (including having Claude read the page directly, like a
person would) and still wasn't confident enough to call it done.

That's what `needs-human` means: not "broken," just "this one's worth a
five-minute look before you trust it." Go to `output/<your-file>/`, check
`grade-report.json` for which pages it flagged and why, and take a look at
those pages yourself. Common culprits: a very messy scan, handwriting, or a
page that's mostly a complex diagram.

## Quick troubleshooting

- **Nothing happened when I asked Claude** — check your file actually landed
  in `input/` and has a supported extension (see the table above).
- **It's taking a while on a scanned document** — that's expected. Scanned
  pages and photos need OCR (and sometimes Claude reading the image directly),
  which is slower than a document with real, selectable text.
- **A picture or diagram looks wrong in the output** — flag it; the grading
  step usually catches this and retries automatically, but it's not
  infallible.
- **First run seems slow** — that's one-time environment setup (installing
  the OCR engine, etc.). Later runs skip straight to extraction.

## Command reference

If you're driving it directly instead of asking Claude in plain English:

```
/scriptorium:extract [--doc <name>] [--format md|html|okf|reqif|reqifz] [--zip]
```

- `--doc <name>` — process just one file from `input/` instead of everything
  waiting there.
- `--format` — pick the output format from the table above (default: `md`).
- `--zip` — also package the result folder into a single `.zip`.

## How it works (for the curious)

Under the friendly exterior, Scriptorium is a small team of AI agents rather
than one big model doing everything at once. A document gets triaged
page-by-page, cheap and reliable extraction runs first, and the expensive
stuff (OCR, then Claude actually looking at the page) only kicks in where
it's genuinely needed. An independent grader — never the agent that did the
extracting, because grading your own homework is a bit of a conflict of
interest — decides whether the result is good enough or needs another pass.

If you want the full architectural tour — the agent tree, the escalation
ladder, why pages are processed in isolated batches — see
[`docs/architecture.md`](docs/architecture.md) for the design and
[`docs/tooling.md`](docs/tooling.md) for the skills/scripts/schemas that
implement it. If you're a developer looking to modify this repo, see
[`AGENTS.md`](AGENTS.md).

## Installing this plugin

In a Claude Code session:

```
/plugin marketplace add MichaelD-42/scriptorium
/plugin install scriptorium@scriptorium
```

Pull future updates with `/plugin marketplace update scriptorium`.

