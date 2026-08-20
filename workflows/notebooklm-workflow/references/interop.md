# NotebookLM Interop Cookbook

Use this reference to connect NotebookLM outputs to whatever downstream skills or
workflows your own setup provides. The handoff targets named below (`docx`, `pptx`,
`xlsx`, `youtube-search`, and similar) are **not** shipped in this repository — they
are examples of the kind of tool you would hand each artifact to. Substitute your own.

## Common handoff artifacts

- Report: Markdown (`download report`)
- Slide deck: PDF or PPTX (`download slide-deck`)
- Quiz/flashcards: JSON or Markdown (`download quiz`, `download flashcards`)
- Data table: CSV (`download data-table`)
- Mind map: JSON (`download mind-map`)
- Audio/video: MP4 (`download audio`, `download video`)

## Skill-by-skill handoffs

### docx

- Convert NotebookLM report markdown into polished `.docx` deliverables.
- Apply tracked-change review workflows for stakeholder edits.

### excalidraw

- Transform NotebookLM mind map JSON into architecture or concept diagrams.
- Visualize source clusters, argument maps, or workflow decomposition.

### gmail

- Draft update emails that include NotebookLM report summaries.
- Attach downloaded NotebookLM artifacts (`.md`, `.pdf`, `.pptx`, `.csv`) in drafts.

### google-sheets

- Import NotebookLM `data-table` CSV into a spreadsheet.
- Add formulas, validation, conditional formatting, and charts for analysis.

### google-slides

- Import NotebookLM highlights to a collaborative slide deck.
- Refine structure and speaker notes; apply brand themes.

### mcp-builder

- Build MCP tools that wrap recurring NotebookLM CLI workflows.
- Expose controlled operations like source ingest, ask, and report generation.

### pdf

- Convert and package NotebookLM outputs into PDF briefing bundles.
- Merge NotebookLM slide PDFs with appendix documents.

### clickup

- Convert NotebookLM findings into actionable ClickUp tasks.
- Attach exported artifacts to tasks for traceable context.

### pptx

- Start from NotebookLM slide deck download (`--format pptx`).
- Apply structural edits, custom layouts, and speaker-note updates.

### skill-creator

- Create derived skills for team-specific NotebookLM workflows.
- Package reusable command recipes and guardrails.

### <your>-internal-comms

- Reframe NotebookLM report content into internal leadership updates.
- Generate standard formats for incident, status, or project communications.

### <your>-brand-guidelines

- Apply your own branding to NotebookLM-based decks and documents.
- Standardize colors, typography, and visual consistency.

### todoist

- Extract action items from NotebookLM chat answers.
- Create tasks with due dates, priorities, and labels.

### xlsx

- Perform advanced spreadsheet analysis on NotebookLM CSV exports.
- Build pivot-ready workbooks with formulas and charts.

### youtube-search

- Discover candidate videos first, then ingest selected URLs into NotebookLM.
- Use metadata ranking to prioritize high-signal sources.

## Recommended cross-skill flow for research projects

1. Use `youtube-search` to shortlist videos and URLs.
2. Use NotebookLM to ingest, ask questions, and generate reports/slides/quizzes.
3. Use `xlsx` or `google-sheets` for quantitative tables.
4. Use `pptx` or `google-slides` for presentation refinement.
5. Use `gmail` and `clickup` for communication and execution.
