import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

from app import money
from app.main import create_app


class Base(unittest.TestCase):
    overrides = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        cfg = {"DB_PATH": self.db_path, "SECRET_KEY": "test-secret", "LOG_LEVEL": "CRITICAL"}
        cfg.update(self.overrides)
        self.app = create_app(cfg)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, email="a@example.ae", name="Aisha"):
        r = self.client.post("/api/auth/uaepass-mock", json={"email": email, "name": name})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        return {"Authorization": f"Bearer {d['token']}"}, d["wallet"]["wallet_no"]

    def fund(self, headers, amount):
        r = self.client.post("/api/wallet/topup", json={"amount": amount}, headers=headers)
        self.assertEqual(r.status_code, 201)

    def balance(self, headers):
        return self.client.get("/api/me", headers=headers).get_json()["wallet"]["balance"]

    def send(self, headers, to, amount, key=None, **extra):
        h = dict(headers)
        if key:
            h["Idempotency-Key"] = key
        return self.client.post("/api/transfer", json={"to_wallet": to, "amount": amount, **extra}, headers=h)


class MoneyTests(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(money.parse_amount("10.50", 10**9), 1050)
        self.assertEqual(money.parse_amount(10, 10**9), 1000)
        self.assertEqual(money.parse_amount(0.1, 10**9), 10)

    def test_parse_invalid(self):
        for bad in [0, -5, "abc", "1.234", None, True, "NaN", "Infinity", ""]:
            with self.assertRaises(money.AmountError, msg=repr(bad)):
                money.parse_amount(bad, 10**9)

    def test_limit(self):
        with self.assertRaises(money.AmountError):
            money.parse_amount("20000.01", money.TRANSFER_MAX_FILS)

    def test_fee_and_vat(self):
        self.assertEqual(money.fee_and_vat(10_000), (100, 5))          # AED 100 -> min fee 1.00, VAT 0.05
        self.assertEqual(money.fee_and_vat(1_000_000), (5000, 250))    # AED 10,000 -> fee 50.00, VAT 2.50
        self.assertEqual(money.fee_and_vat(100), (100, 5))             # tiny transfer still pays the minimum

    def test_format(self):
        self.assertEqual(money.fmt_aed(5), "0.05")
        self.assertEqual(money.fmt_aed(123456), "1234.56")


class PlatformTests(Base):
    def test_health_ready_version(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/ready").get_json()["status"], "ready")
        self.assertIn("version", self.client.get("/api/version").get_json())

    def test_security_headers_and_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_metrics_exposed(self):
        self.client.get("/api/version")
        text = self.client.get("/metrics").get_data(as_text=True)
        self.assertIn("http_requests_total", text)
        self.assertIn("http_request_duration_seconds_bucket", text)

    def test_unknown_route_is_json(self):
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "not_found")

    def test_production_requires_secret(self):
        with self.assertRaises(RuntimeError):
            create_app({"APP_ENV": "production", "SECRET_KEY": None, "DB_PATH": self.db_path})


class FaultInjectionTests(Base):
    overrides = {"FAULT_RATE": 1.0}

    def test_api_fails_but_probes_do_not(self):
        r = self.client.post("/api/auth/uaepass-mock", json={"email": "a@b.ae", "name": "A"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json()["error"]["code"], "injected_fault")
        self.assertEqual(self.client.get("/health").status_code, 200)
        v = self.client.get("/api/version").get_json()
        self.assertTrue(v["fault_injection"])


class AuthTests(Base):
    def test_login_creates_wallet_and_is_stable(self):
        _, w1 = self.login()
        _, w2 = self.login()
        self.assertEqual(w1, w2)
        self.assertRegex(w1, r"^EP\d{10}$")

    def test_validation(self):
        for payload in [{}, {"email": "bad", "name": "x"}, {"email": "a@b.ae", "name": ""}]:
            r = self.client.post("/api/auth/uaepass-mock", json=payload)
            self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/auth/uaepass-mock", data="not json", content_type="text/plain")
        self.assertEqual(r.status_code, 400)

    def test_protected_routes(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        bad = {"Authorization": "Bearer tampered.token.value"}
        self.assertEqual(self.client.get("/api/me", headers=bad).status_code, 401)

    def test_expired_token(self):
        app = create_app({"DB_PATH": self.db_path, "SECRET_KEY": "test-secret",
                          "LOG_LEVEL": "CRITICAL", "TOKEN_TTL_SECONDS": -1})
        c = app.test_client()
        tok = c.post("/api/auth/uaepass-mock", json={"email": "x@y.ae", "name": "X"}).get_json()["token"]
        self.assertEqual(c.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).status_code, 401)


class WalletTests(Base):
    def test_topup_and_limits(self):
        h, _ = self.login()
        self.fund(h, "250.75")
        self.assertEqual(self.balance(h), "250.75")
        r = self.client.post("/api/wallet/topup", json={"amount": "10000.01"}, headers=h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "limit_exceeded")

    def test_transfer_fee_and_vat(self):
        ha, _ = self.login("a@x.ae", "A")
        hb, wb = self.login("b@x.ae", "B")
        self.fund(ha, "500")
        r = self.send(ha, wb, "100.00", note="rent share")
        self.assertEqual(r.status_code, 201)
        t = r.get_json()["transaction"]
        self.assertEqual((t["amount"], t["fee"], t["vat"], t["total"]), ("100.00", "1.00", "0.05", "101.05"))
        self.assertEqual(self.balance(ha), "398.95")
        self.assertEqual(self.balance(hb), "100.00")
        # receiver does not see the sender's fees
        rec = self.client.get("/api/transactions", headers=hb).get_json()["transactions"][0]
        self.assertEqual((rec["direction"], rec["fee"], rec["total"]), ("in", "0.00", "100.00"))

    def test_insufficient_funds_when_fee_pushes_over(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "100")
        r = self.send(ha, wb, "100.00")          # needs 101.05
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "insufficient_funds")
        self.assertEqual(self.balance(ha), "100.00")

    def test_bad_recipients(self):
        ha, wa = self.login()
        self.fund(ha, "100")
        self.assertEqual(self.send(ha, wa, "5").get_json()["error"]["code"], "same_wallet")
        self.assertEqual(self.send(ha, "EP0000000000", "5").get_json()["error"]["code"], "wallet_not_found")
        self.assertEqual(self.send(ha, "bogus", "5").get_json()["error"]["code"], "invalid_input")

    def test_bad_amounts(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "100")
        for bad in ["0", "-5", "1.234", "abc", True, None]:
            r = self.send(ha, wb, bad)
            self.assertEqual(r.status_code, 422, repr(bad))

    def test_quote_matches_transfer(self):
        q = self.client.get("/api/quote?amount=10000").get_json()
        self.assertEqual((q["fee"], q["vat"], q["total"]), ("50.00", "2.50", "10052.50"))


class IdempotencyTests(Base):
    def test_replay_does_not_double_charge(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "500")
        first = self.send(ha, wb, "100", key="order-12345678")
        second = self.send(ha, wb, "100", key="order-12345678")
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertTrue(second.get_json()["replayed"])
        self.assertEqual(first.get_json()["transaction"]["ref"], second.get_json()["transaction"]["ref"])
        self.assertEqual(self.balance(ha), "398.95")

    def test_same_key_different_payload_rejected(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "500")
        self.send(ha, wb, "100", key="order-12345678")
        r = self.send(ha, wb, "200", key="order-12345678")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "idempotency_conflict")


class IntegrityTests(Base):
    def test_ledger_always_balances(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "1000")
        for amt in ["10", "99.99", "250.50", "3"]:
            self.assertEqual(self.send(ha, wb, amt).status_code, 201)
        conn = sqlite3.connect(self.db_path)
        debit, credit = conn.execute("SELECT SUM(debit_fils), SUM(credit_fils) FROM ledger_entries").fetchone()
        self.assertEqual(debit, credit)
        # wallet balances + fee revenue + VAT liability == everything ever funded
        wallets = conn.execute("SELECT SUM(balance_fils) FROM wallets").fetchone()[0]
        extras = conn.execute(
            "SELECT SUM(credit_fils) FROM ledger_entries WHERE account IN ('revenue:fees','liability:vat')"
        ).fetchone()[0]
        self.assertEqual(wallets + extras, 100_000)
        conn.close()

    def test_concurrent_transfers_never_overdraw(self):
        ha, _ = self.login("a@x.ae", "A")
        _, wb = self.login("b@x.ae", "B")
        self.fund(ha, "505.25")                       # enough for exactly five AED 100 transfers (5 x 101.05)
        results = []

        def worker():
            c = self.app.test_client()
            r = c.post("/api/transfer", json={"to_wallet": wb, "amount": "100"}, headers=ha)
            results.append(r.status_code)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(201), 5, results)
        self.assertEqual(results.count(422), 7, results)
        self.assertEqual(self.balance(ha), "0.00")


if __name__ == "__main__":
    unittest.main()
