"""Build 620: ordergeschiedenis (orderAttributions) compact houden in het accountdocument.

Waarom
- 23-10-2026 liep ``asterStrategy2/{uid}`` over de Firestore-limiet van 1 MiB.
  ``orderAttributions`` (tot 2000 rijen, ~610 kB) was de grootste post.

Wat er in het document blijft (alle lezers zijn hierop nagelopen)
- alle rijen van de laatste ``KEEP_RECENT_DAYS`` dagen
  (meldingen, grafiekmarkers 36-48 u, Spike-dubbelcheck, scangeschiedenis);
- per munt+kant de nieuwste rij (eigendomsbewijs bij self-heal: kijkt naar de laatste actie);
- per munt+kant alle rijen van de lopende cyclus, d.w.z. vanaf de laatste volledige
  sluiting (DCA-telling en strategienaam van open posities).

Al het andere gaat naar de subcollectie ``orderAttributionArchive`` (één document per
rij, vaste id, dus opnieuw schrijven is onschadelijk). Rijen verdwijnen pas uit het
document nadat het archief bevestigd is geschreven; lukt dat niet, dan blijft alles
staan zoals voorheen (max. 2000 rijen).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Iterable

ARCHIVE_COLLECTION = "orderAttributionArchive"
KEEP_RECENT_DAYS = 7
MAX_DOCUMENT_ROWS = 2000
# Pas bij tick-start compacteren als dit aantal rijen naar het archief kan
# (voorkomt een extra schrijfactie bij elke tick).
TICK_COMPACT_MIN_ARCHIVABLE = 50
FULL_CLOSE_ACTIONS = frozenset({"FULL_TP", "TAKE_PROFIT_CLOSE"})
_BATCH_LIMIT = 400


def _row_time(row: dict[str, Any]) -> float:
    value = row.get("recordedAt")
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("symbol") or "").upper().strip(), str(row.get("side") or "").upper().strip()


def archive_id(row: dict[str, Any]) -> str:
    raw = "|".join(str(row.get(k) or "") for k in ("orderId", "clientOrderId", "symbol", "side", "action"))
    raw += "|" + repr(_row_time(row))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def split_rows(rows: Iterable[Any], *, now: datetime | None = None,
               keep_recent_days: float = KEEP_RECENT_DAYS) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(houden, archiveren) — volgorde van ``rows`` blijft behouden."""
    clean = [row for row in rows if isinstance(row, dict)]
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    recent_cutoff = now_ts - keep_recent_days * 86400
    latest_index: dict[tuple[str, str], int] = {}
    latest_time: dict[tuple[str, str], float] = {}
    last_close: dict[tuple[str, str], float] = {}
    for index, row in enumerate(clean):
        key = _key(row)
        stamp = _row_time(row)
        if key not in latest_time or stamp >= latest_time[key]:
            latest_time[key] = stamp
            latest_index[key] = index
        if str(row.get("action") or "").upper() in FULL_CLOSE_ACTIONS:
            last_close[key] = max(last_close.get(key, float("-inf")), stamp)
    keep: list[dict[str, Any]] = []
    archive: list[dict[str, Any]] = []
    for index, row in enumerate(clean):
        key = _key(row)
        stamp = _row_time(row)
        # Een rij zonder leesbare tijd wordt nooit gearchiveerd (twijfel = bewaren).
        if (stamp <= 0 or stamp >= recent_cutoff or latest_index.get(key) == index
                or stamp >= last_close.get(key, float("-inf"))):
            keep.append(row)
        else:
            archive.append(row)
    return keep, archive


def write_archive(ref: Any, rows: list[dict[str, Any]]) -> bool:
    """Schrijf rijen naar de archief-subcollectie. True alleen als alles bevestigd is."""
    if not rows:
        return True
    try:
        collection = ref.collection(ARCHIVE_COLLECTION)
        client = getattr(ref, "_client", None)
        for start in range(0, len(rows), _BATCH_LIMIT):
            chunk = rows[start:start + _BATCH_LIMIT]
            batch = client.batch() if client is not None and hasattr(client, "batch") else None
            for row in chunk:
                document = collection.document(archive_id(row))
                payload = {**row, "archivedAt": datetime.now(timezone.utc)}
                if batch is not None:
                    batch.set(document, payload)
                else:
                    document.set(payload)
            if batch is not None:
                batch.commit()
        return True
    except Exception as exc:  # archief onzeker = niets uit het document halen
        print(f"ORDER_ATTRIBUTION_ARCHIVE_FAILED {exc}", flush=True)
        return False


def compact_for_write(ref: Any, rows: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Voor de bestaande schrijvers: rijen die in het document mogen blijven."""
    keep, archive = split_rows(rows, now=now)
    if archive and write_archive(ref, archive):
        return keep[-MAX_DOCUMENT_ROWS:]
    return rows[-MAX_DOCUMENT_ROWS:]


def compact_document(ref: Any, raw: dict[str, Any] | None = None, *, now: datetime | None = None,
                     min_archivable: int = TICK_COMPACT_MIN_ARCHIVABLE) -> int:
    """Bij tick-start: archiveer en schrijf alleen als het document intussen niet is gewijzigd.

    Gebruikt een last-update-time-voorwaarde, zodat een gelijktijdig toegevoegde
    attributie nooit wordt overschreven. Geeft het aantal gearchiveerde rijen terug.
    ``raw`` (het al gelezen document) bepaalt goedkoop óf er iets te doen is; alleen
    dan volgt een verse lezing met tijdstempel.
    """
    try:
        if raw is not None:
            rows_in_raw = raw.get("orderAttributions")
            if not isinstance(rows_in_raw, list):
                return 0
            if len(split_rows(rows_in_raw, now=now)[1]) < min_archivable:
                return 0
        snapshot = ref.get()
        data = snapshot.to_dict() or {}
        rows = data.get("orderAttributions")
        if not isinstance(rows, list):
            return 0
        keep, archive = split_rows(rows, now=now)
        if len(archive) < min_archivable:
            return 0
        if not write_archive(ref, archive):
            return 0
        client = getattr(ref, "_client", None)
        update_time = getattr(snapshot, "update_time", None)
        if client is not None and update_time is not None and hasattr(client, "write_option"):
            ref.update({"orderAttributions": keep}, option=client.write_option(last_update_time=update_time))
        else:
            ref.update({"orderAttributions": keep})
        print(f"ORDER_ATTRIBUTIONS_COMPACTED archived={len(archive)} kept={len(keep)}", flush=True)
        return len(archive)
    except Exception as exc:  # o.a. voorwaarde mislukt: volgende tick opnieuw
        print(f"ORDER_ATTRIBUTION_COMPACT_SKIPPED {exc}", flush=True)
        return 0
