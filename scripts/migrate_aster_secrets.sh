#!/usr/bin/env bash
set -euo pipefail

SOURCE_PROJECT="tradementor-production"
TARGET_PROJECT="tradementor-amar-20260813"
PREFIX="tradementor-aster-"

if [[ "${1:-}" != "--apply" ]]; then
  echo "Veilige controle: er worden nog geen secrets gekopieerd."
  gcloud secrets list \
    --project="${SOURCE_PROJECT}" \
    --filter="name~^${PREFIX}" \
    --format="value(name)" | sed '/^$/d' | wc -l | awk '{print "Gevonden Aster-koppelingen:", $1}'
  echo "Voer hetzelfde script uit met --apply om alleen ontbrekende koppelingen te migreren."
  exit 0
fi

if [[ "${SOURCE_PROJECT}" != "tradementor-production" || "${TARGET_PROJECT}" != "tradementor-amar-20260813" ]]; then
  echo "Afgebroken: onverwachte bron of bestemming." >&2
  exit 1
fi

mapfile -t secret_ids < <(
  gcloud secrets list \
    --project="${SOURCE_PROJECT}" \
    --filter="name~^${PREFIX}" \
    --format="value(name)" | sed '/^$/d' | sort
)

if [[ ${#secret_ids[@]} -eq 0 ]]; then
  echo "Afgebroken: geen bestaande Aster-koppelingen gevonden." >&2
  exit 1
fi

copied=0
skipped=0
for secret_id in "${secret_ids[@]}"; do
  if [[ "${secret_id}" != "${PREFIX}"* ]]; then
    echo "Afgebroken: onverwachte secretnaam." >&2
    exit 1
  fi

  if gcloud secrets describe "${secret_id}" --project="${TARGET_PROJECT}" >/dev/null 2>&1; then
    version_count="$(gcloud secrets versions list "${secret_id}" --project="${TARGET_PROJECT}" --filter='state=enabled' --format='value(name)' | sed '/^$/d' | wc -l)"
    if [[ "${version_count}" -gt 0 ]]; then
      echo "Overslaan (bestaat al): ${secret_id}"
      skipped=$((skipped + 1))
      continue
    fi
  else
    gcloud secrets create "${secret_id}" \
      --project="${TARGET_PROJECT}" \
      --replication-policy="automatic" \
      --labels="migrated-from=tradementor-production" >/dev/null
  fi

  # De payload gaat rechtstreeks van bron naar doel en wordt nooit afgedrukt
  # of als tijdelijk bestand opgeslagen.
  gcloud secrets versions access latest \
    --secret="${secret_id}" \
    --project="${SOURCE_PROJECT}" \
    | gcloud secrets versions add "${secret_id}" \
        --project="${TARGET_PROJECT}" \
        --data-file=- >/dev/null
  echo "Gekopieerd: ${secret_id}"
  copied=$((copied + 1))
done

echo "Migratie gereed. Gekopieerd: ${copied}; veilig overgeslagen: ${skipped}."
