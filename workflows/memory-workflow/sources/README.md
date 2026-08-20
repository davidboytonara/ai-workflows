# Session source mirrors

Optional staging area for provider session exports.

`extract_session_history.py` default paths scan both these mirrors and live provider dirs:

- `sources/pi/` and `~/.pi/agent/sessions/` — pi session `.jsonl` files
- `sources/claude/` and `~/.claude/projects/` — Claude session `.jsonl` files
- `sources/antigravity/`, `~/.gemini/antigravity/conversations/`, and `~/.gemini/antigravity/implicit/` — AntiGravity session `.pb` files

You can also bypass defaults by passing explicit file or directory paths to `extract_session_history.py`.
