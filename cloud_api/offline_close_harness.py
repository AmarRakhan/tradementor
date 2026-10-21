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

    def add(self, symbol, side, qty, mark=100.0, entry=None, minimum=0.001, step=0.001):
        self.pos[(symbol, side)] = float(qty); self.mark[symbol] = float(mark)
        self.entry[(symbol, side)] = entry if entry is not None else (mark + 5 if side == "SHORT" else mark - 5)
        self.min_qty[symbol] = minimum; self.step[symbol] = step

    def rows(self):
        out = []
        for (symbol, side), qty in self.pos.items():
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


def build_backend(ledger: Ledger, fs, *, uid="u1", src: str | None = None, extra=(), real=None):
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
              "_release_aster_account_coordination"}
    wanted = wanted | set(extra)
    tree = ast.parse(src if src is not None else MAIN_SRC)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") == "_MANUAL_AUTO_HEDGE_RELEASE_STATUSES" for t in n.targets)]
    assert len(nodes) == len(wanted) + 1, sorted(getattr(n, "name", "assign") for n in nodes)
    for n in nodes:
        if isinstance(n, ast.FunctionDef):
            n.decorator_list = []
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

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

    ns = {
        "db": fs, "firestore": real[0] if real else SimpleNamespace(transactional=lambda f: (lambda txn: _locked(fs, f, txn))),
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta, "python_secrets": secrets,
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


def request(symbol_qty, *, percentage, key, side="SHORT"):
    return SimpleNamespace(confirm=True, side=side, expected_quantity=symbol_qty, percentage=percentage, idempotency_key=key)
