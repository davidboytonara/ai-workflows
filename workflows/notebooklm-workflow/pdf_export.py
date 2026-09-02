#!/usr/bin/env python3
"""Convert a local Markdown file to PDF — no cloud call, no NotebookLM API.

Fills the one native output gap in this workflow: `download report`,
`download mind-map`, and `download data-table` write Markdown/JSON/CSV, and
none of the `generate.py`/`artifact.py` types has a native PDF format. This
converts an already-downloaded Markdown file to PDF locally, entirely
offline — useful whenever the destination expects a PDF (e.g. an audit or
regulatory briefing doc), not just a source of source-file ingestion.

Usage:
  pdf_export.py <input.md> <output.pdf> [--title "<title>"]

Exit codes: 0 success, 1 conversion failure, 2 usage, 3 missing deps.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import bootstrap  # noqa: E402

PAGE_CSS = """
  @page { size: A4; margin: 2.2cm 2cm; }
  body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; }
  h1 { font-size: 20pt; border-bottom: 1.5pt solid #1a1a1a; padding-bottom: 6pt; margin-top: 0; }
  h2 { font-size: 14.5pt; margin-top: 22pt; }
  h3 { font-size: 12pt; margin-top: 16pt; }
  p, li { orphans: 3; widows: 3; }
  table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 9.5pt; }
  th, td { border: 0.5pt solid #999; padding: 5pt 7pt; text-align: left; }
  th { background-color: #eeeeee; }
  code, pre { font-family: "Courier New", monospace; font-size: 9pt; }
  pre { background-color: #f4f4f4; padding: 8pt; border: 0.5pt solid #ddd; }
  blockquote { border-left: 3pt solid #999; margin-left: 0; padding-left: 10pt; color: #444444; }
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Markdown file to PDF (local, offline, no cloud call)."
    )
    parser.add_argument("input", help="Path to the source .md file")
    parser.add_argument("output", help="Path to write the .pdf file")
    parser.add_argument(
        "--title", default=None,
        help="PDF document title (default: the file's first H1, else its filename)",
    )
    return parser.parse_args()


def first_h1(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def main() -> int:
    args = parse_args()
    src = Path(args.input)
    if not src.is_file():
        print(f"pdf_export: input not found: {src}", file=sys.stderr)
        return 2

    bootstrap()
    try:
        import markdown as md_lib
        from xhtml2pdf import pisa
    except ImportError as exc:
        print(
            f"pdf_export: missing dependency ({exc}). Run "
            "$HOME/.agents/.venv/bin/python .agents/workflows/notebooklm-workflow/_env.py "
            "--bootstrap to install markdown + xhtml2pdf into the shared venv.",
            file=sys.stderr,
        )
        return 3

    text = src.read_text(encoding="utf-8")
    body_html = md_lib.markdown(text, extensions=["extra", "sane_lists", "tables"])
    title = args.title or first_h1(text) or src.stem
    full_html = (
        f"<html><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{PAGE_CSS}</style></head><body>{body_html}</body></html>"
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        result = pisa.CreatePDF(full_html, dest=fh)

    if result.err:
        print(f"pdf_export: conversion failed ({result.err} error(s))", file=sys.stderr)
        return 1

    print(f"pdf_export: wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
