# Third-Party Notices

This repository contains no vendored third-party code, binaries, or browser builds.
Everything listed below is downloaded by you at install time, directly from its
original publisher, under that publisher's own license.

## Python dependencies

Declared per workflow in seven `requirements.txt` files. All are permissively
licensed — Apache-2.0, MIT, or BSD-3-Clause:

- `google-api-python-client`, `google-auth`, `google-auth-oauthlib`,
  `google-auth-httplib2`, `importlib_metadata` (Apache-2.0) — the Gmail / Docs /
  Sheets / Slides workflows.
- `playwright` (Apache-2.0) — the `playwright` workflow.
- `python-pptx`, `beautifulsoup4`, `croniter`, `notebooklm-py`, `PyYAML`
  (MIT or BSD-3-Clause).
- `markdown` (BSD), `xhtml2pdf` (Apache-2.0) — the `notebooklm-workflow`
  workflow's Markdown-to-PDF conversion (`pdf_export.py`), written from
  scratch against these packages; see "Not included, deliberately" below for
  why it isn't derived from the Anthropic `pdf` skill.

Note that `notebooklm-py` is an **unofficial** client for Google NotebookLM; see the
Terms-of-Service notice in the README before using that workflow.

## Node.js dependencies

There is no `package.json` in this repository. Two workflows bootstrap Node packages
into `$HOME/.agents` on demand:

- **`tsx`** (MIT) — installed by `workflows/work-with-workflow/runtimes.md` and
  `workflows/kernel-browser/kernel-browser.md` to run TypeScript helpers.
- **`@onkernel/sdk`** — installed by `workflows/kernel-browser/kernel-browser.md`; it
  is the client for the third-party kernel.sh hosted-browser service, which requires
  your own account and API key. Check its own license and terms before use.

## Browser binaries

`workflows/playwright/` requires a Chromium build, which **you** fetch:

```bash
PLAYWRIGHT_BROWSERS_PATH=workflows/playwright/.browsers \
  python -m playwright install chromium
```

No browser binary is distributed here, deliberately. Playwright's browser downloads
may include Google-proprietary components — notably the Widevine CDM
(`libwidevinecdm.so`), which is licensed by Google, is **not** open source, and is
**not** redistributable — as well as an LGPL-2.1 FFmpeg build. Google Chrome for
Testing is likewise distributed under the Google Chrome Terms of Service, not the
BSD-3 Chromium license.

**Never commit `workflows/playwright/.browsers/` to this or any other repository.**
`.gitignore` blocks it.

## Not included, deliberately

Document-processing helpers for PDF, DOCX, XLSX, and PPTX derived from Anthropic Agent
Skills are omitted from this repository. Their license prohibits extraction,
reproduction, derivative works, and distribution:

> ADDITIONAL RESTRICTIONS: Notwithstanding anything in the Agreement to the contrary,
> users may not: Extract these materials from the Services or retain copies of these
> materials outside the Services; Reproduce or copy these materials […]; Create
> derivative works based on these materials; Distribute, sublicense, or transfer these
> materials to any third party […]
>
> — `LICENSE.txt`, © 2025 Anthropic, PBC

If you want that functionality, re-author it from scratch against `pypdf`,
`python-docx`, and `openpyxl` rather than adapting the Anthropic files.

`notebooklm-workflow/pdf_export.py` is exactly that kind of from-scratch build, scoped
narrowly to the one gap that workflow actually had (no `generate`/`download` type
produces PDF): plain Markdown → HTML → PDF via `markdown` + `xhtml2pdf`, written
independently against those packages' own public APIs, not adapted from or derived
from any Anthropic skill file. DOCX/XLSX/PPTX authoring helpers remain out of scope
here for the same reason stated above.
