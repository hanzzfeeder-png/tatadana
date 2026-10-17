import unittest
import uuid
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from starlette.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.config import get_wib_str, settings
from app.security import create_access_token

class TestStage5AdminDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        conn = get_db()
        cursor = conn.cursor()

        now = get_wib_str()
        cls.admin_id = str(uuid.uuid4())
        cls.admin_email = f"admin_{cls.admin_id[:6]}@tatadana.id"
        cls.user_id = str(uuid.uuid4())
        cls.user_email = f"user_{cls.user_id[:6]}@tatadana.id"

        # 1. Create Superadmin User
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, role, plan, is_admin, phone_verified, created_at, updated_at)
        VALUES (?, ?, 'dummy_hash', 'Superadmin TataDana', 'superadmin', 'pro', 1, 1, ?, ?)
        """, (cls.admin_id, cls.admin_email, now, now))

        # 2. Create Regular Starter User
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, role, plan, is_admin, phone_verified, created_at, updated_at)
        VALUES (?, ?, 'dummy_hash', 'Budi Santoso', 'user', 'starter', 0, 1, ?, ?)
        """, (cls.user_id, cls.user_email, now, now))

        # 3. Create Sample Wallet & Transactions for User
        cls.wallet_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT INTO wallets (id, user_id, name, type, balance, created_at, updated_at)
        VALUES (?, ?, 'Dompet Utama', 'cash', 150000.0, ?, ?)
        """, (cls.wallet_id, cls.user_id, now, now))

        cursor.execute("""
        INSERT INTO transactions (id, user_id, wallet_id, type, amount, transaction_date, note, created_at)
        VALUES (?, ?, ?, 'income', 150000.0, ?, 'Gaji sampingan', ?)
        """, (str(uuid.uuid4()), cls.user_id, cls.wallet_id, now, now))

        # 4. Create Sample AI Log
        cursor.execute("""
        INSERT INTO ai_logs (id, user_id, provider, model, source, prompt_tokens, completion_tokens, latency_ms, status, created_at)
        VALUES (?, ?, 'gemini', 'gemini-1.5-flash', 'parse_transaction', 120, 45, 340, 'success', ?)
        """, (str(uuid.uuid4()), cls.user_id, now))

        # 5. Create Pending Subscription for User
        cls.order_id = f"ORDER-{uuid.uuid4().hex[:8].upper()}"
        cls.sub_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT INTO subscriptions (id, user_id, order_id, plan, gross_amount, status, payment_type, created_at, updated_at)
        VALUES (?, ?, ?, 'pro', 49000, 'pending', 'manual_transfer', ?, ?)
        """, (cls.sub_id, cls.user_id, cls.order_id, now, now))

        conn.commit()
        conn.close()

        # Generate JWT Tokens
        cls.admin_token = create_access_token({
            "sub": cls.admin_id,
            "email": cls.admin_email,
            "role": "superadmin",
            "is_admin": True,
            "plan": "pro"
        })
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.user_token = create_access_token({
            "sub": cls.user_id,
            "email": cls.user_email,
            "role": "user",
            "is_admin": False,
            "plan": "starter"
        })
        cls.user_headers = {"Authorization": f"Bearer {cls.user_token}"}

    def setUp(self):
        self.client.cookies.clear()

    def test_01_admin_access_control(self):
        """Memastikan proteksi RBAC: User biasa ditolak 403 dan unauthenticated ditolak 401"""
        # Unauthenticated request
        res = self.client.get("/api/admin/overview")
        self.assertEqual(res.status_code, 401)

        # Regular user request (Forbidden 403)
        res = self.client.get("/api/admin/overview", headers=self.user_headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Akses khusus Administrator", res.json()["detail"])

        # Superadmin request (Allowed 200)
        res = self.client.get("/api/admin/overview", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertIn("total_users", data)
        self.assertIn("ai_calls_month", data)
        self.assertIn("pending_payments_count", data)

    def test_02_ai_providers_crud_and_encryption(self):
        """Memastikan pengelolaan multi-provider AI: enkripsi key, prioritas, dan failover mode"""
        # 1. Tambah Provider Baru
        raw_key = "sk-test-secret-openai-key-tatadana"
        payload = {
            "name": "OpenAI GPT-4o Mini",
            "provider_type": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": raw_key,
            "is_active": True,
            "priority": 2,
            "mode": "parallel_failover"
        }
        res = self.client.post("/api/admin/ai-providers", json=payload, headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)

        # 2. List Provider dan verifikasi enkripsi (raw key tidak boleh bocor)
        res = self.client.get("/api/admin/ai-providers", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        providers = res.json()["data"]
        created = next((p for p in providers if p["name"] == "OpenAI GPT-4o Mini"), None)
        self.assertIsNotNone(created)
        self.assertEqual(created["provider_type"], "openai")
        self.assertEqual(created["mode"], "parallel_failover")
        self.assertNotIn(raw_key, str(res.json())) # Raw key tidak terbuka di output
        self.assertTrue(created["api_key_masked"].endswith("••••••••"))

        # 3. Update Status / Prioritas
        prov_id = created["id"]
        res = self.client.put(f"/api/admin/ai-providers/{prov_id}", json={"priority": 1, "is_active": False}, headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)

        # 4. Hapus Provider
        res = self.client.delete(f"/api/admin/ai-providers/{prov_id}", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)

    def test_03_ai_logs_pagination_and_filter(self):
        """Memastikan log AI dapat di-filter berdasarkan provider dan status"""
        res = self.client.get("/api/admin/ai-logs?page=1&limit=10&provider=gemini", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("pagination", data)
        self.assertGreaterEqual(data["pagination"]["total"], 1)

    def test_04_users_list_and_search(self):
        """Memastikan fitur pencarian daftar pengguna dan status bot telegram"""
        # Search existing user by name
        res = self.client.get("/api/admin/users?q=Budi", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        users = res.json()["data"]
        self.assertGreaterEqual(len(users), 1)
        self.assertEqual(users[0]["full_name"], "Budi Santoso")
        self.assertIn("is_tg_connected", users[0])

    def test_05_view_user_transactions_and_audit_logging(self):
        """Memastikan inspeksi transaksi pengguna mencatat rekam jejak ke admin_audit_logs"""
        # Admin memeriksa transaksi user Budi
        res = self.client.get(f"/api/admin/users/{self.user_id}/transactions", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        txs = res.json()["data"]
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["amount"], 150000.0)

        # Verifikasi bahwa tindakan ini tercatat di audit log
        res_audit = self.client.get("/api/admin/audit-logs", headers=self.admin_headers)
        self.assertEqual(res_audit.status_code, 200)
        logs = res_audit.json()["data"]
        inspection_log = next((l for l in logs if l.get("action") == "view_user_transactions" and l.get("target_user_id") == self.user_id), None)
        self.assertIsNotNone(inspection_log)
        self.assertEqual(inspection_log["admin_id"], self.admin_id)

    def test_06_impersonation_session_and_audit(self):
        """Memastikan impersonasi akun tanpa password menghasilkan sesi valid & tercatat audit log"""
        # Admin impersonate user Budi
        res = self.client.post(f"/api/admin/impersonate/{self.user_id}", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["redirect_url"], "/dashboard")

        # Cek cookie token yang diberikan
        new_token = res.cookies.get("tatadana_token")
        self.assertIsNotNone(new_token)

        # Akses dashboard dengan token impersonasi
        impersonate_client = TestClient(app)
        impersonate_client.cookies.set("tatadana_token", new_token)
        dash_res = impersonate_client.get("/dashboard")
        self.assertEqual(dash_res.status_code, 200)

        # Verifikasi audit log impersonation
        res_audit = self.client.get("/api/admin/audit-logs", headers=self.admin_headers)
        self.assertEqual(res_audit.status_code, 200)
        logs = res_audit.json()["data"]
        imp_log = next((l for l in logs if l.get("action") == "impersonate_user" and l.get("target_user_id") == self.user_id), None)
        self.assertIsNotNone(imp_log)

    def test_07_payment_approval_upgrades_user_to_pro(self):
        """Memastikan approve pembayaran upgrade otomatis menaikkan profil user ke paket Pro"""
        # Cek status sebelum approval (harus starter)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT plan FROM profiles WHERE id = ?", (self.user_id,))
        plan_before = cursor.fetchone()[0]
        self.assertEqual(plan_before, "starter")
        conn.close()

        # Approve pembayaran via /api/admin/payments/{id}/action
        res = self.client.post(f"/api/admin/payments/{self.sub_id}/action", json={"action": "approve"}, headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("berhasil di-approve", res.json()["message"])

        # Verifikasi status setelah approval (otomatis jadi Pro)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT plan FROM profiles WHERE id = ?", (self.user_id,))
        plan_after = cursor.fetchone()[0]
        cursor.execute("SELECT status FROM subscriptions WHERE id = ?", (self.sub_id,))
        sub_status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(plan_after, "pro")
        self.assertEqual(sub_status, "active")

    def test_08_all_admin_web_templates_render(self):
        """Memastikan seluruh 6 halaman Web Admin modern Orange & Clean White berhasil dirender 200 OK"""
        admin_client = TestClient(app)
        admin_client.cookies.set("tatadana_token", self.admin_token)

        admin_routes = [
            "/admin",
            "/admin/ai-providers",
            "/admin/users",
            "/admin/payments",
            "/admin/ai-logs",
            "/admin/audit-logs"
        ]

        for route in admin_routes:
            res = admin_client.get(route)
            self.assertEqual(res.status_code, 200, f"Gagal render {route}")
            self.assertIn("TataDana", res.text)
            self.assertIn("Superadmin", res.text)

if __name__ == "__main__":
    unittest.main()
