#!/usr/bin/env bash
# triage-email.sh — Scan emails, archive noise, create inbox.org entries
#
# Scheduled at 05:30 UTC (30 min before /today briefing at 06:00 UTC).
# Pipeline: 05:30 email triage → 06:00 today briefing
#
# Writes:
#   - Per-account scan cache: $STATE_DIR/scan_cache_<account>.json
#     (read by /today email-hook for the briefing's Email section)
#   - Audit log line (JSONL): $STATE_DIR/audit.jsonl
#     (queryable history of every triage run)

set -euo pipefail

DATA_DIR="${DATA_DIR:-$HOME/Data}"
MODULE_DIR="$DATA_DIR/.datacore/modules/mail"
STATE_DIR="$DATA_DIR/.datacore/state/mail"
AUDIT_LOG="$STATE_DIR/audit.jsonl"
LOG_PREFIX="[email-triage]"

# The host's own settings (MAIL_TRIAGE_ACCOUNTS among them): fleet .env, then local.env.
for _env in "${DATACORE_ROOT:-$HOME/Data}/.datacore/env/.env" "${DATACORE_ROOT:-$HOME/Data}/.datacore/env/local.env"; do
    # shellcheck disable=SC1090
    [ -r "$_env" ] && { set -a; . "$_env"; set +a; }
done

mkdir -p "$STATE_DIR"

RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')"
START_TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

echo "$LOG_PREFIX Starting at $START_TS (run_id=$RUN_ID)"

# ── Model SELECTION per the enforced per-task router (task: mail-processing) ──
# Resolve the routed provider/model and export it onto the local model knob so
# email_scanner._ollama_classify uses the routed model (not a hardcoded one).
# mail-processing routed LOCAL until 2026-08-17, when it was deliberately
# pointed at a hosted model. Sender, subject and snippet now leave the box for
# whatever provider the router names — never the full body. Set
# mail-processing back to provider: ollama in model_routing.yaml to reverse it.
# Fail-soft: if the shim is absent, the classifier keeps its own default.
COS_LIB="$DATA_DIR/.datacore/lib"
if [ -f "$COS_LIB/cos_llm.sh" ]; then
    # shellcheck disable=SC1090,SC1091
    source "$COS_LIB/cos_llm.sh"
    cos_route_apply mail-processing || true

    # A cloud route needs its key, and nothing in this path had ever loaded one:
    # OPENROUTER_API_KEY lives in /etc/datacored.env, which neither this script
    # nor cos_llm.sh sources — so a cloud-routed run would have fallen straight
    # back to local with no indication why. Lift out the single variable rather
    # than sourcing that file wholesale; it holds the fleet's other credentials
    # and this process has no business inheriting them.
    if [ "${COS_ROUTE_PROVIDER:-}" = "openrouter" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
        if [ -r /etc/datacored.env ]; then
            OPENROUTER_API_KEY=$(sed -n 's/^OPENROUTER_API_KEY=//p' /etc/datacored.env | head -1)
            export OPENROUTER_API_KEY
        fi
        [ -z "${OPENROUTER_API_KEY:-}" ] && \
            echo "$LOG_PREFIX WARNING: route is openrouter but no OPENROUTER_API_KEY — classifier will fall back to local" >&2
    fi

    if [ "${COS_ROUTE_DRYRUN:-0}" = "1" ]; then
        echo "$LOG_PREFIX dry-run: mail-processing -> provider=${COS_ROUTE_PROVIDER} model=${OLLAMA_MODEL:-<OLLAMA_MODEL-default>} sovereignty=${COS_ROUTE_SOVEREIGNTY}"
        exit 0
    fi
fi

# --- Scan each configured account ---
TOTAL_SCANNED=0
TOTAL_ARCHIVED=0
TOTAL_PROCESSED=0
TOTAL_ERRORS=0
ACCOUNT_RESULTS=()

# The accounts are the installation's own: MAIL_TRIAGE_ACCOUNTS, space-separated, from
# the host's environment (never this public file). Publishing replaced the real ones
# here with placeholders, and the box then "scanned" two fake inboxes and reported them
# clean for two nights (2026-09-24/25). No setting is a loud failure, never a clean run.
if [ -z "${MAIL_TRIAGE_ACCOUNTS:-}" ]; then
    echo "$LOG_PREFIX ERROR: MAIL_TRIAGE_ACCOUNTS is not set -- no inbox was scanned" >&2
    exit 2
fi
# shellcheck disable=SC2086  # word-splitting the list is the point
for ACCOUNT in $MAIL_TRIAGE_ACCOUNTS; do
    SAFE_NAME="$(echo "$ACCOUNT" | tr '@' '_' | tr '.' '_')"
    CACHE_FILE="$STATE_DIR/scan_cache_${SAFE_NAME}.json"
    SCAN_LOG="$STATE_DIR/scan_${SAFE_NAME}_${RUN_ID}.log"

    # --cache is write-only after 2026-06-03 scanner refactor. Live scan always runs;
    # results overwrite $CACHE_FILE. (Previously --cache double-purposed as read+write,
    # which caused silent cache-poisoning when the daemon re-ran.)

    echo "$LOG_PREFIX Scanning $ACCOUNT..."

    if python3 "$MODULE_DIR/lib/email_scanner.py" \
        --account "$ACCOUNT" \
        --execute \
        --days 3 \
        --cache "$CACHE_FILE" \
        --format summary > "$SCAN_LOG" 2>&1; then

        # Extract stats from scanner output for audit log
        ARCHIVED=$(grep -oE 'Archived: [0-9]+' "$SCAN_LOG" | grep -oE '[0-9]+' || echo 0)
        PROCESSED=$(grep -oE 'Processed: [0-9]+' "$SCAN_LOG" | grep -oE '[0-9]+' || echo 0)
        ERRORS=$(grep -oE 'Errors: [0-9]+' "$SCAN_LOG" | grep -oE '[0-9]+' || echo 0)
        SCANNED=$(grep -oE 'Found [0-9]+ inbox emails' "$SCAN_LOG" | grep -oE '[0-9]+' || echo 0)

        TOTAL_SCANNED=$((TOTAL_SCANNED + SCANNED))
        TOTAL_ARCHIVED=$((TOTAL_ARCHIVED + ARCHIVED))
        TOTAL_PROCESSED=$((TOTAL_PROCESSED + PROCESSED))
        TOTAL_ERRORS=$((TOTAL_ERRORS + ERRORS))

        ACCOUNT_RESULTS+=("\"$ACCOUNT\": {\"scanned\": $SCANNED, \"archived\": $ARCHIVED, \"processed\": $PROCESSED, \"errors\": $ERRORS}")
        echo "$LOG_PREFIX   $ACCOUNT: scanned=$SCANNED archived=$ARCHIVED processed=$PROCESSED errors=$ERRORS"

        # Echo the summary to journal so journalctl still has a human-readable log
        cat "$SCAN_LOG"
    else
        echo "$LOG_PREFIX WARNING: Failed to scan $ACCOUNT (see $SCAN_LOG)"
        cat "$SCAN_LOG" || true
        TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
        ACCOUNT_RESULTS+=("\"$ACCOUNT\": {\"error\": \"scan_failed\"}")
    fi
done

END_TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# --- Append audit log line (JSONL — one JSON object per line) ---
ACCOUNTS_JSON=$(IFS=,; echo "${ACCOUNT_RESULTS[*]}")
AUDIT_LINE="{\"run_id\": \"$RUN_ID\", \"started_at\": \"$START_TS\", \"completed_at\": \"$END_TS\", \"total_scanned\": $TOTAL_SCANNED, \"total_archived\": $TOTAL_ARCHIVED, \"total_processed\": $TOTAL_PROCESSED, \"total_errors\": $TOTAL_ERRORS, \"accounts\": {$ACCOUNTS_JSON}}"
echo "$AUDIT_LINE" >> "$AUDIT_LOG"

echo "$LOG_PREFIX Completed at $END_TS — totals: scanned=$TOTAL_SCANNED archived=$TOTAL_ARCHIVED processed=$TOTAL_PROCESSED errors=$TOTAL_ERRORS"
echo "$LOG_PREFIX Audit log: $AUDIT_LOG"
