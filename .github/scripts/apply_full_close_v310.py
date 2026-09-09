from pathlib import Path
import re
from textwrap import dedent

REFERENCE_ID = "file_00000000b4bc8210aa8f4c8e32f5e7dd"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def patch_backend() -> None:
    path = Path("cloud_api/main.py")
    text = path.read_text()
    if '@app.post("/v1/me/aster/positions/close-all")' in text:
        return

    model = dedent('''
    class AsterCloseAllRequest(BaseModel):
        confirm: bool
        quote_id: str = Field(min_length=16, max_length=120)
        idempotency_key: str = Field(min_length=16, max_length=120)
    ''').lstrip()
    model_new = model + dedent('''

    class AsterFullCloseRequest(BaseModel):
        confirm: bool
        idempotency_key: str = Field(min_length=16, max_length=120)
    ''')
    text = replace_once(text, model, model_new, "AsterCloseAllRequest model")

    anchor = '@app.get("/v1/me/aster/positions/profitable-close-preview")\n'
    route = dedent(r'''
    @app.post("/v1/me/aster/positions/close-all")
    def close_all_aster_positions(
        request: AsterFullCloseRequest,
        user: dict[str, Any] = Depends(authenticated_user),
    ) -> dict[str, Any]:
        """Explicitly close every current Aster hedge leg, independent of profit."""
        if not request.confirm:
            raise HTTPException(422, "Bevestiging voor Alles sluiten ontbreekt")
        if os.getenv("ASTER_LIVE_EXECUTION_ENABLED", "false").lower() != "true":
            raise HTTPException(423, "Aster productie-uitvoering staat centraal uit")

        uid = str(user["uid"])
        action_hash = hashlib.sha256(f"{uid}:full-close:{request.idempotency_key}".encode()).hexdigest()
        action_ref = user_reference(user).collection("asterFullCloseIntents").document(action_hash)
        growth = portfolio_growth_reference(uid)
        strategy_ref = aster_strategy2_reference(uid)
        lock_token = python_secrets.token_hex(16)
        now = datetime.now(timezone.utc)

        try:
            action_ref.create({
                "uid": uid,
                "status": "RESERVED",
                "createdAt": now,
                "idempotencyKeyHash": action_hash,
            })
        except google_exceptions.AlreadyExists as exc:
            existing = action_ref.get().to_dict() or {}
            result = existing.get("result")
            if existing.get("status") in {"CONFIRMED_FLAT", "PARTIAL_FAIL_CLOSED"} and isinstance(result, dict):
                return {**result, "duplicate": True}
            raise HTTPException(409, "Deze Alles sluiten-opdracht is al ontvangen; er wordt geen tweede set orders geplaatst") from exc

        reserved = False

        def release_account_lock(reason: str) -> None:
            transaction = db.transaction()

            @firestore.transactional
            def release(txn):
                current = growth.get(transaction=txn).to_dict() or {}
                lock = current.get("closeLock") if isinstance(current.get("closeLock"), dict) else {}
                if lock.get("token") == lock_token:
                    txn.set(growth, {"closeLock": {
                        "active": False,
                        "token": "",
                        "actionId": action_hash,
                        "releasedAt": datetime.now(timezone.utc),
                    }}, merge=True)
                txn.set(strategy_ref, {
                    "enabled": False,
                    "monitor": False,
                    "closeAllPause": False,
                    "phase": "STOPPED",
                    "pendingReopens": [],
                    "lastReason": reason,
                    "updatedAt": datetime.now(timezone.utc),
                }, merge=True)

            release(transaction)

        transaction = db.transaction()

        @firestore.transactional
        def reserve_account(txn):
            current = growth.get(transaction=txn).to_dict() or {}
            lock = current.get("closeLock") if isinstance(current.get("closeLock"), dict) else {}
            until = lock.get("until")
            active = bool(lock.get("active")) and (not isinstance(until, datetime) or until > now)
            if active:
                raise HTTPException(409, "Voor dit account loopt al een Alles sluiten-actie")
            txn.set(growth, {"closeLock": {
                "active": True,
                "token": lock_token,
                "actionId": action_hash,
                "until": now + timedelta(hours=1),
            }}, merge=True)
            txn.set(strategy_ref, {
                "enabled": False,
                "monitor": True,
                "closeAllPause": True,
                "phase": "CLOSING_ALL",
                "pendingReopens": [],
                "lastReason": "Persoonlijk Alles sluiten actief",
                "updatedAt": now,
            }, merge=True)

        try:
            reserve_account(transaction)
            reserved = True
            client = _portfolio_growth_client(user, live=True)

            open_orders = client.open_orders()
            unknown = [row for row in open_orders if is_exposure_order(row) is None]
            if unknown:
                raise RuntimeError("Open order(s) kunnen niet veilig als instap of bescherming worden geclassificeerd")
            for order in [row for row in open_orders if is_exposure_order(row) is True]:
                client.cancel_order(
                    str(order.get("symbol", "")),
                    order_id=order.get("orderId"),
                    client_order_id=order.get("clientOrderId"),
                )

            starting_positions = [row for row in client.position_risk() if abs(safe_float(row.get("positionAmt"))) > 0]
            requested_count = len(starting_positions)
            requested_longs = sum(1 for row in starting_positions if str(row.get("positionSide", "")).upper() == "LONG")
            requested_shorts = sum(1 for row in starting_positions if str(row.get("positionSide", "")).upper() == "SHORT")
            starting_keys = {
                (str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper())
                for row in starting_positions
            }
            failures: list[dict[str, Any]] = []

            for index, initial in enumerate(starting_positions, 1):
                symbol = str(initial.get("symbol", "")).upper()
                side = str(initial.get("positionSide", "")).upper()
                try:
                    current_rows = client.position_risk()
                    current = next((row for row in current_rows
                        if str(row.get("symbol", "")).upper() == symbol
                        and str(row.get("positionSide", "")).upper() == side
                        and abs(safe_float(row.get("positionAmt"))) > 0), None)
                    if current is None:
                        continue
                    quantity = abs(Decimal(str(current.get("positionAmt"))))
                    mark = safe_float(current.get("markPrice")) or safe_float(current.get("entryPrice"))
                    if not symbol or side not in {"LONG", "SHORT"} or quantity <= 0 or mark <= 0:
                        raise RuntimeError("Aster gaf geen betrouwbare actuele sluitgegevens")
                    plan = PairExecutionPlan(
                        symbol,
                        quantity,
                        quantity * Decimal(str(mark)),
                        max(1, int(safe_float(current.get("leverage")) or 1)),
                    )
                    execute_aster_leg(
                        client,
                        plan,
                        side=PositionSide(side),
                        action="CLOSE",
                        id_prefix=f"tm-full-{action_hash[:12]}-{index}",
                        confirm=True,
                        manual_loss_confirmation=True,
                    )
                    tolerance = max(Decimal("0.000000000001"), quantity * Decimal("0.000000001"))
                    remaining_leg = next((row for row in client.position_risk()
                        if str(row.get("symbol", "")).upper() == symbol
                        and str(row.get("positionSide", "")).upper() == side
                        and abs(Decimal(str(row.get("positionAmt")))) > tolerance), None)
                    if remaining_leg is not None:
                        raise RuntimeError("Aster heeft de volledige sluiting nog niet bevestigd; er wordt niet blind opnieuw besteld")
                except Exception as exc:
                    failures.append({"symbol": symbol or "?", "side": side or "?", "reason": str(exc)[:220]})

            final_positions = [row for row in client.position_risk() if abs(safe_float(row.get("positionAmt"))) > 0]
            final_keys = {
                (str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper())
                for row in final_positions
            }
            remaining_starting = len(starting_keys & final_keys)
            closed_count = max(0, requested_count - remaining_starting)

            remaining_orders: list[dict[str, Any]] = []
            if not final_positions:
                for order in client.open_orders():
                    try:
                        client.cancel_order(
                            str(order.get("symbol", "")),
                            order_id=order.get("orderId"),
                            client_order_id=order.get("clientOrderId"),
                        )
                    except Exception as exc:
                        failures.append({"symbol": str(order.get("symbol", "?")), "side": "ORDER", "reason": str(exc)[:220]})
                remaining_orders = client.open_orders()

            complete = len(final_positions) == 0 and len(remaining_orders) == 0
            result = {
                "actionId": action_hash,
                "requestedCount": requested_count,
                "requestedLongs": requested_longs,
                "requestedShorts": requested_shorts,
                "closedCount": closed_count,
                "remainingCount": len(final_positions),
                "remainingOrders": len(remaining_orders),
                "failedCount": len(failures),
                "failures": failures[:20],
                "complete": complete,
                "botPaused": True,
                "duplicate": False,
                "message": (
                    "Alle actieve posities zijn exchange-bevestigd gesloten."
                    if complete else
                    f"{closed_count} van {requested_count} startposities zijn bevestigd gesloten; {len(final_positions)} positie(s) staan nog open."
                ),
            }
            status = "CONFIRMED_FLAT" if complete else "PARTIAL_FAIL_CLOSED"
            action_ref.set({"status": status, "result": result, "completedAt": datetime.now(timezone.utc)}, merge=True)
            release_account_lock(
                "Alles sluiten voltooid; bot blijft bewust gestopt"
                if complete else
                "Alles sluiten gedeeltelijk voltooid; bot blijft gestopt voor veilige herhaling"
            )
            reserved = False
            return result
        except HTTPException as exc:
            action_ref.set({"status": "FAILED_BEFORE_CLOSE", "detail": str(exc.detail), "updatedAt": datetime.now(timezone.utc)}, merge=True)
            if reserved:
                release_account_lock("Alles sluiten veilig gestopt na fout; bot blijft gestopt")
            raise
        except Exception as exc:
            action_ref.set({"status": "FAILED_BEFORE_CLOSE", "detail": str(exc)[:500], "updatedAt": datetime.now(timezone.utc)}, merge=True)
            if reserved:
                release_account_lock("Alles sluiten veilig gestopt na fout; bot blijft gestopt")
            raise HTTPException(409, f"Alles sluiten is veilig gestopt: {str(exc)[:300]}") from exc


    ''')
    text = replace_once(text, anchor, route + anchor, "profit preview route")
    path.write_text(text)


def patch_frontend() -> None:
    path = Path("web/components/aster-portfolio-snapshot-enhancer.tsx")
    text = path.read_text()
    if REFERENCE_ID in text:
        return

    profit_preview_type = dedent('''
    type ProfitPreview = {
      reliable: true;
      minimumProfitUsd: number;
      comparison: "greater_than_or_equal";
      long: ProfitBucket;
      short: ProfitBucket;
      all: ProfitBucket;
    };
    ''').lstrip()
    extra_types = profit_preview_type + dedent('''

    type FullClosePreview = { active: number; longs: number; shorts: number };
    type FullCloseFailure = { symbol?: string; side?: string; reason?: string };
    type FullCloseResult = {
      actionId: string;
      requestedCount: number;
      requestedLongs: number;
      requestedShorts: number;
      closedCount: number;
      remainingCount: number;
      remainingOrders: number;
      failedCount: number;
      failures: FullCloseFailure[];
      complete: boolean;
      botPaused: boolean;
      message: string;
      duplicate?: boolean;
    };
    type FullCloseMode = "idle" | "confirm" | "closing" | "partial" | "error";
    ''')
    text = replace_once(text, profit_preview_type, extra_types, "profit preview types")
    text = replace_once(
        text,
        'const REFERENCE = "https://chatgpt.com/s/m_6a9e9a59189881918875e6317fdfc847";',
        f'const REFERENCE = "https://chatgpt.com/s/m_6a9e9a59189881918875e6317fdfc847";\nconst FULL_CLOSE_REFERENCE = "{REFERENCE_ID}";',
        "reference constant",
    )

    text = replace_once(text, '  const closeButton = document.querySelector<HTMLButtonElement>(".portfolio-close-all");\n', '', "legacy close button lookup")
    text = replace_once(
        text,
        '  const dailyGrowth = document.querySelector<HTMLElement>(".portfolio-growth-daily");',
        '  const activePositions = metric("ACTIEVE POSITIES");\n  const activePositionCount = Number(activePositions.replace(/[^\\d]/g, "")) || 0;\n  const dailyGrowth = document.querySelector<HTMLElement>(".portfolio-growth-daily");',
        "active position count",
    )
    text = replace_once(text, '    activePositions: metric("ACTIEVE POSITIES"),', '    activePositions,', "activePositions value")
    text = replace_once(text, '    closeDisabled: !closeButton || closeButton.disabled,', '    closeDisabled: activePositionCount < 1,', "full close disabled")
    text = replace_once(text, '    closeBusy: Boolean(closeButton && /sluiten…|bezig|wachten/i.test(closeButton.textContent || "")),', '    closeBusy: false,', "legacy close busy")

    text = replace_once(text, '  profitBusy,\n  onCloseAll,', '  profitBusy,\n  fullCloseBusy,\n  onCloseAll,', "Snapshot prop args")
    text = replace_once(text, '  profitBusy: ProfitScope | null;\n  onCloseAll: () => void;', '  profitBusy: ProfitScope | null;\n  fullCloseBusy: boolean;\n  onCloseAll: () => void;', "Snapshot prop types")
    text = replace_once(
        text,
        '<button type="button" className="aps-close-all" disabled={values.closeDisabled} onClick={onCloseAll}>{values.closeBusy ? "SLUITEN…" : "ALLES SLUITEN"}</button>',
        '<button type="button" className="aps-close-all" disabled={values.closeDisabled || fullCloseBusy} onClick={onCloseAll}>{fullCloseBusy ? "SLUITEN…" : "ALLES SLUITEN"}</button>',
        "Snapshot header full close button",
    )

    helpers = dedent('''
    function fullCloseQuantity(value: unknown) {
      if (!value || typeof value !== "object") return 0;
      const row = value as Record<string, unknown>;
      const raw = Number(row.quantity ?? row.positionAmt ?? 0);
      return Number.isFinite(raw) ? Math.abs(raw) : 0;
    }

    function fullCloseSide(value: unknown) {
      if (!value || typeof value !== "object") return "";
      const row = value as Record<string, unknown>;
      return String(row.side ?? row.positionSide ?? "").toUpperCase();
    }

    async function loadFullClosePreview(): Promise<FullClosePreview> {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      if (!Array.isArray(payload?.positions)) throw new Error("Actuele Aster-posities konden niet betrouwbaar worden opgehaald.");
      const active = payload.positions.filter((row) => fullCloseQuantity(row) > 0);
      return {
        active: active.length,
        longs: active.filter((row) => fullCloseSide(row) === "LONG").length,
        shorts: active.filter((row) => fullCloseSide(row) === "SHORT").length,
      };
    }

    function FullCloseOverlay({ mode, preview, result, error, onCancel, onConfirm, onRetry }: {
      mode: Exclude<FullCloseMode, "idle">;
      preview: FullClosePreview | null;
      result: FullCloseResult | null;
      error: string;
      onCancel: () => void;
      onConfirm: () => void;
      onRetry: () => void;
    }) {
      const requested = result?.requestedCount ?? preview?.active ?? 0;
      const closed = result?.closedCount ?? 0;
      const canDismiss = mode !== "closing";
      return <div className="aps-full-close-backdrop" role="presentation" data-reference={FULL_CLOSE_REFERENCE}>
        <section className={`aps-full-close-modal aps-full-close-${mode}`} role="dialog" aria-modal="true" aria-labelledby="aps-full-close-title">
          <button className="aps-full-close-x" type="button" aria-label="Sluiten" disabled={!canDismiss} onClick={onCancel}>×</button>
          {mode === "confirm" && <>
            <div className="aps-full-close-warning" aria-hidden="true">!</div>
            <h3 id="aps-full-close-title">Alles sluiten</h3>
            <p className="aps-full-close-question">Weet je zeker dat je alle actieve posities wilt sluiten?</p>
            <p className="aps-full-close-sub">Dit sluit alle open LONG- en SHORT-posities, ongeacht winst of verlies.</p>
            <dl className="aps-full-close-counts">
              <div><dt>Actieve posities</dt><dd>{preview?.active ?? 0}</dd></div>
              <div><dt>Long posities</dt><dd>{preview?.longs ?? 0}</dd></div>
              <div><dt>Short posities</dt><dd>{preview?.shorts ?? 0}</dd></div>
            </dl>
            <footer className="aps-full-close-actions">
              <button type="button" onClick={onCancel}>Annuleren</button>
              <button type="button" className="aps-full-close-danger" onClick={onConfirm}>Alles sluiten</button>
            </footer>
          </>}
          {mode === "closing" && <>
            <div className="aps-full-close-spinner" aria-hidden="true"><i /></div>
            <h3 id="aps-full-close-title">Bezig met sluiten...</h3>
            <p className="aps-full-close-question">Alle actieve posities worden gesloten.<br />Dit kan even duren.</p>
            <div className="aps-full-close-progress" aria-label="Sluitstatus wordt bij Aster bevestigd"><i /></div>
            <strong className="aps-full-close-progress-label">Sluitstatus wordt rechtstreeks bij Aster bevestigd</strong>
            <div className="aps-full-close-info">De pagina wordt na afronding automatisch vernieuwd. Laat dit venster gerust openstaan.</div>
          </>}
          {mode === "partial" && <>
            <div className="aps-full-close-warning" aria-hidden="true">!</div>
            <h3 id="aps-full-close-title">Niet alle posities konden worden gesloten</h3>
            <p className="aps-full-close-question">{closed} van {requested} posities bevestigd gesloten.</p>
            <p className="aps-full-close-sub">{result?.remainingCount ?? 0} positie(s) staan nog open. De bot blijft gestopt zodat je veilig opnieuw kunt proberen.</p>
            <footer className="aps-full-close-actions">
              <button type="button" onClick={onCancel}>Sluiten</button>
              <button type="button" className="aps-full-close-danger" onClick={onRetry}>Opnieuw proberen</button>
            </footer>
          </>}
          {mode === "error" && <>
            <div className="aps-full-close-warning" aria-hidden="true">!</div>
            <h3 id="aps-full-close-title">Alles sluiten mislukt</h3>
            <p className="aps-full-close-sub">{error || "De sluitstatus kon niet betrouwbaar worden bevestigd."}</p>
            <footer className="aps-full-close-actions">
              <button type="button" onClick={onCancel}>Sluiten</button>
              <button type="button" className="aps-full-close-danger" onClick={onRetry}>Opnieuw proberen</button>
            </footer>
          </>}
        </section>
      </div>;
    }

    ''')
    text = replace_once(text, 'async function loadProfitPreview(): Promise<ProfitPreview> {', helpers + 'async function loadProfitPreview(): Promise<ProfitPreview> {', "profit preview helper")

    text = replace_once(
        text,
        '  const [profitBusy, setProfitBusy] = useState<ProfitScope | null>(null);',
        dedent('''
          const [profitBusy, setProfitBusy] = useState<ProfitScope | null>(null);
          const [fullCloseMode, setFullCloseMode] = useState<FullCloseMode>("idle");
          const [fullClosePreview, setFullClosePreview] = useState<FullClosePreview | null>(null);
          const [fullCloseResult, setFullCloseResult] = useState<FullCloseResult | null>(null);
          const [fullCloseError, setFullCloseError] = useState("");
          const [fullCloseSuccess, setFullCloseSuccess] = useState(false);
          const fullCloseRequestKey = useRef("");
        ''').rstrip(),
        "enhancer full close state",
    )

    text = replace_once(
        text,
        '  const syncing = useRef(false);\n\n  useEffect(() => {',
        dedent('''
          const syncing = useRef(false);

          useEffect(() => {
            if (fullCloseMode === "idle") return;
            const previous = document.body.style.overflow;
            document.body.style.overflow = "hidden";
            return () => { document.body.style.overflow = previous; };
          }, [fullCloseMode]);

          useEffect(() => {
        ''').rstrip(),
        "modal scroll lock",
    )

    close_pattern = re.compile(r'  const closeAll = \(\) => \{\n    const legacy = document\.querySelector<HTMLButtonElement>\("\.portfolio-close-all"\);\n    if \(!legacy \|\| legacy\.disabled\) return;\n    legacy\.click\(\);\n  \};')
    match = close_pattern.search(text)
    if not match:
        raise RuntimeError("missing anchor: legacy closeAll handler")
    handlers = dedent('''
      const openFullCloseConfirm = async () => {
        if (fullCloseMode === "closing") return;
        setFullCloseError("");
        setFullCloseResult(null);
        fullCloseRequestKey.current = "";
        try {
          const preview = await loadFullClosePreview();
          setFullClosePreview(preview);
          if (preview.active < 1) return;
          setFullCloseMode("confirm");
        } catch (reason) {
          setFullCloseError(reason instanceof Error ? reason.message : "Actuele Aster-posities konden niet worden opgehaald.");
          setFullCloseMode("error");
        }
      };

      const executeFullClose = async () => {
        if (fullCloseMode === "closing") return;
        setFullCloseError("");
        setFullCloseResult(null);
        setFullCloseMode("closing");
        try {
          const fresh = await loadFullClosePreview();
          setFullClosePreview(fresh);
          if (fresh.active < 1) {
            setFullCloseMode("idle");
            return;
          }
          if (!fullCloseRequestKey.current) fullCloseRequestKey.current = `snapshot-full-close-${Date.now()}-${crypto.randomUUID()}`;
          const payload = await authenticatedRequest("/api/exchanges/aster/positions/close-all", {
            method: "POST",
            body: JSON.stringify({ confirm: true, idempotency_key: fullCloseRequestKey.current }),
          }) as FullCloseResult;
          if (!payload || !Number.isInteger(payload.requestedCount) || !Number.isInteger(payload.closedCount) || !Number.isInteger(payload.remainingCount) || typeof payload.complete !== "boolean") {
            throw new Error("Aster gaf geen betrouwbare eindstatus voor Alles sluiten.");
          }
          setFullCloseResult(payload);
          if (payload.complete && payload.remainingCount === 0) {
            setFullCloseMode("idle");
            setFullCloseSuccess(true);
            window.setTimeout(() => window.location.reload(), 1600);
          } else {
            setFullCloseMode("partial");
          }
        } catch (reason) {
          setFullCloseError(reason instanceof Error ? reason.message : "De sluitstatus kon niet betrouwbaar worden bevestigd.");
          setFullCloseMode("error");
        }
      };

      const retryFullClose = async () => {
        try {
          const preview = await loadFullClosePreview();
          setFullClosePreview(preview);
          if (preview.active < 1) {
            setFullCloseMode("idle");
            setFullCloseSuccess(true);
            window.setTimeout(() => window.location.reload(), 1200);
            return;
          }
          if (fullCloseResult) fullCloseRequestKey.current = "";
          setFullCloseResult(null);
          setFullCloseError("");
          setFullCloseMode("confirm");
        } catch (reason) {
          setFullCloseError(reason instanceof Error ? reason.message : "Actuele Aster-posities konden niet worden opgehaald.");
          setFullCloseMode("error");
        }
      };
    ''').rstrip()
    text = text[:match.start()] + handlers + text[match.end():]

    tail_pattern = re.compile(r'  return host \? createPortal\(\n    <Snapshot[\s\S]*?\n  \) : null;\n\}')
    match = tail_pattern.search(text)
    if not match:
        raise RuntimeError("missing anchor: enhancer return")
    tail = dedent('''
      return host ? <>
        {createPortal(
          <Snapshot
            values={values}
            profitPreview={profitPreview}
            profitBusy={profitBusy}
            fullCloseBusy={fullCloseMode === "closing"}
            onCloseAll={openFullCloseConfirm}
            onCloseProfit={closeProfit}
          />,
          host,
        )}
        {fullCloseMode !== "idle" && typeof document !== "undefined" && createPortal(
          <FullCloseOverlay
            mode={fullCloseMode}
            preview={fullClosePreview}
            result={fullCloseResult}
            error={fullCloseError}
            onCancel={() => { if (fullCloseMode !== "closing") setFullCloseMode("idle"); }}
            onConfirm={executeFullClose}
            onRetry={retryFullClose}
          />,
          document.body,
        )}
        {fullCloseSuccess && typeof document !== "undefined" && createPortal(
          <div className="aps-full-close-success" role="status" data-reference={FULL_CLOSE_REFERENCE}>
            <span aria-hidden="true">✓</span>
            <strong>Alle actieve posities zijn gesloten</strong>
            <button type="button" aria-label="Melding sluiten" onClick={() => setFullCloseSuccess(false)}>×</button>
          </div>,
          document.body,
        )}
      </> : null;
    }''').rstrip()
    text = text[:match.start()] + tail + text[match.end():]
    path.write_text(text)


def write_proxy() -> None:
    path = Path("web/app/api/exchanges/aster/positions/close-all/route.ts")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent('''
    import { proxyCloud } from "@/lib/cloud-proxy";

    export async function POST(request: Request) {
      return proxyCloud(request, "/v1/me/aster/positions/close-all", "POST");
    }
    ''').lstrip())


def patch_css() -> None:
    path = Path("web/app/portfolio-snapshot.css")
    text = path.read_text()
    if ".aps-full-close-backdrop" in text:
        return
    text += dedent('''

    /* Approved Alles sluiten flow — reference file_00000000b4bc8210aa8f4c8e32f5e7dd. */
    .aps-close-all:not(:disabled){border-color:rgba(255,73,87,.82)!important;color:#ff8994!important;background:linear-gradient(180deg,rgba(92,16,24,.46),rgba(34,8,12,.58))!important;box-shadow:0 0 0 1px rgba(255,68,82,.12),0 0 22px rgba(255,48,64,.18)!important}
    .aps-full-close-backdrop{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;padding:max(20px,env(safe-area-inset-top)) 18px max(28px,env(safe-area-inset-bottom));background:rgba(0,4,10,.76);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
    .aps-full-close-modal{position:relative;width:min(440px,100%);max-height:calc(100dvh - 48px);overflow:auto;padding:30px 28px 25px;border:1px solid rgba(83,112,141,.48);border-radius:25px;background:radial-gradient(circle at 50% 0,rgba(18,35,49,.34),transparent 42%),linear-gradient(160deg,#07111b 0%,#030912 72%,#07111b 100%);box-shadow:0 26px 90px rgba(0,0,0,.66),inset 0 1px rgba(255,255,255,.035);color:#f5f8fb;text-align:center}
    .aps-full-close-x{position:absolute;top:16px;right:18px;border:0;background:transparent;color:#9daab9;font-size:31px;line-height:1;cursor:pointer;padding:2px 5px}.aps-full-close-x:disabled{opacity:.38;cursor:default}
    .aps-full-close-warning{width:70px;height:70px;margin:0 auto 18px;border:6px solid #ff525c;border-radius:50%;display:grid;place-items:center;color:#ff525c;font-size:46px;font-weight:800;line-height:1;box-shadow:0 0 28px rgba(255,62,75,.14)}
    .aps-full-close-modal h3{margin:0 0 17px;color:#fff;font-size:26px;line-height:1.1;font-weight:850;letter-spacing:-.03em}.aps-full-close-question{margin:0 auto 11px;max-width:340px;color:#e2e7ee;font-size:18px;line-height:1.42;font-weight:650}.aps-full-close-sub{margin:0 auto 21px;max-width:350px;color:#aab4c2;font-size:15px;line-height:1.5}
    .aps-full-close-counts{margin:20px 0 22px;padding:15px 17px;border:1px solid rgba(93,119,147,.38);border-radius:14px;background:rgba(7,16,27,.58);box-shadow:inset 0 1px rgba(255,255,255,.025)}.aps-full-close-counts>div{display:flex;justify-content:space-between;align-items:center;gap:18px;padding:4px 0}.aps-full-close-counts dt{color:#bac3ce;font-size:15px}.aps-full-close-counts dd{margin:0;color:#fff;font-size:17px;font-weight:750}
    .aps-full-close-actions{display:grid;grid-template-columns:1fr 1fr;gap:14px}.aps-full-close-actions button{min-height:56px;border:1px solid rgba(96,119,144,.56);border-radius:14px;background:linear-gradient(180deg,#17212d,#0c141e);color:#fff;font-size:16px;font-weight:800;box-shadow:inset 0 1px rgba(255,255,255,.04);cursor:pointer}.aps-full-close-actions .aps-full-close-danger{border-color:#ff7b82;background:linear-gradient(180deg,#e73d45,#c5222d);box-shadow:0 0 24px rgba(255,49,61,.25),inset 0 1px rgba(255,255,255,.18)}
    .aps-full-close-spinner{width:88px;height:88px;margin:8px auto 24px;padding:7px;border-radius:50%;background:conic-gradient(#65efb5 0 30%,rgba(101,239,181,.28) 46%,rgba(101,239,181,.06) 68%,#65efb5 100%);animation:aps-full-close-spin 1.1s linear infinite}.aps-full-close-spinner i{display:block;width:100%;height:100%;border-radius:50%;background:#07111b}
    .aps-full-close-progress{position:relative;height:18px;margin:25px 0 13px;overflow:hidden;border:1px solid rgba(72,180,139,.25);border-radius:999px;background:rgba(45,103,83,.26)}.aps-full-close-progress i{position:absolute;inset:0 auto 0 -35%;width:55%;border-radius:inherit;background:linear-gradient(90deg,rgba(35,232,157,.18),#27dfa0,rgba(70,255,191,.6));animation:aps-full-close-progress 1.25s ease-in-out infinite}.aps-full-close-progress-label{display:block;color:#74e8bd;font-size:14px;font-weight:800}.aps-full-close-info{margin-top:25px;padding:15px 17px;border:1px solid rgba(87,115,146,.34);border-radius:14px;background:rgba(15,27,42,.7);color:#aeb9c7;font-size:13px;line-height:1.48;text-align:left}
    .aps-full-close-success{position:fixed;z-index:2147483001;top:max(88px,calc(env(safe-area-inset-top) + 70px));left:50%;transform:translateX(-50%);width:min(400px,calc(100vw - 32px));display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;padding:15px 17px;border:1px solid rgba(27,232,143,.68);border-radius:15px;background:linear-gradient(135deg,rgba(4,71,46,.97),rgba(4,40,30,.98));box-shadow:0 16px 50px rgba(0,0,0,.5),0 0 24px rgba(20,229,137,.12);color:#fff}.aps-full-close-success>span{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:#32e89c;color:#05291d;font-size:22px;font-weight:900}.aps-full-close-success strong{font-size:14px;line-height:1.25}.aps-full-close-success button{border:0;background:transparent;color:#9fd7c0;font-size:24px;cursor:pointer}
    @keyframes aps-full-close-spin{to{transform:rotate(360deg)}}@keyframes aps-full-close-progress{0%{left:-35%}50%{left:80%}100%{left:135%}}
    @media(max-width:480px){.aps-full-close-backdrop{padding-left:15px;padding-right:15px}.aps-full-close-modal{padding:27px 20px 21px;border-radius:22px}.aps-full-close-warning{width:62px;height:62px;border-width:5px;font-size:40px}.aps-full-close-modal h3{font-size:24px}.aps-full-close-question{font-size:17px}.aps-full-close-actions{gap:10px}.aps-full-close-actions button{min-height:53px;font-size:15px}}
    ''')
    path.write_text(text)


def write_tests() -> None:
    Path("cloud_api/test_aster_full_close_contract.py").write_text(dedent('''
    from pathlib import Path

    def route_source() -> str:
        source = Path(__file__).with_name("main.py").read_text()
        start = source.index('@app.post("/v1/me/aster/positions/close-all")')
        end = source.index('@app.get("/v1/me/aster/positions/profitable-close-preview")')
        return source[start:end]

    def test_full_close_is_explicit_uid_scoped_idempotent_and_profit_independent():
        route = route_source()
        assert "if not request.confirm" in route
        assert 'uid = str(user["uid"])' in route
        assert "asterFullCloseIntents" in route
        assert "action_ref.create" in route
        assert "AlreadyExists" in route
        assert "closeEnabled" not in route
        assert "MINIMUM_PROFIT_USD" not in route

    def test_full_close_pauses_reentry_and_uses_fresh_exchange_truth_per_leg():
        route = route_source()
        assert '"enabled": False' in route
        assert '"pendingReopens": []' in route
        assert "closeLock" in route
        assert route.count("client.position_risk()") >= 4
        assert 'side=PositionSide(side)' in route
        assert 'action="CLOSE"' in route
        assert "manual_loss_confirmation=True" in route

    def test_full_close_reports_exchange_confirmed_final_state_and_partial_failures():
        route = route_source()
        assert '"closedCount": closed_count' in route
        assert '"remainingCount": len(final_positions)' in route
        assert '"complete": complete' in route
        assert '"PARTIAL_FAIL_CLOSED"' in route
        assert "remaining_orders" in route
    ''').lstrip())

    Path("web/tests/aster-full-close-flow.test.mjs").write_text(dedent(f'''
    import test from "node:test";
    import assert from "node:assert/strict";
    import {{ readFile }} from "node:fs/promises";

    test("Snapshot Alles sluiten follows approved modal reference and dedicated route", async () => {{
      const [component, css, route] = await Promise.all([
        readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
        readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
        readFile(new URL("../app/api/exchanges/aster/positions/close-all/route.ts", import.meta.url), "utf8"),
      ]);
      assert.match(component, /{REFERENCE_ID}/);
      assert.match(component, /Weet je zeker dat je alle actieve posities wilt sluiten\\?/);
      assert.match(component, /Dit sluit alle open LONG- en SHORT-posities, ongeacht winst of verlies\\./);
      assert.match(component, /Bezig met sluiten\\.\\.\\./);
      assert.match(component, /Alle actieve posities zijn gesloten/);
      assert.match(component, /loadFullClosePreview/);
      assert.match(component, /\\/api\\/exchanges\\/aster\\/positions\\/close-all/);
      assert.doesNotMatch(component, /legacy\\.click\\(\\)/);
      assert.match(route, /\\/v1\\/me\\/aster\\/positions\\/close-all/);
      assert.match(css, /\\.aps-full-close-backdrop/);
      assert.match(css, /\\.aps-full-close-modal/);
      assert.match(css, /\\.aps-full-close-progress/);
      assert.match(css, /\\.aps-full-close-success/);
    }});

    test("existing profit close stays independent", async () => {{
      const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
      for (const value of ["Close Long", "Close Short", "Close All", "profitable-close-preview", "close-profitable"]) assert.match(component, new RegExp(value));
      assert.match(component, /minimumProfitUsd/);
    }});
    ''').lstrip())

    path = Path("web/tests/aster-compact-portfolio-snapshot.test.mjs")
    text = path.read_text()
    text = text.replace('  assert.match(component, /portfolio-close-all/);\n  assert.match(component, /legacy\\.click\\(\\)/);', f'  assert.match(component, /{REFERENCE_ID}/);\n  assert.match(component, /positions\\/close-all/);\n  assert.doesNotMatch(component, /legacy\\.click\\(\\)/);')
    path.write_text(text)


def write_backend_deploy_workflow() -> None:
    path = Path(".github/workflows/deploy-v46-full-close-backend.yml")
    path.write_text(dedent('''
    name: Deploy V46 Full Close Backend

    on:
      push:
        branches:
          - amar-crypto-bot-2026-cloud
        paths:
          - "cloud_api/main.py"
          - "cloud_api/test_aster_full_close_contract.py"
          - ".github/workflows/deploy-v46-full-close-backend.yml"

    permissions:
      contents: read
      id-token: write

    concurrency:
      group: tradementor-production-backend
      cancel-in-progress: false

    env:
      GCP_PROJECT_ID: tradementor-production
      GCP_REGION: europe-west4
      ARTIFACT_REPOSITORY: tradementor
      CLOUD_RUN_SERVICE: tradementor-api
      WIF_PROVIDER: projects/604335232956/locations/global/workloadIdentityPools/github/providers/tradementor-production
      DEPLOY_SERVICE_ACCOUNT: github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com

    jobs:
      verify-deploy:
        runs-on: ubuntu-latest
        environment: production
        timeout-minutes: 35
        steps:
          - uses: actions/checkout@v4
            with:
              ref: amar-crypto-bot-2026-cloud
          - uses: actions/setup-python@v5
            with:
              python-version: '3.12'
          - name: Backend regression
            run: |
              pip install -r cloud_api/requirements.txt pytest
              python -m py_compile cloud_api/main.py
              cd cloud_api
              pytest -q test_aster_full_close_contract.py test_aster_manual_close_contract.py test_aster_profit_close_contract.py test_aster_close_guard.py
          - name: Authenticate Google Cloud
            uses: google-github-actions/auth@v2
            with:
              workload_identity_provider: ${{ env.WIF_PROVIDER }}
              service_account: ${{ env.DEPLOY_SERVICE_ACCOUNT }}
          - uses: google-github-actions/setup-gcloud@v2
          - name: Build and push candidate
            shell: bash
            run: |
              set -euo pipefail
              gcloud auth configure-docker "$GCP_REGION-docker.pkg.dev" --quiet
              IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REPOSITORY/tradementor-api:full-close-$GITHUB_RUN_ID"
              docker build -t "$IMAGE" cloud_api
              docker push "$IMAGE"
              echo "IMAGE=$IMAGE" >> "$GITHUB_ENV"
          - name: Deploy candidate without traffic
            shell: bash
            run: |
              set -euo pipefail
              REV="fullclose-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
              TAG="fullclose-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
              gcloud run services update "$CLOUD_RUN_SERVICE" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --image "$IMAGE" --revision-suffix "$REV" --no-traffic --tag "$TAG"
              SERVICE_JSON="$(gcloud run services describe "$CLOUD_RUN_SERVICE" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json)"
              CANDIDATE_URL="$(printf '%s' "$SERVICE_JSON" | python -c 'import json,sys; d=json.load(sys.stdin); tag=sys.argv[1]; print(next(x["url"] for x in d["status"]["traffic"] if x.get("tag")==tag))' "$TAG")"
              CANDIDATE_REVISION="$(printf '%s' "$SERVICE_JSON" | python -c 'import json,sys; d=json.load(sys.stdin); tag=sys.argv[1]; print(next(x["revisionName"] for x in d["status"]["traffic"] if x.get("tag")==tag))' "$TAG")"
              echo "CANDIDATE_URL=$CANDIDATE_URL" >> "$GITHUB_ENV"
              echo "CANDIDATE_REVISION=$CANDIDATE_REVISION" >> "$GITHUB_ENV"
          - name: Verify candidate
            shell: bash
            run: |
              set -euo pipefail
              HEALTH="$(curl --fail --silent --show-error --retry 6 --retry-delay 5 "$CANDIDATE_URL/health")"
              python - "$HEALTH" <<'PY'
              import json,sys
              value=json.loads(sys.argv[1])
              assert value.get('status') == 'ready'
              assert value.get('multiUser') is True
              PY
          - name: Promote verified backend
            shell: bash
            run: |
              set -euo pipefail
              gcloud run services update-traffic "$CLOUD_RUN_SERVICE" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --to-revisions "$CANDIDATE_REVISION=100"
              SERVICE_URL="$(gcloud run services describe "$CLOUD_RUN_SERVICE" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format='value(status.url)')"
              curl --fail --silent --show-error --retry 6 --retry-delay 5 "$SERVICE_URL/health" >/dev/null
    ''').lstrip())


if __name__ == "__main__":
    patch_backend()
    patch_frontend()
    write_proxy()
    patch_css()
    write_tests()
    write_backend_deploy_workflow()
