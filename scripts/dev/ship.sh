#!/usr/bin/env bash
# ship.sh — agent-friendly commit-and-deliver (fleet-portable core)
#
# Default delivery is a draft PR for everything — Codex and Claude share one
# contract so concurrent sessions stay predictable and the operator is the
# merge gate. In `auto` mode:
#   - Runtime code and detached-HEAD work → fresh agent-prefixed branch +
#     draft PR.
#   - Everything else on a named feature branch → draft PR on that branch.
#
# Draft PRs make work visible without pretending it is ready to merge. Use
# --direct to opt out (docs/tests only), or --auto-merge when the operator
# explicitly wants auto-merge-on-green.
#
# This is the portable core of unitares' scripts/dev/ship.sh (same flags,
# same routing) without the unitares-only machinery (lease advisory, Watcher
# trailer, skills-sync gate). Keep flag behavior in sync with unitares —
# 2026-08-01: the pre-sync script here swallowed `--draft-pr` as the commit
# message and opened a ready PR with an auto-merge attempt.
#
# Usage:
#   ./scripts/dev/ship.sh "commit message"
#   ./scripts/dev/ship.sh --stage-all "commit message"
#   ./scripts/dev/ship.sh --draft-pr "commit message"
#   ./scripts/dev/ship.sh --open-pr "commit message"
#   ./scripts/dev/ship.sh --auto-merge "commit message"
#   ./scripts/dev/ship.sh --direct "commit message"
#   ./scripts/dev/ship.sh --classify          # just print "runtime" or "other"
#   ./scripts/dev/ship.sh --plan "commit message"
#
# Requirements: staged changes (git add already done) unless --stage-all is
# used, gh CLI authed.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

RUNTIME_PATTERNS=(
    '^src/anima_mcp/'
    '^pyproject\.toml$'
)

classify_paths() {
    local files="$1"
    if [[ -z "$files" ]]; then
        echo "empty"; return
    fi
    while IFS= read -r f; do
        for pat in "${RUNTIME_PATTERNS[@]}"; do
            if [[ "$f" =~ $pat ]]; then
                echo "runtime"; return
            fi
        done
    done <<< "$files"
    echo "other"
}

classify() {
    local files; files=$(git diff --cached --name-only)
    classify_paths "$files"
}

worktree_changed_files() {
    {
        git diff --name-only
        git diff --cached --name-only
        git ls-files --others --exclude-standard
    } | sort -u
}

classify_worktree() {
    local files; files=$(worktree_changed_files)
    classify_paths "$files"
}

usage() {
    cat >&2 <<'USAGE'
usage: ship.sh [--stage-all] [--draft-pr|--open-pr|--auto-merge|--direct] "commit message"
       ship.sh --classify
       ship.sh [--stage-all] --plan "commit message"

Modes:
  auto         draft PR for everything (the default convention); runtime/detached
               work mints a fresh agent-prefixed branch, other work uses the
               current branch. --direct opts out for docs/tests-only pushes.
  --draft-pr  commit, push current/new branch, and open a draft PR
  --open-pr   commit, push current/new branch, and open a ready PR
  --auto-merge
               commit, push current/new branch, open a ready PR, and enable auto-merge
  --direct    commit and push the current branch; refuses detached HEAD
  --stage-all stage the full current worktree before classifying/committing.
               With --plan, previews that route without mutating the index.
USAGE
}

MODE="${UNITARES_SHIP_MODE:-auto}"
PLAN_ONLY=0
STAGE_ALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --classify)
            classify
            exit 0
            ;;
        --plan|--dry-run)
            PLAN_ONLY=1
            shift
            ;;
        --stage-all|--all)
            STAGE_ALL=1
            shift
            ;;
        --draft-pr|--draft)
            MODE="draft_pr"
            shift
            ;;
        --open-pr|--pr)
            MODE="open_pr"
            shift
            ;;
        --auto-merge)
            MODE="auto_merge"
            shift
            ;;
        --direct)
            MODE="direct"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --*)
            echo "unknown option: $1" >&2
            usage
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

MESSAGE="${*:-}"
if [[ -z "$MESSAGE" ]]; then
    usage
    exit 2
fi

if [[ "$STAGE_ALL" == "1" && "$PLAN_ONLY" != "1" ]]; then
    echo "[ship] staging all worktree changes"
    git add -A
fi

if [[ "$STAGE_ALL" == "1" && "$PLAN_ONLY" == "1" ]]; then
    KIND=$(classify_worktree)
else
    KIND=$(classify)
fi
BRANCH=$(git branch --show-current)
HEAD_SHORT=$(git rev-parse --short HEAD)
DETACHED=0
if [[ -z "$BRANCH" ]]; then
    DETACHED=1
fi

normalize_mode() {
    case "$1" in
        auto|draft_pr|open_pr|auto_merge|direct)
            echo "$1" ;;
        draft-pr|draft)
            echo "draft_pr" ;;
        open-pr|pr)
            echo "open_pr" ;;
        auto-merge)
            echo "auto_merge" ;;
        *)
            echo "invalid" ;;
    esac
}

MODE=$(normalize_mode "$MODE")
if [[ "$MODE" == "invalid" ]]; then
    echo "invalid UNITARES_SHIP_MODE; expected auto, draft-pr, open-pr, auto-merge, or direct" >&2
    exit 2
fi

DELIVERY="$MODE"
FORCE_AUTO_BRANCH=0
if [[ "$MODE" == "auto" ]]; then
    DELIVERY="draft_pr"
    if [[ "$KIND" == "runtime" || "$DETACHED" == "1" ]]; then
        FORCE_AUTO_BRANCH=1
    fi
elif [[ "$DETACHED" == "1" && "$MODE" != "direct" ]]; then
    FORCE_AUTO_BRANCH=1
fi

if [[ "$KIND" == "empty" ]]; then
    echo "nothing staged — stage files with 'git add' first" >&2
    exit 2
fi

if [[ "$DELIVERY" == "direct" && "$DETACHED" == "1" ]]; then
    echo "detached HEAD cannot use direct delivery; rerun with --draft-pr or create a branch" >&2
    exit 2
fi

if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
    case "$DELIVERY" in
        draft_pr|open_pr|auto_merge)
            FORCE_AUTO_BRANCH=1 ;;
    esac
fi

if [[ "$PLAN_ONLY" == "1" ]]; then
    branch_label="${BRANCH:-"(detached)"}"
    echo "kind=$KIND"
    echo "branch=$branch_label"
    echo "head=$HEAD_SHORT"
    echo "mode=$MODE"
    echo "delivery=$DELIVERY"
    echo "force_auto_branch=$FORCE_AUTO_BRANCH"
    echo "stage_all=$STAGE_ALL"
    exit 0
fi

if [[ "$KIND" != "runtime" && "$KIND" != "other" ]]; then
    echo "unknown staged-change classification: $KIND" >&2
    exit 2
fi

create_auto_branch_if_needed() {
    if [[ "$FORCE_AUTO_BRANCH" != "1" ]]; then
        return 0
    fi

    local slug
    slug=$(printf '%s' "$MESSAGE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)
    if [[ -z "$slug" ]]; then
        slug="change"
    fi

    # Agent-scoped prefix so concurrent agents' auto-branches are self-identifying.
    # Override with UNITARES_SHIP_AGENT=<name>; otherwise detect from env.
    local agent_prefix="${UNITARES_SHIP_AGENT:-}"
    if [[ -z "$agent_prefix" ]]; then
        if [[ -n "${CLAUDECODE:-}" ]]; then
            agent_prefix="claude"
        else
            agent_prefix="codex"
        fi
    fi

    local new_branch="${agent_prefix}/auto/$(date +%Y%m%d-%H%M%S)-${slug}"
    echo "[ship] creating PR branch: $new_branch"
    git checkout -b "$new_branch"
    BRANCH="$new_branch"
}

create_or_show_pr() {
    local pr_kind="$1"
    local pr_title pr_body pr_url existing_url

    # GitHub caps PR titles at 256 chars; use only the first line so
    # multi-line commit messages don't fail PR creation.
    pr_title=$(printf '%s\n' "$MESSAGE" | head -n1)

    existing_url=$(gh pr view --json url --jq .url 2>/dev/null || true)
    if [[ -n "$existing_url" ]]; then
        echo "[ship] PR already exists for $BRANCH"
        echo "$existing_url"
        return 0
    fi

    case "$pr_kind" in
        draft_pr)
            pr_body="Auto-shipped by ship.sh as a draft PR. Local work is visible; mark ready after validation/review."
            pr_url=$(gh pr create --draft --title "$pr_title" --body "$pr_body")
            ;;
        open_pr)
            pr_body="Auto-shipped by ship.sh as an open PR. CI gate applies."
            pr_url=$(gh pr create --title "$pr_title" --body "$pr_body")
            ;;
        auto_merge)
            pr_body="Auto-shipped by ship.sh. Auto-merge requested; CI gate applies."
            pr_url=$(gh pr create --title "$pr_title" --body "$pr_body")
            ;;
        *)
            echo "internal error: unknown PR kind $pr_kind" >&2
            exit 2
            ;;
    esac
    echo "$pr_url"

    if [[ "$pr_kind" == "auto_merge" ]]; then
        gh pr merge --auto --squash "$pr_url" || \
            echo "[ship] auto-merge not enabled (branch protection may require manual setup); PR is open"
    fi
}

case "$DELIVERY" in
    direct)
        echo "[ship] direct path → commit + push on $BRANCH"
        git commit -m "$MESSAGE"
        # Push to the same-name branch on origin, not whatever upstream tracks.
        git push -u origin "HEAD:$BRANCH"
        ;;
    draft_pr|open_pr|auto_merge)
        create_auto_branch_if_needed
        echo "[ship] PR path → $BRANCH ($DELIVERY)"
        git commit -m "$MESSAGE"
        git push -u origin "$BRANCH"
        create_or_show_pr "$DELIVERY"
        ;;
    *)
        echo "internal error: unknown delivery path $DELIVERY" >&2
        exit 2
        ;;
esac
