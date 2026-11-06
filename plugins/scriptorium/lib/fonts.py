"""The document's running-text font size, shared by pdf-triage (which
records it as triage.json's `body_size`) and extract-text (which falls back
to it when run without `--body-size`), so the two can never disagree."""

import statistics


def document_body_size(document) -> float:
    """The document's dominant running-text font size, character-weighted
    across every page of a fitz document. Computed once, document-wide,
    because a per-page median is unstable on sparse pages (a page with only
    a heading and one caption line has no reliable "body" sample of its
    own) — extract_text.py uses this as a stable reference for classifying
    headings by relative size instead of recomputing it per page."""
    weighted_sizes = []
    for page in document:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_len = len(span["text"].strip())
                    if text_len:
                        weighted_sizes.extend([span["size"]] * text_len)
    return statistics.median(weighted_sizes) if weighted_sizes else 0.0
