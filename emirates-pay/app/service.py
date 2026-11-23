"""Business logic: users, wallets, top-ups, transfers, double-entry ledger.

Every money movement runs inside BEGIN IMMEDIATE so concurrent requests are
serialised by the database and a balance can never go negative.
"""
import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone

from . import money


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ref():
    return "TXN-" + secrets.token_hex(6).upper()


def _rollback(db):
    if db.in_transaction:
        db.execute("ROLLBACK")


def _ledger(db, txn_id, entries):
    for account, debit, credit in entries:
        db.execute(
            "INSERT INTO ledger_entries(txn_id, account, debit_fils, credit_fils) VALUES (?,?,?,?)",
            (txn_id, account, debit, credit),
        )


# ---------- users / wallets ----------

def login_or_register(db, email, name):
    db.execute("BEGIN IMMEDIATE")
    try:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user is None:
            cur = db.execute(
                "INSERT INTO users(email, name, created_at) VALUES (?,?,?)", (email, name, _now())
            )
            uid = cur.lastrowid
            for _ in range(10):
                wallet_no = "EP" + "".join(str(secrets.randbelow(10)) for _ in range(10))
                try:
                    db.execute(
                        "INSERT INTO wallets(wallet_no, user_id, created_at) VALUES (?,?,?)",
                        (wallet_no, uid, _now()),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError("could not allocate a wallet number")
        else:
            uid = user["id"]
        db.execute("COMMIT")
    except BaseException:
        _rollback(db)
        raise
    return get_wallet_by_user(db, uid)


def get_wallet_by_user(db, user_id):
    return db.execute(
        "SELECT w.id, w.wallet_no, w.balance_fils, u.id AS user_id, u.name, u.email "
        "FROM wallets w JOIN users u ON u.id = w.user_id WHERE u.id=?",
        (user_id,),
    ).fetchone()


# ---------- top-up ----------

def topup(db, wallet_id, amount):
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE wallets SET balance_fils = balance_fils + ? WHERE id=?", (amount, wallet_id))
        cur = db.execute(
            "INSERT INTO transactions(txn_ref, type, from_wallet_id, to_wallet_id, amount_fils, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (_ref(), "topup", None, wallet_id, amount, _now()),
        )
        txn_id = cur.lastrowid
        _ledger(db, txn_id, [("external:funding", amount, 0), (f"wallet:{wallet_id}", 0, amount)])
        db.execute("COMMIT")
    except BaseException:
        _rollback(db)
        raise
    return txn_id


# ---------- transfer ----------

def transfer(db, sender_id, to_wallet_no, amount, note, idem_key):
    """Returns (txn_id, replayed)."""
    req_hash = hashlib.sha256(f"{to_wallet_no}|{amount}|{note or ''}".encode()).hexdigest()
    fee, vat = money.fee_and_vat(amount)
    total = amount + fee + vat

    db.execute("BEGIN IMMEDIATE")
    try:
        if idem_key:
            prev = db.execute(
                "SELECT id, request_hash FROM transactions WHERE from_wallet_id=? AND idempotency_key=?",
                (sender_id, idem_key),
            ).fetchone()
            if prev:
                if prev["request_hash"] != req_hash:
                    raise ApiError(
                        "idempotency_conflict",
                        "This Idempotency-Key was already used with a different request.",
                        422,
                    )
                db.execute("COMMIT")
                return prev["id"], True

        recv = db.execute("SELECT id FROM wallets WHERE wallet_no=?", (to_wallet_no,)).fetchone()
        if recv is None:
            raise ApiError("wallet_not_found", "Recipient wallet not found.", 404)
        if recv["id"] == sender_id:
            raise ApiError("same_wallet", "You cannot transfer to your own wallet.", 422)

        balance = db.execute("SELECT balance_fils FROM wallets WHERE id=?", (sender_id,)).fetchone()[0]
        if balance < total:
            raise ApiError(
                "insufficient_funds",
                f"Balance AED {money.fmt_aed(balance)} is below the AED {money.fmt_aed(total)} required.",
                422,
            )

        db.execute("UPDATE wallets SET balance_fils = balance_fils - ? WHERE id=?", (total, sender_id))
        db.execute("UPDATE wallets SET balance_fils = balance_fils + ? WHERE id=?", (amount, recv["id"]))
        cur = db.execute(
            "INSERT INTO transactions(txn_ref, type, from_wallet_id, to_wallet_id, amount_fils, fee_fils, "
            "vat_fils, note, idempotency_key, request_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_ref(), "transfer", sender_id, recv["id"], amount, fee, vat, note, idem_key, req_hash, _now()),
        )
        txn_id = cur.lastrowid
        _ledger(db, txn_id, [
            (f"wallet:{sender_id}", total, 0),      # sender pays amount + fee + VAT
            (f"wallet:{recv['id']}", 0, amount),    # recipient receives amount
            ("revenue:fees", 0, fee),               # platform fee income
            ("liability:vat", 0, vat),              # VAT owed to the FTA
        ])
        db.execute("COMMIT")
    except BaseException:
        _rollback(db)
        raise
    return txn_id, False


# ---------- reads ----------

_TXN_SELECT = (
    "SELECT t.*, fw.wallet_no AS from_no, tw.wallet_no AS to_no FROM transactions t "
    "LEFT JOIN wallets fw ON fw.id = t.from_wallet_id JOIN wallets tw ON tw.id = t.to_wallet_id "
)


def get_txn(db, txn_id):
    return db.execute(_TXN_SELECT + "WHERE t.id=?", (txn_id,)).fetchone()


def list_txns(db, wallet_id, limit=50):
    return db.execute(
        _TXN_SELECT + "WHERE t.from_wallet_id=? OR t.to_wallet_id=? ORDER BY t.id DESC LIMIT ?",
        (wallet_id, wallet_id, limit),
    ).fetchall()


def txn_view(r, my_wallet_id):
    if r["type"] == "topup":
        direction, counterparty = "topup", None
    elif r["from_wallet_id"] == my_wallet_id:
        direction, counterparty = "out", r["to_no"]
    else:
        direction, counterparty = "in", r["from_no"]
    fee = r["fee_fils"] if direction == "out" else 0
    vat = r["vat_fils"] if direction == "out" else 0
    return {
        "ref": r["txn_ref"],
        "type": r["type"],
        "direction": direction,
        "counterparty": counterparty,
        "amount": money.fmt_aed(r["amount_fils"]),
        "fee": money.fmt_aed(fee),
        "vat": money.fmt_aed(vat),
        "total": money.fmt_aed(r["amount_fils"] + fee + vat),
        "currency": "AED",
        "note": r["note"],
        "created_at": r["created_at"],
    }
