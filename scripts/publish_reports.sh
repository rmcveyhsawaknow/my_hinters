#!/usr/bin/env bash
# Publish redacted run records or reports to the `reports` branch with a fetch-and-retry loop,
# so several agents can publish at once without clobbering each other.
# Usage: publish_reports.sh runs <agent-slug>   (copies runs/ into reports/agents/<slug>/runs/)
#        publish_reports.sh reports <agent-slug> (copies reports/ wholesale)
set -euo pipefail

mode="${1:-runs}"
agent="${2:-}"
case "$agent" in *[!a-z0-9-]*) echo "bad agent slug" >&2; exit 1;; esac

staging="$(mktemp -d)"
if [ "$mode" = "runs" ]; then
  if [ ! -d runs ] || [ -z "$(ls -A runs 2>/dev/null)" ]; then echo "nothing to publish"; exit 0; fi
  mkdir -p "$staging/reports/agents/$agent/runs"
  cp -a runs/. "$staging/reports/agents/$agent/runs/"
else
  if [ ! -d reports ]; then echo "nothing to publish"; exit 0; fi
  mkdir -p "$staging/reports"
  cp -a reports/. "$staging/reports/"
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

for attempt in 1 2 3 4 5; do
  if git fetch origin reports:refs/remotes/origin/reports 2>/dev/null; then
    git checkout -q -B reports origin/reports
  else
    git checkout -q --orphan reports
    git rm -rfq --cached . >/dev/null 2>&1 || true
    find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  fi
  mkdir -p reports
  cp -a "$staging/reports/." reports/
  git add reports/
  if git diff --cached --quiet; then echo "no changes"; exit 0; fi
  git commit -q -m "Publish $mode for $agent"
  if git push origin reports; then echo "published"; exit 0; fi
  echo "push failed (attempt $attempt); retrying"
  sleep $((attempt * 5))
done
echo "could not publish after retries" >&2
exit 1
