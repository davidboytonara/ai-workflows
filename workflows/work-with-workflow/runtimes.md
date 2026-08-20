# Runtime Conventions

Helper reference for `work-with-workflow.md`. All workflow dependencies install into the one shared location per language below (see the primary for the rules); use the system interpreter (`python3`, `npm`) only to create the shared environment when it is missing. Install dependencies into the shared location, preferably from a workflow-local `requirements.txt` / `package.json`.

## Python

Shared virtualenv at `$HOME/.agents/.venv`. Canonical bootstrap:

```bash
PY="$HOME/.agents/.venv/bin/python"
[ -x "$PY" ] || python3 -m venv "$HOME/.agents/.venv"
"$PY" --version
```

## TypeScript

Shared Node modules at `$HOME/.agents/node_modules`, driven by a single root `$HOME/.agents/package.json`, with `tsx` pinned as the runner. Canonical bootstrap + run:

```bash
TSX="$HOME/.agents/node_modules/.bin/tsx"
# Install into the shared store (creates the root package.json on first run):
[ -x "$TSX" ] || npm install --prefix "$HOME/.agents" tsx
"$TSX" --version
```

Always install with `npm install --prefix "$HOME/.agents" ...`.
