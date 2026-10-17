import unittest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.config import get_wib_str
from app.security import create_access_token
from app.services.telegram_service import TelegramService

client = TestClient(app)

class TestStage4UserDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.user1_id = f"u1_{uuid.uuid4().hex[:8]}"
        self.user2_id = f"u2_{uuid.uuid4().hex[:8]}"
        now = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()

        # Seed 2 independent users
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User Satu', 'starter', 'user', ?)",
                       (self.user1_id, f"{self.user1_id}@test.id", now))
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User Dua', 'starter', 'user', ?)",
                       (self.user2_id, f"{self.user2_id}@test.id", now))

        # Seed Wallets
        self.u1_w1 = f"w1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at) VALUES (?, ?, 'Dompet Cash U1', 'cash', 250000.0, 1, ?)",
                       (self.u1_w1, self.user1_id, now))

        self.u2_w1 = f"w2_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at) VALUES (?, ?, 'Dompet Bank U2', 'bank', 5000000.0, 1, ?)",
                       (self.u2_w1, self.user2_id, now))

        # Seed Categories
        self.u1_cat = f"cat1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO categories (id, user_id, name, type, monthly_budget, created_at) VALUES (?, ?, 'Makan U1', 'expense', 500000.0, ?)",
                       (self.u1_cat, self.user1_id, now))

        # Seed Transactions for User 1
        self.u1_tx = f"tx1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO transactions (id, user_id, wallet_id, category_id, type, amount, transaction_date, note, source, created_at) VALUES (?, ?, ?, ?, 'expense', 35000.0, ?, 'Makan siang U1', 'web', ?)",
                       (self.u1_tx, self.user1_id, self.u1_w1, self.u1_cat, now, now))

        conn.commit()
        conn.close()

        # Auth tokens
        self.u1_token = create_access_token({"sub": self.user1_id})
        self.u1_headers = {"Authorization": f"Bearer {self.u1_token}"}

        self.u2_token = create_access_token({"sub": self.user2_id})
        self.u2_headers = {"Authorization": f"Bearer {self.u2_token}"}

    def test_unauthenticated_dashboard_redirects_to_login(self):
        """Memastikan akses halaman dashboard tanpa login dialihkan ke halaman /login"""
        res = client.get("/dashboard", follow_redirects=False)
        self.assertEqual(res.status_code, 307)
        self.assertEqual(res.headers.get("location"), "/login")

    def test_authenticated_dashboard_pages_render(self):
        """Memastikan semua halaman navigasi dashboard render dengan sukses (200 OK)"""
        cookies = {"tatadana_token": self.u1_token}
        pages = [
            "/dashboard",
            "/dashboard/transaksi",
            "/dashboard/laporan",
            "/dashboard/budget",
            "/dashboard/wallet",
            "/dashboard/settings"
        ]
        for p in pages:
            res = client.get(p, cookies=cookies)
            self.assertEqual(res.status_code, 200, f"Halaman {p} gagal diakses!")
            self.assertIn("Tata", res.text)
            self.assertIn("Dana", res.text)

    def test_dashboard_stats_api_and_user_isolation(self):
        """Memastikan API stats mengembalikan data kalkulasi riil dan tidak bocor ke user lain"""
        res_u1 = client.get("/api/transactions/stats", headers=self.u1_headers)
        self.assertEqual(res_u1.status_code, 200)
        data_u1 = res_u1.json()

        # User 1 punya saldo Rp 250.000 dan pengeluaran Rp 35.000
        self.assertEqual(data_u1["cards"]["total_balance"], 250000.0)
        self.assertEqual(data_u1["cards"]["monthly_expense"], 35000.0)
        self.assertEqual(len(data_u1["recent_transactions"]), 1)
        self.assertEqual(data_u1["recent_transactions"][0]["note"], "Makan siang U1")

        # User 2 punya saldo Rp 5.000.000 dan 0 transaksi
        res_u2 = client.get("/api/transactions/stats", headers=self.u2_headers)
        self.assertEqual(res_u2.status_code, 200)
        data_u2 = res_u2.json()
        self.assertEqual(data_u2["cards"]["total_balance"], 5000000.0)
        self.assertEqual(data_u2["cards"]["monthly_expense"], 0.0)
        self.assertEqual(len(data_u2["recent_transactions"]), 0)

    def test_settings_pairing_code_and_unlink_lifecycle(self):
        """Memastikan alur tombol pembuat pairing token, status terhubung, dan tombol putuskan tautan"""
        # 1. Cek status awal: Belum terhubung
        res_status_1 = client.get("/api/telegram/status", headers=self.u1_headers)
        self.assertEqual(res_status_1.status_code, 200)
        self.assertFalse(res_status_1.json()["data"]["is_user_linked"])

        # 2. Klik tombol buat kode penautan
        res_gen = client.post("/api/telegram/generate-pairing-code", headers=self.u1_headers)
        self.assertEqual(res_gen.status_code, 200)
        token_info = res_gen.json()["data"]
        raw_token = token_info["token"]
        self.assertTrue(raw_token.startswith("TD-"))
        self.assertIn("deep_link", token_info)

        # 3. Simulasi penautan via bot Telegram
        consume_res = TelegramService.consume_pairing_token(raw_token, 777123, 777123, "test_user1_tg")
        self.assertTrue(consume_res["success"])

        # 4. Cek status setelah penautan: Harus Terhubung
        res_status_2 = client.get("/api/telegram/status", headers=self.u1_headers)
        self.assertEqual(res_status_2.status_code, 200)
        st_data = res_status_2.json()["data"]
        self.assertTrue(st_data["is_user_linked"])
        self.assertEqual(st_data["user_link"]["telegram_username"], "test_user1_tg")

        # 5. Putuskan tautan via tombol Putuskan Tautan di Settings
        res_unlink = client.post("/api/telegram/unlink", headers=self.u1_headers)
        self.assertEqual(res_unlink.status_code, 200)

        # 6. Cek status akhir: Kembali Belum Terhubung
        res_status_3 = client.get("/api/telegram/status", headers=self.u1_headers)
        self.assertFalse(res_status_3.json()["data"]["is_user_linked"])

if __name__ == "__main__":
    unittest.main()
