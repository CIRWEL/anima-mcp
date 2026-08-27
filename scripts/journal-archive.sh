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
# Incremental via journalctl --cursor-file: each run exports only entries
# newer than the saved cursor. After a reboot the volatile journal restarts
# and the stale cursor falls back to the journal head, so the new boot is
# captured from its beginning; at most the previous boot's tail since the
# last hourly run is lost — the price of not writing the journal to the SD
# card continuously.
#
# Failure direction (design invariant 2): any export failure exits non-zero,
# leaving the systemd unit in a failed state — visible, never silently
# skipped.

set -u

ARCHIVE_DIR="${JOURNAL_ARCHIVE_DIR:-$HOME/.anima/journal-archive}"
CURSOR_FILE="${JOURNAL_ARCHIVE_CURSOR:-$ARCHIVE_DIR/.cursor}"
RETAIN_DAYS="${JOURNAL_ARCHIVE_RETAIN_DAYS:-14}"
MAX_DIR_MB="${JOURNAL_ARCHIVE_MAX_MB:-300}"
JOURNALCTL="${JOURNAL_ARCHIVE_JOURNALCTL:-journalctl}"

mkdir -p "$ARCHIVE_DIR" || { echo "journal-archive: cannot create $ARCHIVE_DIR" >&2; exit 1; }

day_file="$ARCHIVE_DIR/journal-$(date +%F).log.gz"
tmp="$(mktemp "${TMPDIR:-/tmp}/journal-archive.XXXXXX")" || exit 1
trap 'rm -f "$tmp"' EXIT

# journalctl updates the cursor file itself only on a successful read, so a
# failed export retries the same window next run instead of losing it.
if ! "$JOURNALCTL" --cursor-file="$CURSOR_FILE" -o short-iso --no-pager > "$tmp"; then
    echo "journal-archive: journalctl export failed" >&2
    exit 1
fi

# One gzip member appended per run keeps the day file zcat-readable while
# never rewriting existing bytes. Quiet hours append nothing at all.
if [ -s "$tmp" ]; then
    if ! gzip -c "$tmp" >> "$day_file"; then
        echo "journal-archive: append to $day_file failed" >&2
        exit 1
    fi
fi

# Retention: RETAIN_DAYS of daily files, plus a hard size cap so a log storm
# cannot bloat the slim mirror this feeds. Oldest files go first; if a single
# storm day alone exceeds the cap, it too is dropped — self-protection beats
# completeness here, and the prune is announced.
find "$ARCHIVE_DIR" -maxdepth 1 -name 'journal-*.log.gz' -mtime +"$RETAIN_DAYS" -delete

max_kb=$((MAX_DIR_MB * 1024))
while :; do
    used_kb=$(du -sk "$ARCHIVE_DIR" | awk '{print $1}')
    [ "$used_kb" -le "$max_kb" ] && break
    oldest=$(find "$ARCHIVE_DIR" -maxdepth 1 -name 'journal-*.log.gz' | sort | head -n 1)
    [ -z "$oldest" ] && break
    rm -f "$oldest"
    echo "journal-archive: size cap ${MAX_DIR_MB}M exceeded, pruned $(basename "$oldest")" >&2
done

exit 0
