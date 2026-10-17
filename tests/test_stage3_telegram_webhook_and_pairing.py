import unittest
import uuid
import hashlib
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.services.telegram_service import TelegramService
from app.services.transaction_service import TransactionService
from app.config import settings, get_wib_str

client = TestClient(app)

class TestStage3TelegramWebhookAndPairing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.user1_id = f"u1_{uuid.uuid4().hex[:8]}"
        self.user2_id = f"u2_{uuid.uuid4().hex[:8]}"
        now = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()

        # Seed profiles
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User 1', 'starter', 'user', ?)",
                       (self.user1_id, f"{self.user1_id}@test.id", now))
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User 2', 'starter', 'user', ?)",
                       (self.user2_id, f"{self.user2_id}@test.id", now))

        # Seed User 1 Wallet
        self.u1_wallet = f"w1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at) VALUES (?, ?, 'Cash U1', 'cash', 100000.0, 1, ?)",
                       (self.u1_wallet, self.user1_id, now))

        # Seed User 1 Category
        self.u1_cat_food = f"cat1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Makanan', 'expense', ?)",
                       (self.u1_cat_food, self.user1_id, now))

        conn.commit()
        conn.close()

    def test_webhook_secret_header_validation(self):
        """Memastikan endpoint webhook memvalidasi header X-Telegram-Bot-Api-Secret-Token"""
        payload = {"update_id": 999001, "message": {"text": "Halo"}}

        # 1. Tanpa header secret -> 401 Unauthorized
        res_no_header = client.post("/api/telegram/webhook", json=payload)
        self.assertEqual(res_no_header.status_code, 401)
        self.assertIn("Secret token webhook tidak valid", res_no_header.json()["detail"])

        # 2. Header secret salah -> 401 Unauthorized
        res_wrong_header = client.post(
            "/api/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret-palsu-hacker"}
        )
        self.assertEqual(res_wrong_header.status_code, 401)

        # 3. Header secret cocok -> 200 OK
        res_correct = client.post(
            "/api/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
        )
        self.assertEqual(res_correct.status_code, 200)

    def test_one_time_pairing_token_lifecycle(self):
        """Memastikan One-Time Pairing Token acak, ter-hash, single-use, dan kadaluwarsa"""
        # 1. Generate token untuk User 1
        token_info = TelegramService.generate_pairing_token(self.user1_id)
        raw_token = token_info["token"]
        self.assertTrue(raw_token.startswith("TD-"))
        self.assertEqual(token_info["expires_in_seconds"], 600)

        # 2. Verifikasi di database: token disimpan dalam bentuk HASH (SHA-256), bukan plaintext
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT token_hash, user_id FROM telegram_pair_tokens WHERE user_id = ?", (self.user1_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        self.assertEqual(row["token_hash"], expected_hash)
        self.assertNotIn(raw_token, row["token_hash"]) # Plaintext tidak bocor di DB

        # 3. Konsumsi token secara sah oleh akun Telegram User 1
        tg_user_id = 123456789
        tg_chat_id = 123456789
        consume_res = TelegramService.consume_pairing_token(raw_token, tg_user_id, tg_chat_id, "user1_tg")
        self.assertTrue(consume_res["success"])
        self.assertEqual(consume_res["user_id"], self.user1_id)

        # 4. Verifikasi Single-Use (Token dimusnahkan dan tidak dapat dipakai ulang)
        reuse_res = TelegramService.consume_pairing_token(raw_token, tg_user_id, tg_chat_id, "user1_tg")
        self.assertFalse(reuse_res["success"])
        self.assertIn("tidak valid atau sudah digunakan", reuse_res["message"])

        # 5. Verifikasi di tabel telegram_links: identitas sudah tertaut
        linked_user = TelegramService.find_user_by_telegram(tg_user_id)
        self.assertIsNotNone(linked_user)
        self.assertEqual(linked_user["id"], self.user1_id)

    def test_pairing_token_expired_rejection(self):
        """Memastikan token yang sudah kedaluwarsa otomatis ditolak"""
        token_info = TelegramService.generate_pairing_token(self.user1_id)
        raw_token = token_info["token"]

        # Manipulasi masa kedaluwarsa menjadi kemarin di database
        conn = get_db()
        cursor = conn.cursor()
        past_str = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE telegram_pair_tokens SET expires_at = ? WHERE user_id = ?", (past_str, self.user1_id))
        conn.commit()
        conn.close()

        res = TelegramService.consume_pairing_token(raw_token, 888111, 888111, "expired_test")
        self.assertFalse(res["success"])
        self.assertIn("telah kedaluwarsa", res["message"])

    def test_idempotency_race_condition_protection(self):
        """Memastikan duplikasi update_id Telegram tertolak secara atomik (Anti-Race Condition)"""
        update_id = int(uuid.uuid4().int % 1000000000)
        # Panggilan pertama: belum diproses -> return False
        is_first_processed = TelegramService.is_update_processed(update_id)
        self.assertFalse(is_first_processed)

        # Panggilan kedua (simulasi duplicate webhook/retry): sudah diproses -> return True
        is_second_processed = TelegramService.is_update_processed(update_id)
        self.assertTrue(is_second_processed)

    def test_unlinked_user_cannot_record_transaction(self):
        """Memastikan pesan dari Telegram yang belum tertaut tidak bisa mencatat transaksi"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE source = 'telegram_text'")
        count_before = cursor.fetchone()[0]
        conn.close()

        unlinked_tg_id = int(uuid.uuid4().int % 1000000000)
        payload = {
            "update_id": int(uuid.uuid4().int % 1000000000),
            "message": {
                "message_id": 1,
                "from": {"id": unlinked_tg_id, "username": "intruder"},
                "chat": {"id": unlinked_tg_id, "type": "private"},
                "text": "Beli kopi 20rb"
            }
        }

        res = client.post(
            "/api/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "waiting_link")

        # Pastikan tidak ada transaksi telegram baru yang terbuat di database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE source = 'telegram_text'")
        count_after = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count_after, count_before)

    def test_verified_user_records_transaction_via_telegram(self):
        """Memastikan akun Telegram tertaut mencatat transaksi dengan user_id sah dan saldo terpotong"""
        # Tautkan User 1 via token
        token_info = TelegramService.generate_pairing_token(self.user1_id)
        tg_id = int(uuid.uuid4().int % 1000000000)
        TelegramService.consume_pairing_token(token_info["token"], tg_id, tg_id, "tg_user1")

        # Kirim teks pencatatan transaksi via webhook
        payload = {
            "update_id": int(uuid.uuid4().int % 1000000000),
            "message": {
                "message_id": 2,
                "from": {"id": tg_id, "username": "tg_user1"},
                "chat": {"id": tg_id, "type": "private"},
                "text": "Beli makan siang 25rb"
            }
        }

        res = client.post(
            "/api/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
        )
        self.assertEqual(res.status_code, 200)
        json_data = res.json()
        self.assertEqual(json_data.get("status"), "success")

        # Cek saldo dompet Cash U1: awal 100k - 25k = 75k
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_wallet,))
        balance = cursor.fetchone()[0]

        # Cek baris transaksi terikat ke user1_id
        cursor.execute("SELECT user_id, amount, source FROM transactions WHERE user_id = ?", (self.user1_id,))
        tx_row = cursor.fetchone()
        conn.close()

        self.assertEqual(balance, 75000.0)
        self.assertEqual(tx_row["user_id"], self.user1_id)
        self.assertEqual(tx_row["amount"], 25000.0)
        self.assertIn("telegram", tx_row["source"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
