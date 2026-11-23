import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wallets (
  id INTEGER PRIMARY KEY,
  wallet_no TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  balance_fils INTEGER NOT NULL DEFAULT 0 CHECK (balance_fils >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY,
  txn_ref TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL CHECK (type IN ('topup','transfer')),
  from_wallet_id INTEGER REFERENCES wallets(id),
  to_wallet_id INTEGER NOT NULL REFERENCES wallets(id),
  amount_fils INTEGER NOT NULL CHECK (amount_fils > 0),
  fee_fils INTEGER NOT NULL DEFAULT 0,
  vat_fils INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  idempotency_key TEXT,
  request_hash TEXT,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_txn_idem
  ON transactions(from_wallet_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS ledger_entries (
  id INTEGER PRIMARY KEY,
  txn_id INTEGER NOT NULL REFERENCES transactions(id),
  account TEXT NOT NULL,
  debit_fils INTEGER NOT NULL DEFAULT 0,
  credit_fils INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path):
    # isolation_level=None -> we control transactions explicitly (BEGIN IMMEDIATE).
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.close()
