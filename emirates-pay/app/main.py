"""Emirates Pay - demo wallet API (Flask)."""
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException

from . import db as dbmod
from . import money, service
from .metrics import Metrics
from .service import ApiError

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}$")
WALLET_RE = re.compile(r"^EP\d{10}$")
QUIET_PATHS = {"/health", "/ready", "/metrics"}   # kept out of logs and SLI metrics


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def load_config(overrides=None):
    env = os.environ.get
    cfg = {
        "APP_ENV": env("APP_ENV", "development"),
        "SECRET_KEY": env("SECRET_KEY"),
        "DB_PATH": env("DB_PATH", "data/emirates_pay.db"),
        "APP_VERSION": env("APP_VERSION", "dev"),
        "GIT_SHA": env("GIT_SHA", "local"),
        "LOG_LEVEL": env("LOG_LEVEL", "INFO"),
        "FAULT_RATE": float(env("FAULT_RATE", "0")),            # 0..1 share of /api calls returning 500
        "FAULT_LATENCY_MS": int(env("FAULT_LATENCY_MS", "0")),  # artificial delay on /api calls
        "TOKEN_TTL_SECONDS": int(env("TOKEN_TTL_SECONDS", str(8 * 3600))),
    }
    cfg.update(overrides or {})
    if not cfg["SECRET_KEY"]:
        if cfg["APP_ENV"] == "production":
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
        cfg["SECRET_KEY"] = "dev-only-insecure-key"
    return cfg


def create_app(overrides=None):
    cfg = load_config(overrides)
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(cfg)
    app.json.sort_keys = False

    log = logging.getLogger("emirates_pay")
    log.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(cfg["LOG_LEVEL"])
    log.propagate = False

    dbmod.init_db(cfg["DB_PATH"])
    metrics = Metrics(cfg["APP_VERSION"], cfg["GIT_SHA"])
    signer = URLSafeTimedSerializer(cfg["SECRET_KEY"], salt="emirates-pay-auth")

    # ---------- per-request plumbing ----------

    def get_db():
        if "db" not in g:
            g.db = dbmod.connect(cfg["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def start_request():
        g.start = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        # Failure injection for demos: canary auto-rollback, alerting, SLO burn.
        if request.path.startswith("/api/") and request.path != "/api/version":
            if cfg["FAULT_LATENCY_MS"] > 0:
                time.sleep(cfg["FAULT_LATENCY_MS"] / 1000)
            if cfg["FAULT_RATE"] > 0 and random.random() < cfg["FAULT_RATE"]:
                return error_response("injected_fault", "Injected failure (FAULT_RATE).", 500)

    @app.after_request
    def finish_request(resp):
        elapsed = time.perf_counter() - g.get("start", time.perf_counter())
        resp.headers["X-Request-ID"] = g.get("request_id", "")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        if request.path not in QUIET_PATHS:
            route = request.url_rule.rule if request.url_rule else "unmatched"
            metrics.observe_request(request.method, route, resp.status_code, elapsed)
            log.info("request", extra={"fields": {
                "request_id": g.get("request_id"), "method": request.method, "path": request.path,
                "status": resp.status_code, "duration_ms": round(elapsed * 1000, 1),
            }})
        return resp

    # ---------- errors ----------

    def error_response(code, message, status):
        return jsonify({"error": {"code": code, "message": message}}), status

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.code, e.message, e.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        return error_response(e.name.lower().replace(" ", "_"), e.description, e.code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        log.exception("unhandled error", extra={"fields": {"request_id": g.get("request_id")}})
        return error_response("internal_error", "Something went wrong. Please try again.", 500)

    # ---------- helpers ----------

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError("invalid_input", "Request body must be a JSON object.", 400)
        return data

    def parse_money(value, limit):
        try:
            return money.parse_amount(value, limit)
        except money.AmountError as exc:
            code = "limit_exceeded" if "exceeds" in str(exc) else "invalid_amount"
            raise ApiError(code, str(exc), 422)

    def require_auth(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise ApiError("unauthorized", "Missing bearer token.", 401)
            try:
                data = signer.loads(header[7:], max_age=cfg["TOKEN_TTL_SECONDS"])
            except BadSignature:
                raise ApiError("unauthorized", "Invalid or expired token.", 401)
            wallet = service.get_wallet_by_user(get_db(), data.get("uid"))
            if wallet is None:
                raise ApiError("unauthorized", "Unknown user.", 401)
            g.wallet = wallet
            return fn(*args, **kwargs)
        return wrapper

    def wallet_json(w):
        return {"wallet_no": w["wallet_no"], "balance": money.fmt_aed(w["balance_fils"]), "currency": "AED"}

    # ---------- platform endpoints ----------

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            get_db().execute("SELECT 1").fetchone()
        except Exception:
            return {"status": "not_ready"}, 503
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics_endpoint():
        return metrics.render(), 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ---------- API ----------

    @app.get("/api/version")
    def version():
        return {
            "version": cfg["APP_VERSION"], "git_sha": cfg["GIT_SHA"], "env": cfg["APP_ENV"],
            "fault_injection": cfg["FAULT_RATE"] > 0 or cfg["FAULT_LATENCY_MS"] > 0,
        }

    @app.post("/api/auth/uaepass-mock")
    def uaepass_mock():
        """Stand-in for a UAE Pass style login. No real identity verification."""
        data = body()
        email = str(data.get("email", "")).strip().lower()
        name = str(data.get("name", "")).strip()
        if not EMAIL_RE.match(email):
            raise ApiError("invalid_input", "A valid email is required.", 422)
        if not 1 <= len(name) <= 80:
            raise ApiError("invalid_input", "Name must be 1 to 80 characters.", 422)
        w = service.login_or_register(get_db(), email, name)
        token = signer.dumps({"uid": w["user_id"]})
        return {"token": token, "user": {"name": w["name"], "email": w["email"]}, "wallet": wallet_json(w)}

    @app.get("/api/me")
    @require_auth
    def me():
        w = g.wallet
        return {"user": {"name": w["name"], "email": w["email"]}, "wallet": wallet_json(w)}

    @app.get("/api/quote")
    def quote():
        amount = parse_money(request.args.get("amount"), money.TRANSFER_MAX_FILS)
        fee, vat = money.fee_and_vat(amount)
        return {
            "amount": money.fmt_aed(amount), "fee": money.fmt_aed(fee), "vat": money.fmt_aed(vat),
            "total": money.fmt_aed(amount + fee + vat), "currency": "AED",
        }

    @app.post("/api/wallet/topup")
    @require_auth
    def wallet_topup():
        amount = parse_money(body().get("amount"), money.TOPUP_MAX_FILS)
        db = get_db()
        txn_id = service.topup(db, g.wallet["id"], amount)
        metrics.inc("wallet_topups_total")
        w = service.get_wallet_by_user(db, g.wallet["user_id"])
        view = service.txn_view(service.get_txn(db, txn_id), w["id"])
        return {"transaction": view, "wallet": wallet_json(w)}, 201

    @app.post("/api/transfer")
    @require_auth
    def transfer():
        data = body()
        to_no = str(data.get("to_wallet", "")).strip().upper()
        if not WALLET_RE.match(to_no):
            raise ApiError("invalid_input", "Recipient wallet number looks like EP0000000000.", 422)
        note = data.get("note")
        if note is not None:
            note = str(note).strip()[:140] or None
        amount = parse_money(data.get("amount"), money.TRANSFER_MAX_FILS)
        idem = request.headers.get("Idempotency-Key")
        if idem is not None and not 8 <= len(idem) <= 80:
            raise ApiError("invalid_input", "Idempotency-Key must be 8 to 80 characters.", 422)

        db = get_db()
        try:
            txn_id, replayed = service.transfer(db, g.wallet["id"], to_no, amount, note, idem)
        except ApiError as e:
            metrics.inc("wallet_transfers_total", result=e.code)
            raise
        metrics.inc("wallet_transfers_total", result="replayed" if replayed else "success")
        w = service.get_wallet_by_user(db, g.wallet["user_id"])
        view = service.txn_view(service.get_txn(db, txn_id), w["id"])
        return {"transaction": view, "wallet": wallet_json(w), "replayed": replayed}, (200 if replayed else 201)

    @app.get("/api/transactions")
    @require_auth
    def transactions():
        rows = service.list_txns(get_db(), g.wallet["id"])
        return {"transactions": [service.txn_view(r, g.wallet["id"]) for r in rows]}

    return app
