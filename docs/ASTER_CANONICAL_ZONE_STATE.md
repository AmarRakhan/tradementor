# Aster Canonical Zone State

Build 580 introduces one server-authoritative browser contract at `strategy2.runtimeTruth.zoneState`.

## Ownership matrix

| Value | Canonical owner |
| --- | --- |
| Account open total | exchange/runtime account snapshot |
| Account LONG | exchange/runtime account snapshot |
| Account SHORT | exchange/runtime account snapshot |
| Strategy-2 open positions | canonical zoneState |
| Zone ownership | canonical zoneState |
| Active zone | canonical zoneState |
| LONG max per zone | saved Strategy-2 settings through zoneState |
| SHORT max per zone | saved Strategy-2 settings through zoneState |
| Max total positions | saved Strategy-2 settings through zoneState |
| Zone price range | canonical server zone ladder |
| Unassigned Strategy-2 positions | canonical zoneState |
| Non-Strategy-2 open positions | canonical zoneState |

## Invariants

`account.totalOpen = strategyOwned.totalOpen + nonStrategyOwned.totalOpen`

`strategyOwned.totalOpen = sum(zones[].totalOpen) + unassignedStrategyPositions.length`

The same invariants apply independently to LONG and SHORT counts.

## Frontend contract

BESTAAT DE DATA AL? GEBRUIK DE CANONIEKE BRON. BOUW GEEN TWEEDE STATE OF AFLEIDING.

FRONTEND FORMATTEERT EN RENDERT; FRONTEND BEPAALT GEEN ACCOUNT- OF TRADINGTRUTH.

Frontend consumers must not reconstruct zone occupancy from `multiBbPositions`, `seatModel`, `priceZoneSeats`, `zoneSoldiers`, localStorage or sessionStorage.

Legacy fields may remain temporarily for backward compatibility, but they are deprecated as browser truth sources.
