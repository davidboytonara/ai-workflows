#!/usr/bin/env bash
# LLM_harness.sh — one timed headless model call, routed to `claude -p`
# (authenticated Claude Code profile) or `pi` (ChatGPT / other providers).
#
# Usage:
#   LLM_harness.sh [-m|--model MODEL] [-t|--thinking EFFORT] [-s|--stopwatch SECONDS]
#                  [--grace SECONDS] [--max-context-tokens N] [--context-grace N]
#                  [--resume-session ID] [--state-file PATH] [--pi-stall-secs N]
#                  [--pi-session-id ID] [--pi-session-dir DIR]
#                  [-n|--dry-run] [--list-models] [--default-model] [--] PROMPT
#
# Routing (MODEL is an alias or a full id; `--list-models` prints the menu):
#   unqualified lowercase MODEL matching ^claude -> claude  (EFFORT -> --effort)
#   bare non-Claude MODEL                        -> pi --provider openai
#   provider/id MODEL                            -> pi --model provider/id
# Pi receives EFFORT unchanged via --thinking (off through max).
# Guarded routes — claude with --max-context-tokens > 0 (casper_guard.py) and pi
# unless --pi-stall-secs 0 (casper_pi_guard.py, driving `pi --mode rpc`) — inject a
# wind-down notice --grace seconds (or --context-grace tokens) before the budget,
# hard-stop with 124, and print the FINAL assistant text. The two unguarded routes
# keep stdout byte-for-byte the model's output — casper_verify.py parses it.
#
# Defaults: MODEL=auto — under a pi driver (PI_CODING_AGENT with PI_PROVIDER and
#           PI_MODEL set) the driver's own model as PROVIDER/ID (pi route, driver
#           credentials); anywhere else opus. Bare PI_MODEL is never used alone: an
#           unqualified claude-* id would route to the Claude CLI instead. An explicit
#           --model always wins; --model "" means auto; --default-model prints it.
#           EFFORT=auto (GPT 5.6 Sol=high, all others=medium)
#           STOPWATCH=7200  GRACE=300
#           MAX-CONTEXT-TOKENS=0 (token guard off)  CONTEXT-GRACE=40000
#           PI-STALL-SECS=900 (pi liveness guard; 0 disables)
#
# --resume-session/--state-file are claude guard-route extras (warm resume of a paused
# resolver session and its sidecar for the dispatcher); ignored on the other routes.
# --pi-session-id/--pi-session-dir are the pi-route session extras (ignored on claude):
# an existing `<dir>/*_<id>.jsonl` is RESUMED via `--session <file>` (works from any
# cwd; plain `pi --session-id` lookup is project(cwd)-scoped and would miss it), else
# the session is created there with that id. The dir must already exist.
# -n/--dry-run prints the exact command that would run and exits.
#
# Exit codes:
#   <child>  passed through from claude/pi
#   124      stopwatch elapsed or context-token budget reached (treat as "paused" —
#            handover lives in the plan doc)
#   2        usage error
set -euo pipefail

MODEL=""
EFFORT="medium"
THINKING_EXPLICIT=0
STOPWATCH="7200"
GRACE="300"
MAX_CTX="0"
CTX_GRACE="40000"
RESUME_SESSION=""
STATE_FILE=""
PI_STALL="900"
PI_SESSION_ID=""
PI_SESSION_DIR=""
PROMPT=""
DRYRUN=0

# Driver-aware default: casper dispatched by pi runs its resolvers on pi with the
# driving session's own model; anywhere else the historical Claude default stands.
# Requires BOTH PI_PROVIDER and PI_MODEL — composing PROVIDER/ID is what keeps a
# claude-* PI_MODEL on the pi route (a bare claude-* id would hit the Claude CLI).
# casper_fanout.py mirrors this rule (_default_model); a parity test pins them.
default_model() {
  if [ -n "${PI_CODING_AGENT:-}" ] && [ -n "${PI_PROVIDER:-}" ] && [ -n "${PI_MODEL:-}" ]; then
    printf '%s/%s\n' "$PI_PROVIDER" "$PI_MODEL"
  else
    echo "opus"
  fi
}

# Friendly alias -> full model id. Single source of truth for every entry point
# (casper.md MODEL, fanout --model, per-plan model fields in plans.json).
# Aliases are case-insensitive and take an optional version ("Fable 5", "sonnet-5");
# anything unrecognized passes through UNCHANGED as a full model id.
resolve_model() {
  local m
  m="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
  case "$m" in
    fable|fable-5|fable5)        echo "claude-fable-5" ;;
    opus|opus-5|opus5)           echo "claude-opus-5" ;;
    sonnet|sonnet-5|sonnet5)     echo "claude-sonnet-5" ;;
    haiku|haiku-4.5|haiku-4-5)   echo "claude-haiku-4-5-20251001" ;;
    gpt|gpt5|gpt-5)              echo "gpt-5" ;;
    *)                           echo "$1" ;;
  esac
}

# Guard routes: locate this script's dir and the venv python, and demote the outer
# stopwatch to a +60s failsafe — the guard owns the real stopwatch (and stays inside
# fanout's 7800s lease). Sets HERE/GUARD_PY/TIMEOUT for the caller.
use_guard() {
  HERE="$(cd "$(dirname "$0")" && pwd)"
  GUARD_PY="${CASPER_PY:-$HOME/.agents/.venv/bin/python}"
  [ -x "$GUARD_PY" ] || GUARD_PY="$(command -v python3)"
  TIMEOUT=(timeout --signal=TERM --kill-after=10 "$((STOPWATCH + 60))")
}

list_models() {
  cat <<'EOF'
ALIAS               MODEL ID                    BACKEND
fable  | Fable 5    claude-fable-5              claude
opus   | Opus 5     claude-opus-5               claude          (default)
sonnet | Sonnet 5   claude-sonnet-5             claude
haiku  | Haiku 4.5  claude-haiku-4-5-20251001   claude
gpt-5               gpt-5                       pi --provider openai  (needs OPENAI_API_KEY)
gpt-5.6-sol         gpt-5.6-sol                 pi --provider openai  (OPENAI_API_KEY)
-                   openai-codex/gpt-5.6-sol    pi  (Pi ChatGPT OAuth/subscription)
Aliases are case-insensitive; space or hyphen both work ("Fable 5", "sonnet-5").
Anything else passes through: unqualified lowercase claude* -> claude;
bare ids -> OpenAI via pi; provider/id values -> that provider via pi.
EOF
}

# Print the leading comment header (everything after the shebang up to the first code line).
usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    -m|--model)      MODEL="${2?--model needs a value}"; shift 2 ;;  # empty = auto
    -t|--thinking)   EFFORT="${2:?--thinking needs a value}"; THINKING_EXPLICIT=1; shift 2 ;;
    -s|--stopwatch)  STOPWATCH="${2:?--stopwatch needs a value}"; shift 2 ;;
    --grace)         GRACE="${2:?--grace needs a value}"; shift 2 ;;
    --max-context-tokens) MAX_CTX="${2:?--max-context-tokens needs a value}"; shift 2 ;;
    --context-grace) CTX_GRACE="${2:?--context-grace needs a value}"; shift 2 ;;
    --resume-session) RESUME_SESSION="${2:?--resume-session needs a value}"; shift 2 ;;
    --state-file)    STATE_FILE="${2:?--state-file needs a value}"; shift 2 ;;
    --pi-stall-secs) PI_STALL="${2:?--pi-stall-secs needs a value}"; shift 2 ;;
    --pi-session-id) PI_SESSION_ID="${2:?--pi-session-id needs a value}"; shift 2 ;;
    --pi-session-dir) PI_SESSION_DIR="${2:?--pi-session-dir needs a value}"; shift 2 ;;
    -n|--dry-run)    DRYRUN=1; shift ;;
    --list-models)   list_models; exit 0 ;;
    --default-model) default_model; exit 0 ;;
    -h|--help)       usage; exit 0 ;;
    --)              shift; PROMPT="$*"; break ;;
    -*)              echo "LLM_harness.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)               PROMPT="$*"; break ;;
  esac
done

if [ -z "${PROMPT//[[:space:]]/}" ]; then
  echo "LLM_harness.sh: empty PROMPT" >&2; usage >&2; exit 2
fi
case "$STOPWATCH" in ''|*[!0-9]*) echo "LLM_harness.sh: --stopwatch must be integer seconds" >&2; exit 2 ;; esac
case "$GRACE" in ''|*[!0-9]*) echo "LLM_harness.sh: --grace must be integer seconds" >&2; exit 2 ;; esac
case "$MAX_CTX" in ''|*[!0-9]*) echo "LLM_harness.sh: --max-context-tokens must be an integer" >&2; exit 2 ;; esac
case "$CTX_GRACE" in ''|*[!0-9]*) echo "LLM_harness.sh: --context-grace must be an integer" >&2; exit 2 ;; esac
case "$PI_STALL" in ''|*[!0-9]*) echo "LLM_harness.sh: --pi-stall-secs must be integer seconds" >&2; exit 2 ;; esac

[ -n "$MODEL" ] || MODEL="$(default_model)"
MODEL="$(resolve_model "$MODEL")"

# Choose a model-aware default only when the caller did not supply --thinking.
# Match the GPT model by basename so both bare and provider-qualified forms work.
if [ "$THINKING_EXPLICIT" = 0 ]; then
  case "${MODEL,,}" in
    gpt-5.6-sol|*/gpt-5.6-sol) EFFORT="high" ;;
    *)                         EFFORT="medium" ;;
  esac
fi

# Hard wall-clock: SIGTERM at STOPWATCH, SIGKILL 10s later if it ignores TERM.
TIMEOUT=(timeout --signal=TERM --kill-after=10 "${STOPWATCH}")

if [[ "$MODEL" != */* && "$MODEL" =~ ^claude ]]; then
  if [ "$MAX_CTX" -gt 0 ]; then
    # Token-guard route: casper_guard.py owns the claude call, the real stopwatch,
    # the wind-down injection, and the token hard stop (exit 124).
    use_guard
    CMD=("$GUARD_PY" "$HERE/casper_guard.py"
      --model "$MODEL" --effort "$EFFORT"
      --stopwatch "$STOPWATCH" --grace "$GRACE"
      --max-context-tokens "$MAX_CTX" --context-grace "$CTX_GRACE")
    if [ -n "$RESUME_SESSION" ]; then CMD+=(--resume-session "$RESUME_SESSION"); fi
    if [ -n "$STATE_FILE" ]; then CMD+=(--state-file "$STATE_FILE"); fi
    CMD+=(-- "$PROMPT")
  else
    # Legacy route (default): plain claude -p. Callers that parse this stdout as
    # JSON (casper_verify.py judgments) rely on it staying byte-for-byte the
    # model's output — do not move them onto the guard route.
    # Wait indefinitely for backgrounded sub-work instead of the CLI's own ~600s
    # internal ceiling: the outer TIMEOUT stopwatch above already bounds total
    # wall-clock, so an inner ceiling only risks a benign exit-0 before the
    # resolver actually finishes (and before it runs its own `--set done`).
    CMD=(env CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0
      claude -p --dangerously-skip-permissions
      --model "$MODEL" --effort "$EFFORT" -- "$PROMPT")
  fi
else
  # Pi accepts off|minimal|low|medium|high|xhigh|max. A provider-qualified
  # model is self-routing; bare non-Claude IDs are explicitly OpenAI.
  PROVIDER_ARGS=()
  case "$MODEL" in */*) : ;; *) PROVIDER_ARGS=(--provider openai) ;; esac
  # Session continuity (fanout warm resume): resume the matching session file when
  # one exists — `--session <file>` works from any cwd — else create it with the
  # exact id. Timestamped names sort oldest-first; the loop keeps the newest.
  SESS_ARGS=()
  if [ -n "$PI_SESSION_ID" ]; then
    RESUME_FILE=""
    if [ -n "$PI_SESSION_DIR" ]; then
      for f in "$PI_SESSION_DIR"/*_"$PI_SESSION_ID".jsonl; do
        [ -e "$f" ] && RESUME_FILE="$f"
      done
    fi
    if [ -n "$RESUME_FILE" ]; then
      SESS_ARGS=(--session "$RESUME_FILE")
    elif [ -n "$PI_SESSION_DIR" ]; then
      SESS_ARGS=(--session-dir "$PI_SESSION_DIR" --session-id "$PI_SESSION_ID")
    else
      SESS_ARGS=(--session-id "$PI_SESSION_ID")
    fi
  fi
  if [ "$PI_STALL" -gt 0 ]; then
    # RPC-supervisor route (default): casper_pi_guard.py drives `pi --mode rpc`
    # over the JSONL protocol — the prompt goes in as an rpc command, the event
    # stream is liveness (with /proc + session-file checks as fallback for quiet
    # tool calls), a wind-down notice is steered $GRACE seconds before the
    # stopwatch, the hard stop is a clean `abort` (then kill, exit 124 = pause),
    # extension dialogs are auto-cancelled to match headless `pi -p`, and stdout
    # is the FINAL assistant text (casper_verify.py parses it).
    use_guard
    CMD=("$GUARD_PY" "$HERE/casper_pi_guard.py"
      --stall-secs "$PI_STALL" --stopwatch "$STOPWATCH"
      --wind-down-secs "$GRACE" --rpc-prompt "$PROMPT")
    if [ -n "$PI_SESSION_DIR" ]; then CMD+=(--watch-dir "$PI_SESSION_DIR"); fi
    CMD+=(-- pi --mode rpc "${PROVIDER_ARGS[@]}" --model "$MODEL" --thinking "$EFFORT" "${SESS_ARGS[@]}")
  else
    # Escape hatch (--pi-stall-secs 0): bare `pi -p`, stdout byte-for-byte the
    # model's output. pi has no `--` end-of-options separator (rejects it as
    # "Unknown option: --"); the prompt is a plain positional message.
    CMD=(pi -p "${PROVIDER_ARGS[@]}" --model "$MODEL" --thinking "$EFFORT" "${SESS_ARGS[@]}" "$PROMPT")
  fi
fi

if [ "$DRYRUN" = 1 ]; then
  printf '%q ' "${TIMEOUT[@]}" "${CMD[@]}"; echo
  exit 0
fi
exec "${TIMEOUT[@]}" "${CMD[@]}"
