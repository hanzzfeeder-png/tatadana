import unittest
import uuid
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from starlette.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.config import get_wib_str
from app.security import create_access_token

class TestStage6LandingPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.user_id = str(uuid.uuid4())
        cls.user_email = f"user_{cls.user_id[:6]}@tatadana.id"
        now = get_wib_str()

        # Seed test user
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at)
        VALUES (?, ?, 'dummy_hash', 'Pengguna Uji', 'starter', 'user', 1, ?, ?)
        """, (cls.user_id, cls.user_email, now, now))
        conn.commit()
        conn.close()

        cls.user_token = create_access_token({
            "sub": cls.user_id,
            "email": cls.user_email,
            "role": "user",
            "plan": "starter"
        })

    def setUp(self):
        self.client.cookies.clear()

    def test_01_guest_landing_page_renders_200(self):
        """Memastikan pengunjung tamu (belum login) dapat melihat landing page publik dengan sukses (200 OK)"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 1. Navbar & Branding
        self.assertIn("TataDana", html)
        self.assertIn("SMART FINTECH", html)
        self.assertIn('href="/login"', html)
        self.assertIn('href="/register"', html)

        # 2. Hero Section
        self.assertIn("✨ Catat keuangan langsung dari Telegram", html)
        self.assertIn("Gaji habis sebelum akhir bulan?", html)
        self.assertIn("ke mana uangmu pergi", html)
        self.assertIn("TataDana mencatat setiap pengeluaranmu langsung dari chat Telegram atau foto struk", html)
        self.assertIn("Mulai Gratis Sekarang", html)
        self.assertIn("Lihat cara kerjanya", html)
        self.assertIn("// TODO: ganti dengan video asli", html)

    def test_02_problem_aware_and_solution_transition(self):
        """Memastikan 3 masalah utama pengguna dan transisi solusi hadir sesuai spesifikasi"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 3 Masalah
        self.assertIn("Buka aplikasi keuangan? Nanti dulu deh...", html)
        self.assertIn("Kok uangnya habis ya? Padahal kayak tidak beli apa-apa", html)
        self.assertIn("Udah niat bikin budget, tapi seminggu lupa", html)

        # Transisi Solusi
        self.assertIn("Bagaimana kalau mencatat keuangan semudah kirim pesan ke teman?", html)
        self.assertIn("Introducing <b>TataDana</b>", html)

    def test_03_interactive_demo_and_three_main_features(self):
        """Memastikan widget simulasi bot Telegram interaktif dan 3 fitur utama alternating terpasang"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Widget Demo
        self.assertIn("landing-chat-stream", html)
        self.assertIn("Kopi 25rb", html)
        self.assertIn("Bensin 50k", html)
        self.assertIn("Gaji 1.5jt", html)
        self.assertIn("Struk 146rb", html)
        self.assertIn("/saldo", html)

        # 3 Fitur Utama
        self.assertIn("Catat via Telegram — Teks, Voice Note, & Foto Struk", html)
        self.assertIn("Laporan & Ekspor Otomatis di Dashboard Web", html)
        self.assertIn("AI Financial Advisor & Peringatan Otomatis", html)

    def test_04_testimonials_pricing_and_faq_present(self):
        """Memastikan masonry testimoni, pricing table 2 kolom (Starter vs Pro), dan minimal 7 FAQ tersedia"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Testimoni & Todo mark
        self.assertIn("// TODO: ganti dengan testimoni asli", html)
        self.assertIn("Anisa Putri", html)
        self.assertIn("Rizky Pratama", html)

        # Pricing Table (2 Kolom: Starter vs Pro)
        self.assertIn("Paket Starter", html)
        self.assertIn("Rp 49.000", html)
        self.assertIn("TataDana Pro", html)
        self.assertIn("Rp 99.000", html)
        self.assertIn("Sekali Bayar", html)

        # Minimal 7 Pertanyaan FAQ
        self.assertIn("1. Apakah fitur foto struk bisa dipakai di paket Starter?", html)
        self.assertIn("2. Bagaimana TataDana menjamin keamanan dan privasi data keuangan saya?", html)
        self.assertIn("3. Bagaimana format input teks saat chat ke Bot Telegram?", html)
        self.assertIn("4. Bagaimana cara menghubungkan akun Telegram dengan akun TataDana saya?", html)
        self.assertIn("5. Apakah TataDana mendukung banyak dompet (multi-wallet) dan transfer saldo?", html)
        self.assertIn("6. Apakah ada batasan jumlah transaksi per bulan?", html)
        self.assertIn("7. Bagaimana jika saya mengalami kendala teknis atau butuh bantuan?", html)

    def test_05_final_cta_and_four_column_footer(self):
        """Memastikan final CTA banner gradien oranye dan footer 4 kolom (Brand, Produk, Perusahaan, Legal) lengkap"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Final CTA
        self.assertIn("Mulai Kendalikan Keuanganmu Hari Ini", html)
        self.assertIn("Daftar Akun Gratis Sekarang", html)

        # Footer 4 Kolom
        self.assertIn("Produk", html)
        self.assertIn("Perusahaan", html)
        self.assertIn("Legal & Bantuan", html)
        self.assertIn("Kebijakan Privasi", html)
        self.assertIn("Syarat & Ketentuan", html)
        self.assertIn("support@tatadana.id", html)

    def test_06_authenticated_user_redirects_to_dashboard(self):
        """Memastikan pengguna yang sudah login (sesi aktif) otomatis dialihkan ke /dashboard saat membuka root /"""
        auth_client = TestClient(app)
        auth_client.cookies.set("tatadana_token", self.user_token)

        # Buka root / tanpa follow_redirects untuk verifikasi response redirect (302/307)
        res = auth_client.get("/", follow_redirects=False)
        self.assertIn(res.status_code, [302, 307])
        self.assertEqual(res.headers.get("location"), "/dashboard")

        # Buka root / dengan follow_redirects untuk memastikan mendarat di /dashboard (200 OK)
        res_followed = auth_client.get("/", follow_redirects=True)
        self.assertEqual(res_followed.status_code, 200)
        self.assertIn("Ringkasan finansial", res_followed.text)
        self.assertIn("Saldo Total", res_followed.text)

    def test_07_legal_pages_render_200(self):
        """Memastikan halaman publik /privacy dan /terms dapat diakses (200 OK)"""
        res_privacy = self.client.get("/privacy")
        self.assertEqual(res_privacy.status_code, 200)
        self.assertIn("Kebijakan Privasi TataDana", res_privacy.text)

        res_terms = self.client.get("/terms")
        self.assertEqual(res_terms.status_code, 200)
        self.assertIn("Syarat & Ketentuan Layanan TataDana", res_terms.text)

if __name__ == "__main__":
    unittest.main()
