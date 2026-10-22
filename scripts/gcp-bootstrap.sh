#!/usr/bin/env bash
# Phase 2 of docs/distributed-ecosystem-plan.md: the GCP project the ecosystem publishes to.
# Idempotent. Needs a billing account linked to the project first (console: Billing, or
#   gcloud billing projects link "$PROJECT" --billing-account="$BILLING_ACCOUNT").
# Usage: scripts/gcp-bootstrap.sh [--project my-hinters] [--region us-central1] [--budget 20]
#        [--billing-account 0X0X0X-0X0X0X-0X0X0X] [--host desktop-okqpjmv] [--dry-run]
set -euo pipefail

PROJECT="my-hinters"; REGION="us-central1"; BUDGET="20"; BILLING_ACCOUNT=""; HOST_ID=""; DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --billing-account) BILLING_ACCOUNT="$2"; shift 2 ;;
    --host) HOST_ID="$2"; shift 2 ;;
    --dry-run) DRY="echo would run:"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
BUCKET="gs://${PROJECT}-ecosystem"
run() { if [ -n "$DRY" ]; then echo "$DRY $*"; else "$@"; fi; }

echo "== project $PROJECT"
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
LINKED="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' || true)"
if [ -z "$LINKED" ]; then
  if [ -n "$BILLING_ACCOUNT" ]; then
    run gcloud billing projects link "$PROJECT" --billing-account="$BILLING_ACCOUNT"
    LINKED="billingAccounts/$BILLING_ACCOUNT"
  else
    echo "no billing account is linked to $PROJECT; link one (console: Billing) or pass --billing-account, then rerun" >&2
    exit 1
  fi
fi
echo "billing: $LINKED"

echo "== APIs"
run gcloud services enable --project "$PROJECT" \
  storage.googleapis.com iam.googleapis.com cloudresourcemanager.googleapis.com logging.googleapis.com \
  bigquery.googleapis.com run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
  billingbudgets.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

echo "== budget: $BUDGET USD per month, alerts at 50, 90 and 100 percent, scoped to this project"
ACCOUNT="${LINKED#billingAccounts/}"
if gcloud billing budgets list --billing-account="$ACCOUNT" --format='value(displayName)' 2>/dev/null | grep -qx "$PROJECT monthly"; then
  echo "budget '$PROJECT monthly' exists"
else
  run gcloud billing budgets create --billing-account="$ACCOUNT" --display-name="$PROJECT monthly" \
    --budget-amount="${BUDGET}USD" --filter-projects="projects/$NUMBER" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
fi

echo "== bucket $BUCKET ($REGION, uniform access, no public access, versioning, backups to Nearline after 30 days)"
if gcloud storage buckets describe "$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  echo "bucket exists"
else
  run gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi
run gcloud storage buckets update "$BUCKET" --versioning
LIFECYCLE="$(mktemp)"
cat > "$LIFECYCLE" <<'JSON'
{"rule": [
  {"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"}, "condition": {"age": 30, "matchesPrefix": ["hosts/"]}},
  {"action": {"type": "Delete"}, "condition": {"age": 180, "matchesPrefix": ["hosts/"], "isLive": false}}
]}
JSON
run gcloud storage buckets update "$BUCKET" --lifecycle-file="$LIFECYCLE"
rm -f "$LIFECYCLE"

if [ -n "$HOST_ID" ]; then
  SA="host-${HOST_ID}@${PROJECT}.iam.gserviceaccount.com"
  echo "== service account for host $HOST_ID: $SA (object creator and viewer on this bucket only)"
  if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
    run gcloud iam service-accounts create "host-${HOST_ID}" --project "$PROJECT" --display-name="ecosystem host $HOST_ID"
  fi
  run gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectCreator"
  run gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectViewer"
  echo "next, on that host (the key goes into the keyring, never into the repository):"
  echo "  gcloud iam service-accounts keys create host-${HOST_ID}.json --iam-account=$SA   # then store it and delete the file"
  echo "  set ecosystem.backup_target: $BUCKET in config/local.yaml and run: hglab local backup push"
fi
echo "== done"
