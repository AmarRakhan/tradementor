#!/usr/bin/env bash
# READ-ONLY evidence for Kostenreductie 4.1 (COST-001..COST-004, COST-007). Only describe/list commands.
# Run as the owner in Cloud Shell, or by ChatGPT on the Workstation with the existing gcloud login.
# Writes nothing to Google Cloud. Output: ./cost-probe-<UTC>/ (share the folder; it contains no secrets).
set -euo pipefail
umask 077
P=tradementor-production
R=europe-west4
CLUSTER=cluster-mthll54f
CONFIG=config-mthlka1d
WS=w-tradementoradmin-mthm3sja
OUT="cost-probe-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"

run() {  # run <file> <gcloud args...>  — refuses anything that is not a describe/list
  local file="$1"; shift
  case " $* " in *" delete "*|*" update "*|*" stop "*|*" start "*|*" create "*|*" set-"*|*" add-"*|*" remove-"*)
    echo "REFUSED (not read-only): $*" >&2; exit 2;; esac
  case " $* " in *" describe "*|*" list "*) ;; *) echo "REFUSED (not describe/list): $*" >&2; exit 2;; esac
  if gcloud "$@" > "$OUT/$file" 2> "$OUT/$file.err"; then echo "OK   $file"; else echo "FAIL $file (see $file.err)"; fi
}

# A/B — who and what created the live revisions (creator principal, client, image)
for REV in tradementor-api-cp605-421f3452 amar-bot-v44-direct-install-cp605-421f3452 \
           tradementor-api-cp604-aebf1239 tradementor-api-src-f87d6b20-124369; do
  run "revision-$REV.txt" run revisions describe "$REV" --project="$P" --region="$R" \
    --format="yaml(metadata.annotations,metadata.labels,spec.containers[0].image,status.imageDigest,spec.serviceAccountName)"
done
run builds-regional.txt builds list --project="$P" --region="$R" --limit=20 --format="table(id,createTime,status,source.storageSource.object,images)"
run builds-global.txt   builds list --project="$P" --limit=20 --format="table(id,createTime,status,images)"

# F — Workstation state and automatic stop settings
run ws-workstation.txt workstations describe "$WS" --cluster="$CLUSTER" --config="$CONFIG" --region="$R" --project="$P" \
  --format="yaml(state,startTime,updateTime,host,reconciling)"
run ws-config.txt workstations configs describe "$CONFIG" --cluster="$CLUSTER" --region="$R" --project="$P" \
  --format="yaml(idleTimeout,runningTimeout,host.gceInstance.machineType,host.gceInstance.bootDiskSizeGb,persistentDirectories)"
run ws-cluster.txt workstations clusters describe "$CLUSTER" --region="$R" --project="$P" \
  --format="yaml(network,subnetwork,privateClusterConfig,controlPlaneIp,degraded)"

# PSC — which endpoint is billed (Networking Private Service Connect Consumer End Point)
run psc-forwarding-rules.txt compute forwarding-rules list --project="$P" --format="table(name,region.basename(),target,IPAddress,network.basename())"
run compute-disks.txt compute disks list --project="$P" --format="table(name,zone.basename(),region.basename(),sizeGb,type.basename(),users.basename())"
run compute-instances.txt compute instances list --project="$P" --format="table(name,zone.basename(),machineType.basename(),status,labels)"

# COST-007 — remaining Scheduler jobs (Hyperliquid/MEXC paused?)
run scheduler-jobs.txt scheduler jobs list --project="$P" --location="$R" --format="table(name.basename(),schedule,state,httpTarget.uri)"

# COST-005 — Artifact Registry repositories (detailed manifest: tools/cost/ar_inventory.py)
run ar-repositories.txt artifacts repositories list --project="$P" --location=all --format="table(name,format,sizeBytes,cleanupPolicyDryRun)"

# Cloud Run inventory incl. traffic
run run-services.txt run services list --project="$P" --region="$R" \
  --format="table(metadata.name,status.traffic[0].revisionName,status.traffic[0].percent,spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])"
echo "Done. Folder: $OUT (no secrets; safe to share with Claude/ChatGPT)."
