#!/usr/bin/env bash
# run-workflow.sh — Execute a single benchmark run for a given workflow + method
#
# Usage: bash run-workflow.sh <workflow_name> <method> <run_id>
#
# Arguments:
#   $1  workflow_name  — e.g. "deep-research" or "gmail-triage"
#   $2  method         — one of: cowork | eragon-norouting | eragon-routing
#   $3  run_id         — e.g. "run-001-cowork"
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

  cowork)
    # Claude Cowork: openrouter/anthropic/claude-sonnet-4.6 via openrouter, NO routing table.
    # The skill is passed as the system/task prompt; -Q suppresses the interactive shell.
    hermes chat \
        -q "$(cat "${SKILL_FILE}")" \
        -m "openrouter/anthropic/claude-sonnet-4.6" \
        --provider openrouter \
        -Q \
        > "${OUTPUT_FILE}" 2>&1 \
      || HERMES_EXIT=$?
    ;;

  eragon-norouting)
    # Eragon all-Opus baseline: anthropic/claude-opus-4-6 via anthropic provider.
    # Forces all steps to Opus, ignoring any routing table in the skill.
    hermes chat \
        -q "$(cat "${SKILL_FILE}")" \
        -m "anthropic/claude-opus-4-6" \
        --provider anthropic \
        -Q \
        > "${OUTPUT_FILE}" 2>&1 \
      || HERMES_EXIT=$?
    ;;

  eragon-routing)
    # Eragon with routing: uses default provider, letting the skill's routing table
    # drive per-step model selection via sessions_spawn.
    hermes chat \
        -q "$(cat "${SKILL_FILE}")" \
        -Q \
        > "${OUTPUT_FILE}" 2>&1 \
      || HERMES_EXIT=$?
    ;;

  *)
    echo "ERROR: Unknown method '${METHOD}'. Valid: cowork, eragon-norouting, eragon-routing" >&2
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
