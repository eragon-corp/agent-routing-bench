#!/usr/bin/env bash
# run-workflow.sh — Execute a single run for a given workflow + method
#
# Usage: bash run-workflow.sh <workflow_name> <method> <run_id>
#
# Arguments:
#   $1  workflow_name  — e.g. "deep-research" or "gmail-triage"
#   $2  method         — one of: claude-code | eragon-norouting | eragon-routing
#   $3  run_id         — e.g. "run-001-claude-code"
#
# Outputs (written to workflows/<name>/runs/<run_id>/):
#   output.txt   — full stdout of the hermes invocation
#   timing.json  — wall-clock timing metadata
#
# Exit codes:
#   0 = success
#   1 = missing arguments or unknown method
#   2 = hermes invocation failed (non-zero exit from hermes chat)

set -euo pipefail

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
WORKFLOW="${1:-}"
METHOD="${2:-}"
RUN_ID="${3:-}"

if [[ -z "$WORKFLOW" || -z "$METHOD" || -z "$RUN_ID" ]]; then
    echo "ERROR: Missing required arguments." >&2
    echo "Usage: bash run-workflow.sh <workflow_name> <method> <run_id>" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Paths (relative to repo root, which is the parent of harness/)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

SKILL_FILE="${REPO_ROOT}/workflows/${WORKFLOW}/skill.md"
RUN_DIR="${REPO_ROOT}/workflows/${WORKFLOW}/runs/${RUN_ID}"
OUTPUT_FILE="${RUN_DIR}/output.txt"
TIMING_FILE="${RUN_DIR}/timing.json"

# Validate skill file exists
if [[ ! -f "$SKILL_FILE" ]]; then
    echo "ERROR: skill.md not found at ${SKILL_FILE}" >&2
    exit 1
fi

# Ensure run directory exists
mkdir -p "$RUN_DIR"

# ---------------------------------------------------------------------------
# Method → hermes invocation
# ---------------------------------------------------------------------------
# Timing
START_EPOCH=$(date +%s%N)   # nanoseconds
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

HERMES_EXIT=0

case "$METHOD" in

  claude-code)
    # Claude Code CLI: runs the skill as a prompt via `claude -p`, no routing table.
    # Strips YAML frontmatter before passing to claude. Ensures npm-global in PATH.
    export PATH="$HOME/.npm-global/bin:$PATH"
    SKILL_CONTENT=$(awk '/^---/{f=!f; next} !f' "${SKILL_FILE}")
    claude -p "${SKILL_CONTENT}" \
        > "${OUTPUT_FILE}" 2>&1 \
      || HERMES_EXIT=$?
    ;;

  eragon-norouting)
    # Eragon all-Opus run: sends skill to Eragon chat UI via CDP with model override.
    # Forces all steps to Opus by passing /model anthropic/claude-opus-4.8 before the skill.
    python3 "${SCRIPT_DIR}/run-eragon.py" \
        --skill "${SKILL_FILE}" \
        --output "${OUTPUT_FILE}" \
        --model "anthropic/claude-opus-4.8" \
      || HERMES_EXIT=$?
    ;;

  eragon-routing)
    # Eragon with routing: sends skill to Eragon chat UI via CDP.
    # The skill's routing table drives per-step model selection via sessions_spawn.
    python3 "${SCRIPT_DIR}/run-eragon.py" \
        --skill "${SKILL_FILE}" \
        --output "${OUTPUT_FILE}" \
      || HERMES_EXIT=$?
    ;;

  *)
    echo "ERROR: Unknown method '${METHOD}'. Valid: claude-code, eragon-norouting, eragon-routing" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
END_EPOCH=$(date +%s%N)
END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Wall-clock seconds (float)
WALLCLOCK_NS=$(( END_EPOCH - START_EPOCH ))
WALLCLOCK_S=$(echo "scale=3; ${WALLCLOCK_NS} / 1000000000" | bc)

# Determine status string
if [[ "$HERMES_EXIT" -eq 0 ]]; then
    STATUS="completed"
else
    STATUS="failed"
fi

# Write timing.json
cat > "${TIMING_FILE}" <<EOF
{
  "run_id":        "${RUN_ID}",
  "workflow":      "${WORKFLOW}",
  "method":        "${METHOD}",
  "status":        "${STATUS}",
  "exit_code":     ${HERMES_EXIT},
  "start_iso":     "${START_ISO}",
  "end_iso":       "${END_ISO}",
  "wallclock_s":   ${WALLCLOCK_S}
}
EOF

# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------
if [[ "$HERMES_EXIT" -ne 0 ]]; then
    echo "ERROR: hermes exited with code ${HERMES_EXIT} for run ${RUN_ID}" >&2
    exit 2
fi

echo "OK: ${RUN_ID} completed in ${WALLCLOCK_S}s"
exit 0
