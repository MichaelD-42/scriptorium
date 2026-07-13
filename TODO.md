# The Scriptorium TODO list for Claude

[x] Docs: architecture documentation of the loop and tooling in docs/
[x] Convert diagrams to plantUML or mermaid charts
[x] Input document: pptx
[x] Input document: docx
[x] Input document: xlsx
[x] Input document: html
[x] Input document: images
[x] Output: reqif
[x] Output: reqifx
[x] Feature: zip package of output result
[ ] Feature: create from extracted content a local running RAG vector database (the data package necessary to load the data)
[ ] Portability: Tier-3 vision escalation currently relies on Claude Code's Read-tool-on-image (agent reads PNG directly into context) — not available the same way in Codex CLI or GitHub Copilot's coding agent. Make it a script (`vision-page`) that calls a multimodal model API directly with the rendered PNG, returning a shard like `ocr.py` does, so the pipeline is harness-agnostic.
