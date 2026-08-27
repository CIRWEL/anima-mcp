#!/bin/bash
# journal-archive.sh — hourly incremental export of the systemd journal into
# ~/.anima/journal-archive/, where the Mac's daily slim mirror already carries
# everything under ~/.anima off-host (backup_lumen.sh excludes only backups/,
# schema_renders/ and *.db*).
#
# WHY: journald on this Pi is volatile (RAM-backed), and high-churn logging
# rotates it in under a day — one boot on 2026-08-27 held 24,937 wlan0 REGDOM
# lines and barely 22 hours of history. When the day-summary writer death of
# 2026-03-28 was finally investigated in August (#188), no operational record
# survived to distinguish three candidate mechanisms. This archive exists so
# the next quiet failure has a journal to read.
#
# Incremental via journalctl --cursor-file, run against a SCRATCH copy of the
# cursor that is promoted only after the append is durable: journalctl
# advances the cursor file as part of its own successful run, so using the
# real cursor directly would permanently skip a window whose append failed.
# After a reboot the volatile journal restarts; systemd >= 254 detects the
# unmatched cursor and reads from the new journal's head (deployed: 257), so
# at most the previous boot's tail since the last hourly run is lost. A
# backward clock jump can delay resumption until wall time passes the saved
# cursor's timestamp — bounded on this Pi by fake-hwclock keeping time
# roughly monotonic across boots.
#
# Failure direction (design invariant 2): every failure exits non-zero AND
# drops a .last_failure marker in the archive dir (cleared on the next full
# success). The systemd failed state is transient — the next successful timer
# run clears it — but the marker is durable and rides the mirror to the Mac.

set -u

ARCHIVE_DIR="${JOURNAL_ARCHIVE_DIR:-$HOME/.anima/journal-archive}"
CURSOR_FILE="${JOURNAL_ARCHIVE_CURSOR:-$ARCHIVE_DIR/.cursor}"
RETAIN_DAYS="${JOURNAL_ARCHIVE_RETAIN_DAYS:-7}"
MAX_DIR_MB="${JOURNAL_ARCHIVE_MAX_MB:-100}"
JOURNALCTL="${JOURNAL_ARCHIVE_JOURNALCTL:-journalctl}"

fail() {
    echo "journal-archive: $1" >&2
    printf '%s %s\n' "$(date -Is)" "$1" > "$ARCHIVE_DIR/.last_failure" 2>/dev/null
    exit 1
}

mkdir -p "$ARCHIVE_DIR" || { echo "journal-archive: cannot create $ARCHIVE_DIR" >&2; exit 1; }

day_file="$ARCHIVE_DIR/journal-$(date +%F).log.gz"
tmp="$(mktemp "${TMPDIR:-/tmp}/journal-archive.XXXXXX")" || fail "mktemp failed"
scratch_cursor="$tmp.cursor"
trap 'rm -f "$tmp" "$scratch_cursor"' EXIT

# Scratch-cursor dance: copy, export against the copy, promote only after the
# append lands. A failed promote after a successful append re-exports the
# window next run — duplication, never loss.
if [ -f "$CURSOR_FILE" ]; then
    cp "$CURSOR_FILE" "$scratch_cursor" || fail "cursor copy failed"
fi
if ! "$JOURNALCTL" --cursor-file="$scratch_cursor" -o short-iso --no-pager > "$tmp"; then
    fail "journalctl export failed"
fi

# One gzip member appended per run keeps the day file zcat-readable while
# never rewriting existing bytes. Quiet hours append nothing at all.
if [ -s "$tmp" ]; then
    if ! gzip -c "$tmp" >> "$day_file"; then
        fail "append to $day_file failed"
    fi
fi
if [ -f "$scratch_cursor" ]; then
    mv "$scratch_cursor" "$CURSOR_FILE" || fail "cursor promote failed"
fi

# Retention: RETAIN_DAYS of daily files (find's -mtime rounding makes the
# effective window roughly a day longer — errs toward keeping more), plus a
# hard size cap so a log storm cannot bloat the slim mirror this feeds.
# Oldest files go first; TODAY's file is never pruned — it may be the sole
# copy the daily mirror has not yet carried off-host — so a single storm day
# can exceed the cap by design, loudly.
find "$ARCHIVE_DIR" -maxdepth 1 -name 'journal-*.log.gz' -mtime +"$RETAIN_DAYS" -delete

max_kb=$((MAX_DIR_MB * 1024))
prev_kb=""
while :; do
    used_kb=$(du -sk "$ARCHIVE_DIR" 2>/dev/null | awk '{print $1}')
    [ -n "$used_kb" ] || fail "size cap check failed: du produced no output"
    [ "$used_kb" -le "$max_kb" ] && break
    [ "$used_kb" = "$prev_kb" ] && fail "size cap enforcement made no progress at ${used_kb}k"
    prev_kb=$used_kb
    oldest=$(find "$ARCHIVE_DIR" -maxdepth 1 -name 'journal-*.log.gz' ! -name "$(basename "$day_file")" | sort | head -n 1)
    if [ -z "$oldest" ]; then
        echo "journal-archive: today's file alone exceeds the ${MAX_DIR_MB}M cap — not pruning the sole un-mirrored copy" >&2
        break
    fi
    rm -f "$oldest"
    [ -e "$oldest" ] && fail "size cap enforcement stuck — could not delete $oldest"
    echo "journal-archive: size cap ${MAX_DIR_MB}M exceeded, pruned $(basename "$oldest")" >&2
done

rm -f "$ARCHIVE_DIR/.last_failure"
exit 0
