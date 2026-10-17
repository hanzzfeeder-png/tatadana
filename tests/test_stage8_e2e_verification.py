import unittest
import uuid
import os
import sys
from datetime import datetime
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from starlette.testclient import TestClient
from app.main import app
from app.database import get_db, init_db
from app.config import settings, get_wib_now, get_wib_str
from app.services.telegram_service import TelegramService
from app.services.transaction_service import TransactionService

class TestStage8E2EVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        self.client.cookies.clear()

    def test_01_complete_auth_and_onboarding_lifecycle(self):
        """
        1. Uji alur auth lengkap:
        Register -> Verifikasi OTP nomor HP -> Onboarding preferensi -> Setup wallet default 'Dompet Tunai'
        """
        unique_suffix = uuid.uuid4().hex[:6]
        email = f"e2e_stage8_{unique_suffix}@tatadana.id"
        raw_phone = f"0812{uuid.uuid4().int % 100000000:08d}"

        # 1. Registrasi Akun
        reg_res = self.client.post("/api/auth/register", json={
            "email": email,
            "password": "Password123!",
            "full_name": "Pengguna Verifikasi E2E",
            "phone_number": raw_phone
        })
        self.assertEqual(reg_res.status_code, 200)
        data = reg_res.json()["data"]
        user_id = data["user_id"]
        otp_code = data["otp_preview"]
        self.assertFalse(data["phone_verified"])

        # 2. Verifikasi OTP Nomor HP
        otp_res = self.client.post("/api/auth/verify-otp", json={
            "user_id": user_id,
            "otp_code": otp_code
        })
        self.assertEqual(otp_res.status_code, 200)
        self.assertIn("Nomor HP berhasil diverifikasi", otp_res.json()["message"])

        # 3. Onboarding Preferensi Finansial & Kategori Standar
        categories_approved = [
            {"name": "🍜 Makanan & Minuman", "type": "expense", "icon": "🍜", "monthly_budget": 1500000},
            {"name": "🚗 Transportasi", "type": "expense", "icon": "🚗", "monthly_budget": 500000},
            {"name": "🎮 Hiburan & Hobi", "type": "expense", "icon": "🎮", "monthly_budget": 300000},
            {"name": "🏠 Tagihan & Utilitas", "type": "expense", "icon": "🏠", "monthly_budget": 750000},
            {"name": "💰 Gaji Bulanan", "type": "income", "icon": "💰", "monthly_budget": 0}
        ]

        onb_res = self.client.post("/api/auth/onboarding", json={
            "user_id": user_id,
            "persona": "karyawan",
            "financial_goal": "stop_boncos",
            "wallet_name": "Dompet Tunai",
            "selected_categories": categories_approved
        })
        self.assertEqual(onb_res.status_code, 200)
        self.assertTrue(onb_res.json()["success"])
        self.assertEqual(onb_res.json()["redirect_url"], "/dashboard")

        # 4. Verifikasi State di Database
        conn = get_db()
        cursor = conn.cursor()

        # Profil verified
        cursor.execute("SELECT phone_verified, plan FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        self.assertEqual(p["phone_verified"], 1)
        self.assertEqual(p["plan"], "free")

        # Default wallet 'Dompet Tunai' exists and is_default = 1
        cursor.execute("SELECT name, is_default, balance FROM wallets WHERE user_id = ?", (user_id,))
        w = cursor.fetchone()
        self.assertIsNotNone(w)
        self.assertEqual(w["name"], "Dompet Tunai")
        self.assertEqual(w["is_default"], 1)

        # Kategori terpasang
        cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ?", (user_id,))
        cat_count = cursor.fetchone()[0]
        self.assertGreaterEqual(cat_count, 5)
        conn.close()

    def test_02_telegram_webhook_transactions_and_wib_timezone(self):
        """
        2. Uji webhook Telegram:
        - Pasangkan akun via pairing token.
        - Kirim pesan teks 'beli makan 25rb' (pengeluaran).
        - Kirim pesan teks 'gaji freelance 1.5jt' (pemasukan).
        - Pastikan transaksi tersimpan dengan timezone Asia/Jakarta (WIB).
        """
        user_id = str(uuid.uuid4())
        email = f"tg_e2e_{user_id[:6]}@tatadana.id"
        now_wib = get_wib_str()

        # Seed profile
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at)
        VALUES (?, ?, 'hash', 'Budi Telegram', 'starter', 'user', 1, ?, ?)
        """, (user_id, email, now_wib, now_wib))

        # Seed default wallet
        wallet_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT INTO wallets (id, user_id, name, type, balance, is_default, icon, color, created_at, updated_at)
        VALUES (?, ?, 'Dompet Tunai', 'cash', 100000.0, 1, '👛', '#FF6B00', ?, ?)
        """, (wallet_id, user_id, now_wib, now_wib))

        # Seed categories
        cursor.execute("""
        INSERT INTO categories (id, user_id, name, type, icon, color, created_at)
        VALUES (?, ?, 'Makanan & Minuman', 'expense', '🍜', '#FF6B00', ?)
        """, (str(uuid.uuid4()), user_id, now_wib))
        cursor.execute("""
        INSERT INTO categories (id, user_id, name, type, icon, color, created_at)
        VALUES (?, ?, 'Penghasilan Tambahan', 'income', '💼', '#10B981', ?)
        """, (str(uuid.uuid4()), user_id, now_wib))
        conn.commit()
        conn.close()

        # Link Telegram Account
        tg_id = int(uuid.uuid4().int % 1000000000)
        TelegramService.link_telegram_account_direct(user_id, tg_id, tg_id, "buditg")

        # 1. Simulasikan pesan teks pengeluaran "beli makan 25rb"
        update_id_1 = int(uuid.uuid4().int % 1000000000)
        res_exp = self.client.post("/api/telegram/webhook", json={
            "update_id": update_id_1,
            "message": {
                "message_id": 101,
                "from": {"id": tg_id, "username": "buditg"},
                "chat": {"id": tg_id, "type": "private"},
                "text": "beli makan 25rb"
            }
        }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
        self.assertEqual(res_exp.status_code, 200)

        # 2. Simulasikan pesan teks pemasukan "gaji freelance 1.5jt"
        update_id_2 = int(uuid.uuid4().int % 1000000000)
        res_inc = self.client.post("/api/telegram/webhook", json={
            "update_id": update_id_2,
            "message": {
                "message_id": 102,
                "from": {"id": tg_id, "username": "buditg"},
                "chat": {"id": tg_id, "type": "private"},
                "text": "gaji freelance 1.5jt"
            }
        }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
        self.assertEqual(res_inc.status_code, 200)

        # 3. Verifikasi Transaksi dan Timezone WIB di Database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT type, amount, source, transaction_date
        FROM transactions
        WHERE user_id = ?
        ORDER BY created_at ASC
        """, (user_id,))
        txs = cursor.fetchall()
        conn.close()

        self.assertEqual(len(txs), 2)

        # Pengeluaran
        self.assertEqual(txs[0]["type"], "expense")
        self.assertEqual(float(txs[0]["amount"]), 25000.0)
        self.assertEqual(txs[0]["source"], "telegram_text")

        # Pemasukan
        self.assertEqual(txs[1]["type"], "income")
        self.assertEqual(float(txs[1]["amount"]), 1500000.0)
        self.assertEqual(txs[1]["source"], "telegram_text")

        # Pastikan format tanggal transaksi sesuai format WIB (YYYY-MM-DD HH:MM:SS)
        current_wib_year = get_wib_now().year
        tx_dt = datetime.strptime(txs[0]["transaction_date"], "%Y-%m-%d %H:%M:%S")
        self.assertEqual(tx_dt.year, current_wib_year)
        self.assertEqual(tx_dt.month, get_wib_now().month)

    def test_03_telegram_webhook_idempotency(self):
        """
        3. Uji idempotency Telegram:
        Memastikan pesan dengan update_id duplikat otomatis di-skip dan tidak dicatat ganda di DB.
        """
        user_id = str(uuid.uuid4())
        now_wib = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at) VALUES (?, ?, 'hash', 'User Idem', 'starter', 'user', 1, ?, ?)",
                       (user_id, f"idem_{user_id[:6]}@tatadana.id", now_wib, now_wib))
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at, updated_at) VALUES (?, ?, 'Dompet Tunai', 'cash', 50000.0, 1, ?, ?)",
                       (str(uuid.uuid4()), user_id, now_wib, now_wib))
        conn.commit()
        conn.close()

        tg_id = int(uuid.uuid4().int % 1000000000)
        TelegramService.link_telegram_account_direct(user_id, tg_id, tg_id, "idem_user")

        duplicate_update_id = int(uuid.uuid4().int % 1000000000)
        payload = {
            "update_id": duplicate_update_id,
            "message": {
                "message_id": 201,
                "from": {"id": tg_id, "username": "idem_user"},
                "chat": {"id": tg_id, "type": "private"},
                "text": "Beli pulsa 10k"
            }
        }

        # Panggilan pertama -> Diproses
        res1 = self.client.post("/api/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
        self.assertEqual(res1.status_code, 200)

        # Panggilan kedua (dengan update_id sama) -> Terdeteksi duplikat, di-skip
        res2 = self.client.post("/api/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json().get("status"), "skipped")
        self.assertEqual(res2.json().get("reason"), "already_processed")

        # Pastikan transaksi hanya tercatat 1 kali di database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user_id,))
        tx_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(tx_count, 1)

    def test_04_starter_plan_restrictions_ocr_and_monthly_quota(self):
        """
        4. Uji pembatasan paket Starter:
        - Akses OCR struk belanja ditolak (status 'blocked' & reason 'starter_plan_restriction').
        - Transaksi dicegat ketika kuota 50 kali/bulan terlampaui.
        """
        user_id = str(uuid.uuid4())
        now_wib = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at) VALUES (?, ?, 'hash', 'Starter User', 'starter', 'user', 1, ?, ?)",
                       (user_id, f"starter_{user_id[:6]}@tatadana.id", now_wib, now_wib))
        wallet_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at, updated_at) VALUES (?, ?, 'Dompet Tunai', 'cash', 200000.0, 1, ?, ?)",
                       (wallet_id, user_id, now_wib, now_wib))
        conn.commit()
        conn.close()

        tg_id = int(uuid.uuid4().int % 1000000000)
        TelegramService.link_telegram_account_direct(user_id, tg_id, tg_id, "starter_user")

        # A. Uji blokir OCR Struk untuk Starter
        res_photo = self.client.post("/api/telegram/webhook", json={
            "update_id": int(uuid.uuid4().int % 1000000000),
            "message": {
                "message_id": 301,
                "from": {"id": tg_id, "username": "starter_user"},
                "chat": {"id": tg_id, "type": "private"},
                "photo": [{"file_id": "dummy_photo_1", "file_unique_id": "dp1"}]
            }
        }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
        self.assertEqual(res_photo.status_code, 200)
        self.assertEqual(res_photo.json().get("status"), "blocked")
        self.assertEqual(res_photo.json().get("reason"), "starter_plan_restriction")

        # B. Uji kuota transaksi bulanan (Maks 50 untuk Starter)
        conn = get_db()
        cursor = conn.cursor()
        month_prefix = get_wib_now().strftime("%Y-%m")
        # Simulasikan 50 transaksi yang sudah ada di bulan berjalan
        dummy_txs = [
            (str(uuid.uuid4()), user_id, wallet_id, None, 'expense', 1000.0, 'dummy', f"{month_prefix}-01 10:00:00", 'test', now_wib)
            for _ in range(50)
        ]
        cursor.executemany("""
        INSERT INTO transactions (id, user_id, wallet_id, category_id, type, amount, note, transaction_date, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, dummy_txs)
        conn.commit()
        conn.close()

        # Coba buat transaksi ke-51 -> Ditolak karena batas kuota starter
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=user_id,
                wallet_id=wallet_id,
                tx_type="expense",
                amount=5000.0,
                note="Transaksi ke-51 melebihi batas"
            )
        self.assertIn("Batas transaksi bulanan tercapai (50/50 transaksi)", str(ctx.exception))

        # Jika di-upgrade ke Pro, transaksi ke-51 langsung diizinkan
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE profiles SET plan = 'pro' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

        tx_pro = TransactionService.create_transaction(
            user_id=user_id,
            wallet_id=wallet_id,
            tx_type="expense",
            amount=5000.0,
            note="Transaksi Pro ke-51 berhasil"
        )
        self.assertIsNotNone(tx_pro["id"])

    def test_05_export_reports_excel_pdf_and_history(self):
        """
        5. Uji ekspor laporan keuangan:
        - Starter plan ditolak saat mengekspor (403 Forbidden).
        - Akun Pro berhasil Generate Excel (.xlsx) & PDF (.pdf).
        - Pastikan response valid, file fisik tergenerate > 0 byte.
        - Pastikan endpoint riwayat ekspor dan download file berfungsi normal.
        """
        user_id = str(uuid.uuid4())
        email = f"export_{user_id[:6]}@tatadana.id"
        now_wib = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, phone_verified, created_at, updated_at) VALUES (?, ?, 'hash', 'Export Tester', 'starter', 'user', 1, ?, ?)",
                       (user_id, email, now_wib, now_wib))
        wallet_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, is_default, created_at, updated_at) VALUES (?, ?, 'Dompet Tunai', 'cash', 500000.0, 1, ?, ?)",
                       (wallet_id, user_id, now_wib, now_wib))

        # Insert some transactions for report
        cursor.execute("""
        INSERT INTO transactions (id, user_id, wallet_id, type, amount, note, transaction_date, source, created_at)
        VALUES (?, ?, ?, 'income', 1000000.0, 'Gaji Projek', ?, 'web', ?)
        """, (str(uuid.uuid4()), user_id, wallet_id, now_wib, now_wib))
        cursor.execute("""
        INSERT INTO transactions (id, user_id, wallet_id, type, amount, note, transaction_date, source, created_at)
        VALUES (?, ?, ?, 'expense', 150000.0, 'Belanja Mingguan', ?, 'web', ?)
        """, (str(uuid.uuid4()), user_id, wallet_id, now_wib, now_wib))
        conn.commit()
        conn.close()

        # Set user session cookie (as starter)
        from app.security import create_access_token
        token_starter = create_access_token({"sub": user_id, "email": email, "role": "user", "plan": "starter"})
        self.client.cookies.set("tatadana_token", token_starter)

        # A. Uji Starter ditolak ekspor (403)
        res_starter_excel = self.client.post("/api/reports/export/excel", json={})
        self.assertEqual(res_starter_excel.status_code, 403)
        self.assertIn("eksklusif untuk pengguna paket Pro", res_starter_excel.json()["detail"])

        # B. Upgrade pengguna ke Pro
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE profiles SET plan = 'pro' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

        token_pro = create_access_token({"sub": user_id, "email": email, "role": "user", "plan": "pro"})
        self.client.cookies.set("tatadana_token", token_pro)

        # 1. Ekspor Excel untuk Pro
        res_excel = self.client.post("/api/reports/export/excel", json={})
        self.assertEqual(res_excel.status_code, 200)
        data_excel = res_excel.json()
        self.assertTrue(data_excel["success"])
        excel_filename = data_excel["file_name"]
        self.assertTrue(excel_filename.endswith(".xlsx"))

        # 2. Ekspor PDF untuk Pro
        res_pdf = self.client.post("/api/reports/export/pdf", json={})
        self.assertEqual(res_pdf.status_code, 200)
        data_pdf = res_pdf.json()
        self.assertTrue(data_pdf["success"])
        pdf_filename = data_pdf["file_name"]
        self.assertTrue(pdf_filename.endswith(".pdf"))

        # 3. Riwayat Ekspor
        res_history = self.client.get("/api/reports/export/history")
        self.assertEqual(res_history.status_code, 200)
        history = res_history.json()["data"]
        self.assertGreaterEqual(len(history), 2)
        types = [h["file_type"] for h in history]
        self.assertIn("xlsx", types)
        self.assertIn("pdf", types)

        # 4. Download File Ekspor
        dl_excel = self.client.get(f"/api/reports/download/{excel_filename}")
        self.assertEqual(dl_excel.status_code, 200)
        self.assertGreater(len(dl_excel.content), 0)

        dl_pdf = self.client.get(f"/api/reports/download/{pdf_filename}")
        self.assertEqual(dl_pdf.status_code, 200)
        self.assertGreater(len(dl_pdf.content), 0)

if __name__ == "__main__":
    unittest.main()
