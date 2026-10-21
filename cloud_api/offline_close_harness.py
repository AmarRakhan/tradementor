"""Offline harness for Close Profits 2.0: REAL source of the individual close route, the Auto Hedge manual-release
helpers, the account-lease functions, the Auto Hedge lock/dynamic-hedge guard modules and (optionally) the Auto
Hedge worker entry, executed against an in-memory Firestore model and a simulated Aster ledger.

Mocks: Firestore (in-memory model, serialisable transactions), Aster HTTP/order API (ledger). NOT mocked: the route,
manual-release helpers, lease functions, lock + dynamic-hedge guards, ContractRules, close_size. No network, no
credentials, no orders. This is a model-based test harness, not proof against real Firestore/Aster."""
from __future__ import annotations

import ast
import copy
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
MAIN_SRC = (HERE / "main.py").read_text()


class AlreadyExists(Exception):
    pass


def _merge(base, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)


class FakeFirestore:
    def __init__(self):
        self.docs: dict[tuple, dict] = {}
        self.mutex = threading.RLock()
        self.writes: list[tuple] = []

    def collection(self, name):
        return _Col(self, (name,))

    def transaction(self):
        return _Txn()


class _Col:
    def __init__(self, fs, path): self.fs, self.path = fs, path
    def document(self, doc_id): return _Doc(self.fs, self.path + (str(doc_id),))
    def add(self, data):
        doc = self.document(secrets.token_hex(8)); doc.set(data); return None, doc
    def where(self, field, op, value):
        assert op == "==", "model supports equality filters only"
        return _Query(self, [(field, value)])
    def stream(self): return _Query(self, []).stream()


class _Query:
    def __init__(self, col, filters): self.col, self.filters = col, filters
    def where(self, field, op, value):
        assert op == "==", "model supports equality filters only"
        return _Query(self.col, self.filters + [(field, value)])
    def stream(self):
        n = len(self.col.path)
        with self.col.fs.mutex:
            rows = [(path, data) for path, data in self.col.fs.docs.items()
                    if len(path) == n + 1 and path[:n] == self.col.path
                    and all(data.get(f) == v for f, v in self.filters)]
        return [_Snap(path[-1], data) for path, data in rows]


class _Snap:
    def __init__(self, doc_id, data): self.id, self._d = doc_id, data; self.exists = data is not None
    def to_dict(self): return copy.deepcopy(self._d) if self._d is not None else None


class _Doc:
    def __init__(self, fs, path): self.fs, self.path, self.id = fs, path, path[-1]
    def collection(self, name): return _Col(self.fs, self.path + (name,))
    def get(self, transaction=None):
        with self.fs.mutex:
            return _Snap(self.id, self.fs.docs.get(self.path))
    def set(self, data, merge=False):
        with self.fs.mutex:
            self.fs.writes.append((self.path, copy.deepcopy(data)))
            if merge and self.path in self.fs.docs:
                _merge(self.fs.docs[self.path], data)
            else:
                self.fs.docs[self.path] = copy.deepcopy(data)
    def delete(self):
        with self.fs.mutex:
            self.fs.docs.pop(self.path, None)
    def create(self, data):
        with self.fs.mutex:
            if self.path in self.fs.docs:
                raise AlreadyExists()
            self.set(data)


class _Txn:
    def set(self, ref, data, merge=False): ref.set(data, merge=merge)


class Ledger:
    """Simulated Aster account: Hedge Mode positions, MARKET closes, scriptable failure modes."""
    def __init__(self, fs):
        self.fs = fs
        self.pos = {}            # (symbol, side) -> qty
        self.mark = {}           # symbol -> price
        self.entry = {}          # (symbol, side) -> entry price
        self.min_qty = {}        # symbol -> minQty
        self.step = {}           # symbol -> step
        self.orders = []         # every order that REACHED the exchange: (symbol, side, qty, id_prefix)
        self.modes = {}          # symbol -> "ok" | "drop_after_accept" | "reject_before"
        self.on_before_order = None
        self.on_before_read = None
        self.order_log = {}      # client order id -> {"symbol","side","qty","executed","status"}  (REAL-leg mode)
        self.reflection_lag = {} # symbol -> number of position_risk() reads that still show the OLD size
        self._pending = []       # [(reads_left, symbol, side, new_qty)]
        self.partial_ratio = 0.4
        self.query_fails = set() # symbols for which the read-only order query errors

    def add(self, symbol, side, qty, mark=100.0, entry=None, minimum=0.001, step=0.001):
        self.pos[(symbol, side)] = float(qty); self.mark[symbol] = float(mark)
        self.entry[(symbol, side)] = entry if entry is not None else (mark + 5 if side == "SHORT" else mark - 5)
        self.min_qty[symbol] = minimum; self.step[symbol] = step

    def reduce(self, symbol, side, qty, lag=0):
        """Apply a fill to the exchange position; with lag>0 the position endpoint keeps showing the old size."""
        new_qty = max(0.0, self.pos[(symbol, side)] - qty)
        if lag:
            self._pending.append([lag, symbol, side, self.pos[(symbol, side)], new_qty])
        self.pos[(symbol, side)] = new_qty

    def rows(self):
        shown = dict(self.pos)
        still = []
        for item in self._pending:
            if item[0] > 0:
                shown[(item[1], item[2])] = item[3]          # lagging reflection: old size still visible
                item[0] -= 1
                still.append(item)
        self._pending = still
        out = []
        for (symbol, side), qty in shown.items():
            if qty <= 0:
                continue
            mark = self.mark[symbol]
            diff = (self.entry[(symbol, side)] - mark) if side == "SHORT" else (mark - self.entry[(symbol, side)])
            out.append({"symbol": symbol, "positionSide": side, "positionAmt": str(-qty if side == "SHORT" else qty),
                        "markPrice": str(mark), "leverage": "5", "unRealizedProfit": str(diff * qty)})
        return out

    def exchange_info(self):
        return {"symbols": [{"symbol": s, "status": "TRADING", "filters": [
            {"filterType": "LOT_SIZE", "minQty": str(self.min_qty[s]), "maxQty": "100000", "stepSize": str(self.step[s])},
            {"filterType": "MARKET_LOT_SIZE", "minQty": str(self.min_qty[s]), "maxQty": "100000", "stepSize": str(self.step[s])},
            {"filterType": "MIN_NOTIONAL", "notional": "5"}]} for s in self.mark]}


def build_backend(ledger: Ledger, fs, *, uid="u1", src: str | None = None, extra=(), real=None, real_leg=False):
    """`real=(firestore_module, google_exceptions_module)` binds the SAME route/lease/helper source to a real
    Firestore client `fs` (emulator) instead of the in-memory model."""
    """Returns (close_route, ns). `ns` exposes the lease + lock plumbing for worker-side models."""
    import aster_position_loss_auto_hedge_lock as lock
    from aster_dynamic_hedge_manual import begin_manual_action, complete_manual_action, fail_manual_action
    from aster_execution import PairExecutionPlan
    from aster_gateway import AsterValidationError, ContractRules, PositionSide
    from position_close import ALLOWED_CLOSE_PERCENTAGES, close_size

    wanted = {"close_one_aster_position", "_begin_position_loss_auto_hedge_manual_release",
              "_complete_position_loss_auto_hedge_manual_release", "_fail_position_loss_auto_hedge_manual_release",
              "_manual_auto_hedge_leg_view", "_position_loss_auto_hedge_pair_ref", "_position_loss_auto_hedge_pair",
              "user_reference", "aster_account_coordination_reference", "_acquire_aster_account_coordination",
              "_release_aster_account_coordination", "_renew_aster_account_coordination", "_open_pnl_check",
              "_enforce_min_open_pnl", "_refuse_if_recent_close_unconfirmed", "_series_guard_intents",
              "_clear_series_guard"}
    wanted = wanted | set(extra)
    tree = ast.parse(src if src is not None else MAIN_SRC)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") in ("_MANUAL_AUTO_HEDGE_RELEASE_STATUSES", "_BULK_UNCONFIRMED_CLOSE_WINDOW")
                      for t in n.targets)]
    assert len(nodes) == len(wanted) + 2, sorted(getattr(n, "name", "assign") for n in nodes)
    for n in nodes:
        if isinstance(n, ast.FunctionDef):
            n.decorator_list = []
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    clock = SimpleNamespace(offset=timedelta(0))          # advance to simulate slow exchange calls / lease expiry

    class _AnyDatetime(type):
        # Firestore returns its own datetime subclass: isinstance() in the route must accept every datetime.
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)

    class FakeDT(datetime, metaclass=_AnyDatetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime.now(tz) + clock.offset
            return cls(base.year, base.month, base.day, base.hour, base.minute, base.second, base.microsecond, base.tzinfo)

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail); self.status_code, self.detail = status_code, detail

    def safe_float(v, d=0.0):
        try: return float(v)
        except (TypeError, ValueError): return d

    class Client:
        def __init__(self, *, signer_address, sign_message, live_authorized, before_order_submit=None):
            self.hook = before_order_submit
        def position_risk(self):
            if ledger.on_before_read: ledger.on_before_read()
            return ledger.rows()
        def public_exchange_info(self): return ledger.exchange_info()
        # --- REAL-leg mode: the real aster_execution.execute_leg_once talks to these two methods ----------
        def submit_order_once(self, intent, *, config, confirm, hedge_mode_confirmed, risk_approved):
            from aster_gateway import AsterSubmissionUncertain
            sym, side_v, qty = intent.symbol, intent.position_side.value, float(intent.quantity)
            mode = ledger.modes.get(sym, "ok")
            if ledger.on_before_order:
                ledger.on_before_order(sym)
            if mode == "reject_before":
                raise RuntimeError("exchange rejected before accept")
            ledger.orders.append((sym, side_v, qty, intent.intent_id))
            lag = ledger.reflection_lag.get(sym, 0)
            if mode == "ack_new":                                 # acknowledged, not (yet) filled; stays NEW on every query
                ledger.order_log[intent.intent_id] = {"symbol": sym, "executed": 0.0, "status": "NEW"}
                return {"orderId": 1, "status": "NEW"}, False
            if mode == "ack_new_then_filled":                     # ack NEW, the confirmation query already sees FILLED
                ledger.reduce(sym, side_v, qty, lag)
                ledger.order_log[intent.intent_id] = {"symbol": sym, "executed": qty, "status": "FILLED"}
                return {"orderId": 1, "status": "NEW"}, False
            if mode == "partial_fill":
                done = qty * ledger.partial_ratio
                ledger.reduce(sym, side_v, done, lag)
                ledger.order_log[intent.intent_id] = {"symbol": sym, "executed": done, "status": "PARTIALLY_FILLED"}
                return {"orderId": 1, "status": "PARTIALLY_FILLED", "executedQty": str(done)}, False
            ledger.reduce(sym, side_v, qty, lag)
            ledger.order_log[intent.intent_id] = {"symbol": sym, "executed": qty, "status": "FILLED"}
            if mode == "drop_after_accept":
                raise ConnectionError("connection lost after Aster accepted the order")
            if mode == "timeout_after_accept":                    # read timeout; the gateway then does ONE read-only query
                if sym in ledger.query_fails:
                    raise AsterSubmissionUncertain("Aster-order blijft onzeker")
                return {"orderId": 1, "status": "FILLED"}, True
            if mode == "late_response":                           # the answer arrives very late (lease may have expired)
                clock.offset += timedelta(seconds=60)
            return {"orderId": 1, "status": "FILLED"}, False
        def query_order(self, symbol, intent_id):
            if symbol in ledger.query_fails:
                from aster_gateway import AsterApiError
                raise AsterApiError("query failed")
            row = ledger.order_log.get(intent_id)
            return {"orderId": 1, "status": row["status"] if row else "UNKNOWN"}

    def execute_aster_leg(client, plan, *, side, action, id_prefix, confirm, manual_loss_confirmation):
        sym, side_v = plan.symbol, side.value if hasattr(side, "value") else side
        mode = ledger.modes.get(sym, "ok")
        if client.hook:
            client.hook(SimpleNamespace(action=action, symbol=sym))
        if ledger.on_before_order:
            ledger.on_before_order(sym)
        if mode == "reject_before":
            raise RuntimeError("exchange rejected before accept")
        qty = float(plan.quantity)
        ledger.orders.append((sym, side_v, qty, id_prefix))
        ledger.pos[(sym, side_v)] = max(0.0, ledger.pos[(sym, side_v)] - qty)
        if mode == "drop_after_accept":
            raise ConnectionError("connection lost after Aster accepted the order")   # UNKNOWN to the caller
        return {"status": "FILLED"}

    if real_leg:
        from aster_execution import execute_leg_once
        execute_aster_leg = execute_leg_once  # noqa: F811  (REAL code path: no double POST, fill confirmation, fail-closed)
    ns = {
        "clock": clock,
        "db": fs, "firestore": real[0] if real else SimpleNamespace(transactional=lambda f: (lambda txn: _locked(fs, f, txn))),
        "datetime": FakeDT, "timezone": timezone, "timedelta": timedelta, "python_secrets": secrets,
        "hashlib": __import__("hashlib"), "os": SimpleNamespace(getenv=lambda *a, **k: "true"), "time": SimpleNamespace(sleep=lambda x: None),
        "HTTPException": HTTPException, "google_exceptions": real[1] if real else SimpleNamespace(AlreadyExists=AlreadyExists),
        "AutoHedgeCloseBlocked": lock.AutoHedgeCloseBlocked, "require_auto_hedge_close_allowed": lock.require_auto_hedge_close_allowed,
        "begin_manual_action": begin_manual_action, "complete_manual_action": complete_manual_action,
        "fail_manual_action": fail_manual_action, "PairExecutionPlan": PairExecutionPlan, "PositionSide": PositionSide,
        "AsterValidationError": AsterValidationError, "ContractRules": ContractRules, "Decimal": __import__("decimal").Decimal,
        "ALLOWED_CLOSE_PERCENTAGES": ALLOWED_CLOSE_PERCENTAGES, "close_size": close_size, "safe_float": safe_float,
        "AsterV3Client": Client, "load_aster_secret": lambda user: SimpleNamespace(signer_address="a"),
        "local_eip712_signer": lambda s: None, "_block_order_during_close_all": lambda u: (lambda intent: None),
        "execute_aster_leg": execute_aster_leg, "Any": object, "AsterManualCloseRequest": object,
        "Depends": lambda f: None, "authenticated_user": None,
        "_portfolio_growth_client": lambda user, live=False: Client(signer_address="a", sign_message=None, live_authorized=False),
    }
    exec(compile(module, "main.py::real", "exec"), ns)
    lock.configure_auto_hedge_lock_reader(lambda u, s: (ns["_position_loss_auto_hedge_pair"](u, s)))
    return ns["close_one_aster_position"], SimpleNamespace(**ns), HTTPException


def _locked(fs, fn, txn):
    with fs.mutex:
        return fn(txn)


def request(symbol_qty, *, percentage, key, side="SHORT", min_open_pnl_usd=None, bulk_series=False):
    return SimpleNamespace(confirm=True, side=side, expected_quantity=symbol_qty, percentage=percentage, idempotency_key=key,
                           min_open_pnl_usd=min_open_pnl_usd, bulk_series=bulk_series)
