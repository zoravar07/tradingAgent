#!/bin/bash
# Z Money daily run for launchd (~/Library/LaunchAgents/com.zmoney.nightly.plist).
#
# Trigger model: launchd starts this at login (RunAtLoad) and every 30 minutes
# (StartInterval); a tick missed while the Mac was asleep fires at the next
# wake. This script turns those ticks into "at most one run per weekday":
#   - weekends: skip.
#   - data/.nightly.done holds the local date of the last completed or
#     guard-skipped run; if it is today, skip.
#   - a failed run (sync/data/crash) may retry on later ticks, up to
#     MAX_ATTEMPTS per day, tracked in data/.nightly.attempts.
# Everything else is unchanged: venv Python by absolute path, per-run log in
# logs/, an atomic lock so two ticks can't overlap, exit 2 from the script
# means the pre-flight guard declined (logged, reported as success).
set -u
PROJECT="/Users/zoravarsingh/zmoney"
PYTHON="$PROJECT/.venv/bin/python"
SCRIPT="$PROJECT/scripts/run_live_briefing.py"
LOG_DIR="$PROJECT/logs"
LOCK_DIR="$PROJECT/data/.nightly.lock"
DONE_FILE="$PROJECT/data/.nightly.done"
ATTEMPTS_FILE="$PROJECT/data/.nightly.attempts"
MAX_ATTEMPTS=3
TODAY="$(date +%Y-%m-%d)"          # local date: "once per weekday" means the user's day
DOW="$(date +%u)"                  # 1=Mon .. 7=Sun
mkdir -p "$LOG_DIR"

# ---- cheap gates first, without creating a log file per 30-minute tick
if [ "$DOW" -ge 6 ]; then exit 0; fi
if [ "$(cat "$DONE_FILE" 2>/dev/null)" = "$TODAY" ]; then exit 0; fi
ATTEMPTS="$(grep "^$TODAY " "$ATTEMPTS_FILE" 2>/dev/null | awk '{print $2}')"
ATTEMPTS="${ATTEMPTS:-0}"
if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then exit 0; fi

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/nightly-$STAMP.log"
exec >>"$LOG" 2>&1
ln -sfn "$LOG" "$LOG_DIR/latest.log"
echo "=== run start $(date -u +%FT%TZ) (local $(date '+%F %T %Z'), attempt $((ATTEMPTS + 1))/$MAX_ATTEMPTS today) ==="

# ---- single-flight lock (mkdir is atomic); PID inside for staleness checks
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  OLD_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo '')"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "SKIPPED: a run is already in progress (pid $OLD_PID, lock $LOCK_DIR)"
    exit 0
  fi
  echo "stale lock from pid '${OLD_PID:-?}' with no live process — clearing"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "FAILED: could not take lock"; exit 1; }
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

echo "$TODAY $((ATTEMPTS + 1))" > "$ATTEMPTS_FILE"
cd "$PROJECT" || { echo "FAILED: cannot cd to project"; exit 1; }
"$PYTHON" -u "$SCRIPT"
RC=$?
case $RC in
  0) echo "$TODAY" > "$DONE_FILE"; echo "=== done: run completed ($(date -u +%FT%TZ)) ===" ;;
  2) echo "$TODAY" > "$DONE_FILE"; echo "=== done: skipped by pre-flight guard, nothing spent; no retry today ($(date -u +%FT%TZ)) ==="; RC=0 ;;
  *) echo "=== FAILED with exit $RC ($(date -u +%FT%TZ)); will retry on a later tick if attempts remain ===" ;;
esac
exit $RC
