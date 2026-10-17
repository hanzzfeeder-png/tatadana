import unittest
import uuid
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from starlette.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.services.auth_service import AuthService
from app.security import create_access_token

class TestStage7AuthAndOnboarding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        self.client.cookies.clear()

    def test_01_registration_password_too_short_rejected(self):
        """Memastikan password < 8 karakter ditolak dengan pesan error Bahasa Indonesia"""
        res = self.client.post("/api/auth/register", json={
            "email": f"short_pwd_{uuid.uuid4().hex[:6]}@tatadana.id",
            "password": "pass", # < 8 chars
            "full_name": "Test Short Pwd",
            "phone_number": "081234567890"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("Password minimal 8 karakter", res.json()["detail"])

    def test_02_registration_invalid_phone_rejected(self):
        """Memastikan format nomor HP non-Indonesia ditolak dengan pesan error Bahasa Indonesia"""
        # Test non-Indonesian prefix
        res1 = self.client.post("/api/auth/register", json={
            "email": f"bad_phone1_{uuid.uuid4().hex[:6]}@tatadana.id",
            "password": "Password123!",
            "full_name": "Test Bad Phone 1",
            "phone_number": "123456789" # not starting with 08 or +62
        })
        self.assertEqual(res1.status_code, 400)
        self.assertIn("Nomor WhatsApp tidak valid", res1.json()["detail"])

        # Test too short phone number
        res2 = self.client.post("/api/auth/register", json={
            "email": f"bad_phone2_{uuid.uuid4().hex[:6]}@tatadana.id",
            "password": "Password123!",
            "full_name": "Test Bad Phone 2",
            "phone_number": "0812" # < 10 digits
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn("Nomor WhatsApp tidak valid", res2.json()["detail"])

    def test_03_registration_success_and_default_wallet_created(self):
        """Memastikan registrasi berhasil, wallet 'Dompet Tunai' dibuat otomatis, dan OTP digenerate"""
        unique_id = uuid.uuid4().hex[:6]
        email = f"user_{unique_id}@tatadana.id"
        phone = f"0812{uuid.uuid4().int % 100000000:08d}"

        res = self.client.post("/api/auth/register", json={
            "email": email,
            "password": "SecurePassword123!",
            "full_name": "Budi Santoso",
            "phone_number": phone
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["email"], email)
        self.assertFalse(data["phone_verified"])
        self.assertTrue(len(data["otp_preview"]) == 6)
        user_id = data["user_id"]

        # Verifikasi di database: Dompet Tunai otomatis dibuat dengan is_default = 1
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, is_default, type, balance FROM wallets WHERE user_id = ?", (user_id,))
        wallet = cursor.fetchone()
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet["name"], "Dompet Tunai")
        self.assertEqual(wallet["is_default"], 1)

        # Verifikasi kategori default di-provision
        cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ?", (user_id,))
        cat_count = cursor.fetchone()[0]
        self.assertGreaterEqual(cat_count, 5)

        # Verifikasi default plan adalah 'free'
        cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
        self.assertEqual(cursor.fetchone()["plan"], "free")
        conn.close()

    def test_04_phone_otp_verification_flow(self):
        """Memastikan verifikasi OTP 6 digit berhasil mengubah phone_verified menjadi True"""
        unique_id = uuid.uuid4().hex[:6]
        email = f"otp_user_{unique_id}@tatadana.id"
        phone = f"0813{uuid.uuid4().int % 100000000:08d}"

        reg_res = self.client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "full_name": "Siti Rahma",
            "phone_number": phone
        })
        self.assertEqual(reg_res.status_code, 200)
        data = reg_res.json()["data"]
        user_id = data["user_id"]
        otp = data["otp_preview"]

        # 1. Coba verifikasi dengan OTP salah -> 400
        wrong_res = self.client.post("/api/auth/verify-otp", json={
            "user_id": user_id,
            "otp_code": "000000"
        })
        self.assertEqual(wrong_res.status_code, 400)
        self.assertIn("Kode OTP tidak cocok", wrong_res.json()["detail"])

        # 2. Coba resend OTP
        resend_res = self.client.post("/api/auth/resend-otp", json={"user_id": user_id})
        self.assertEqual(resend_res.status_code, 200)
        new_otp = resend_res.json()["otp_preview"]
        self.assertEqual(len(new_otp), 6)

        # 3. Verifikasi dengan new OTP -> 200
        verify_res = self.client.post("/api/auth/verify-otp", json={
            "user_id": user_id,
            "otp_code": new_otp
        })
        self.assertEqual(verify_res.status_code, 200)
        self.assertIn("Nomor HP berhasil diverifikasi", verify_res.json()["message"])

        # Periksa di database phone_verified == 1
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_verified, otp_code FROM profiles WHERE id = ?", (user_id,))
        profile = cursor.fetchone()
        conn.close()
        self.assertEqual(profile["phone_verified"], 1)
        self.assertIsNone(profile["otp_code"])

    def test_05_onboarding_wizard_completion(self):
        """Memastikan wizard preferensi onboarding menyimpan kategori yang disetujui & me-redirect ke dashboard"""
        unique_id = uuid.uuid4().hex[:6]
        email = f"onb_user_{unique_id}@tatadana.id"
        phone = f"0814{uuid.uuid4().int % 100000000:08d}"

        reg_res = self.client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "full_name": "Ahmad Dani",
            "phone_number": phone
        })
        user_id = reg_res.json()["data"]["user_id"]

        # Kirim onboarding data
        selected_cats = [
            {"name": "🍜 Makanan & Minuman", "type": "expense", "icon": "🍜", "monthly_budget": 1750000},
            {"name": "🚗 Transportasi", "type": "expense", "icon": "🚗", "monthly_budget": 600000},
            {"name": "🎮 Hiburan & Hobi", "type": "expense", "icon": "🎮", "monthly_budget": 350000},
            {"name": "🏠 Tagihan & Utilitas", "type": "expense", "icon": "🏠", "monthly_budget": 800000},
            {"name": "💰 Gaji Bulanan", "type": "income", "icon": "💰", "monthly_budget": 0}
        ]

        onb_res = self.client.post("/api/auth/onboarding", json={
            "user_id": user_id,
            "persona": "karyawan",
            "financial_goal": "save_20",
            "wallet_name": "Dompet Tunai",
            "selected_categories": selected_cats
        })
        self.assertEqual(onb_res.status_code, 200)
        res_data = onb_res.json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["redirect_url"], "/dashboard")

        # Verifikasi budget terupdate di database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT monthly_budget FROM categories WHERE user_id = ? AND name = ?", (user_id, "🍜 Makanan & Minuman"))
        cat = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(cat)
        self.assertEqual(float(cat["monthly_budget"]), 1750000.0)

    def test_06_login_with_email_and_indonesian_phone(self):
        """Memastikan login dapat dilakukan menggunakan email maupun nomor HP (08xx / +62xx)"""
        unique_id = uuid.uuid4().hex[:6]
        email = f"login_user_{unique_id}@tatadana.id"
        raw_phone = f"0815{uuid.uuid4().int % 100000000:08d}"

        self.client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "full_name": "Dewi Sartika",
            "phone_number": raw_phone
        })

        # 1. Login dengan Email
        login_email = self.client.post("/api/auth/login", json={
            "identifier": email,
            "password": "Password123!"
        })
        self.assertEqual(login_email.status_code, 200)
        self.assertIn("tatadana_token", login_email.cookies)

        # 2. Login dengan Nomor HP format 08xx
        login_phone1 = self.client.post("/api/auth/login", json={
            "identifier": raw_phone,
            "password": "Password123!"
        })
        self.assertEqual(login_phone1.status_code, 200)

        # 3. Login dengan Nomor HP format +62xx
        plus_62_phone = "+62" + raw_phone[1:]
        login_phone2 = self.client.post("/api/auth/login", json={
            "identifier": plus_62_phone,
            "password": "Password123!"
        })
        self.assertEqual(login_phone2.status_code, 200)

        # 4. Login salah password -> 401
        login_wrong = self.client.post("/api/auth/login", json={
            "identifier": email,
            "password": "WrongPassword!"
        })
        self.assertEqual(login_wrong.status_code, 401)

    def test_07_auth_pages_split_screen_ui_rendering(self):
        """Memastikan halaman /login dan /register menyajikan UI split-screen modern dan elemen kunci"""
        # 1. GET /login
        login_page = self.client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        html_login = login_page.text
        self.assertIn("Keuanganmu.<br>Terkontrol.", html_login)
        self.assertIn("Ringkasan Pengeluaran", html_login)
        self.assertIn("Lanjutkan dengan Google", html_login)
        self.assertIn("focus:ring-[#F97316]", html_login)
        self.assertNotIn("Akun Demo Siap Pakai", html_login)
        self.assertNotIn("fillDemoCredentials", html_login)
        self.assertIn("signInWithOAuth", html_login)
        self.assertIn("provider: 'google'", html_login)
        self.assertIn("redirectTo", html_login)
        self.assertIn("window.location.origin", html_login)
        self.assertNotIn("handleGoogleOAuthMock", html_login)
        self.assertNotIn("demo@tatadana.id", html_login)

        # 2. GET /register
        register_page = self.client.get("/register")
        self.assertEqual(register_page.status_code, 200)
        html_reg = register_page.text
        self.assertIn("Keuanganmu.<br>Terkontrol.", html_reg)
        self.assertIn("Alokasi Budget Pintar", html_reg)
        self.assertIn("Daftar dengan Google", html_reg)
        self.assertIn("Verifikasi Nomor Handphone", html_reg)
        self.assertIn("Atur Preferensi Finansialmu", html_reg)
        self.assertIn("🍜 Makanan & Minuman", html_reg)
        self.assertIn("focus:ring-[#F97316]", html_reg)
        self.assertIn("signInWithOAuth", html_reg)
        self.assertIn("provider: 'google'", html_reg)

    def test_08_authenticated_user_redirected_to_dashboard(self):
        """Memastikan user yang telah login otomatis diarahkan (redirect) ke /dashboard jika mengakses /login atau /register"""
        user_id = str(uuid.uuid4())
        email = f"active_{user_id[:6]}@tatadana.id"
        now = "2026-10-17 08:00:00"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at)
        VALUES (?, ?, 'dummy_hash', 'Pengguna Aktif', 'starter', 'user', 1, ?, ?)
        """, (user_id, email, now, now))
        conn.commit()
        conn.close()

        token = create_access_token({"sub": user_id, "email": email, "role": "user", "plan": "starter"})
        self.client.cookies.set("tatadana_token", token)

        res_login = self.client.get("/login", follow_redirects=False)
        self.assertEqual(res_login.status_code, 307)
        self.assertEqual(res_login.headers["location"], "/dashboard")

        res_register = self.client.get("/register", follow_redirects=False)
        self.assertEqual(res_register.status_code, 307)
        self.assertEqual(res_register.headers["location"], "/dashboard")

    def test_09_google_oauth_callback_creates_pure_new_profile(self):
        """
        Memastikan Google OAuth callback membuat record profil murni baru (bukan akun demo Budi Pratama),
        mengatur dompet default 'Dompet Tunai', kategori standard, dan memasang cookie tatadana_token.
        """
        u_suffix = uuid.uuid4().hex[:6]
        google_email = f"andi.wijaya.{u_suffix}@gmail.com"
        google_name = "Andi Wijaya Google"
        google_avatar = "https://lh3.googleusercontent.com/a/mock-andi.jpg"
        supabase_uid = str(uuid.uuid4())

        # 1. Test POST /api/auth/oauth-callback
        res = self.client.post("/api/auth/oauth-callback", json={
            "email": google_email,
            "full_name": google_name,
            "avatar_url": google_avatar,
            "supabase_id": supabase_uid
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["is_new"])
        self.assertEqual(data["user"]["email"], google_email)
        self.assertEqual(data["user"]["full_name"], google_name)
        self.assertNotEqual(data["user"]["full_name"], "Budi Pratama")
        self.assertNotEqual(data["user"]["email"], "demo@tatadana.id")
        self.assertIn("tatadana_token", res.cookies)

        # 2. Verifikasi di Database bahwa record murni baru tersimpan
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, full_name, avatar_url, plan FROM profiles WHERE email = ?", (google_email,))
        p = cursor.fetchone()
        self.assertIsNotNone(p)
        self.assertEqual(p["full_name"], google_name)
        self.assertEqual(p["avatar_url"], google_avatar)
        self.assertEqual(p["plan"], "free")

        # Verifikasi dompet default
        cursor.execute("SELECT name, balance FROM wallets WHERE user_id = ?", (p["id"],))
        wallet = cursor.fetchone()
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet["name"], "Dompet Tunai")

        # Verifikasi kategori
        cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ?", (p["id"],))
        cat_count = cursor.fetchone()[0]
        self.assertGreaterEqual(cat_count, 5)
        conn.close()

        # 3. Test GET /auth/callback rendering
        cb_page = self.client.get("/auth/callback")
        self.assertEqual(cb_page.status_code, 200)
        self.assertIn("Menghubungkan Akun Google", cb_page.text)
        self.assertIn("/api/auth/oauth-callback", cb_page.text)

        # 4. Test GET /auth/callback dengan direct parameter (server-side redirect)
        direct_email = f"direct.user.{u_suffix}@gmail.com"
        direct_res = self.client.get(f"/auth/callback?email={direct_email}&name=Direct+Google+User", follow_redirects=False)
        self.assertEqual(direct_res.status_code, 302)
        self.assertEqual(direct_res.headers["location"], "/dashboard")
        self.assertIn("tatadana_token", direct_res.cookies)

    def test_10_google_login_existing_user_synced(self):
        """Memastikan login Google berulang untuk user yang sudah ada tidak menduplikasi akun dan mensinkronkan avatar"""
        u_suffix = uuid.uuid4().hex[:6]
        google_email = f"citra.{u_suffix}@gmail.com"

        # Login pertama (registrasi murni baru)
        res1 = self.client.post("/api/auth/oauth-callback", json={
            "email": google_email,
            "full_name": "Citra Lestari",
            "avatar_url": None
        })
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.json()["data"]["is_new"])

        # Login kedua (login kembali dengan avatar baru dari Google)
        new_avatar = "https://lh3.googleusercontent.com/a/citra-photo.jpg"
        res2 = self.client.post("/api/auth/oauth-callback", json={
            "email": google_email,
            "full_name": "Citra Lestari",
            "avatar_url": new_avatar
        })
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.json()["data"]["is_new"])

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM profiles WHERE email = ?", (google_email,))
        self.assertEqual(cursor.fetchone()[0], 1)
        cursor.execute("SELECT avatar_url FROM profiles WHERE email = ?", (google_email,))
        self.assertEqual(cursor.fetchone()["avatar_url"], new_avatar)
        conn.close()

        # Reject invalid email
        bad_res = self.client.post("/api/auth/oauth-callback", json={
            "email": "not-an-email"
        })
        self.assertEqual(bad_res.status_code, 422) # Pydantic validation error

if __name__ == "__main__":
    unittest.main()
