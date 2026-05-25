#!/usr/bin/env bash
# Configure branch protection on a satellite repo per v2 brief requirements.
#
# Idempotent — re-runs are safe. Configures:
#
#   * Required pull request review before merging (1 approval)
#   * Require review from CODEOWNERS
#   * Dismiss stale reviews on new commits
#   * No self-approve
#   * No force-push to main
#
# Requires: gh CLI authenticated with repo admin scope.
#
# Usage:
#   ./scripts/setup-branch-protection.sh cdonovan-abtex/epicoracle-marketplace [branch]
#
# Default branch is "main" if not specified.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <owner/repo> [branch]" >&2
    exit 1
fi

REPO="$1"
BRANCH="${2:-main}"

log() { printf '[branch-protection] %s\n' "$*" >&2; }

log "Configuring branch protection on ${REPO}:${BRANCH}"

# Use gh api directly — the convenience subcommands don't cover every
# field we care about (notably ``dismiss_stale_reviews`` + CODEOWNERS).
gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/${REPO}/branches/${BRANCH}/protection" \
    --input - <<EOF
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true
}
EOF

log "Branch protection configured on ${REPO}:${BRANCH}."
log ""
log "Manual verification steps:"
log "  1. Visit https://github.com/${REPO}/settings/branches"
log "  2. Confirm 'Require a pull request before merging' is ON"
log "  3. Confirm 'Require review from Code Owners' is ON"
log "  4. Confirm 'Allow force pushes' is OFF"
log "  5. Confirm 'Allow deletions' is OFF"
