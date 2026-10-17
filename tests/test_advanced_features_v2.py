import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, get_db
from app.services.report_service import ReportService, STORAGE_DIR
from app.services.auth_service import AuthService
from app.services.ai_service import AIService
from app.security import create_access_token
from app.config import settings

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    init_db()

class TestAdvancedFeaturesV2:
    def test_01_pdf_export_and_download(self):
        """
        Uji Fitur 1: Ekspor PDF Laporan Keuangan
        - Filter tanggal, kategori, dompet, jenis
        - Pembuatan file PDF dengan NumberedCanvas & Category Breakdown
        - Download endpoint dengan Content-Disposition attachment
        """
        # 1. Setup User Pro
        import uuid
        import random
        u_suffix = uuid.uuid4().hex[:6]
        test_email = f"pdf_tester_{u_suffix}@tatadana.id"
        test_phone = f"0819{random.randint(10000000, 99999999)}"

        user_reg = AuthService.register_user(
            email=test_email,
            password="password123",
            full_name="PDF Pro Tester",
            phone_number=test_phone
        )
        user_id = user_reg["user_id"]

        # Upgrade to Pro
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE profiles SET plan = 'pro' WHERE id = ?", (user_id,))
        
        # Insert sample transactions
        cursor.execute("SELECT id FROM wallets WHERE user_id = ? LIMIT 1", (user_id,))
        w_id = cursor.fetchone()[0]

        cursor.execute("SELECT id FROM categories WHERE user_id = ? AND type = 'expense' LIMIT 1", (user_id,))
        c_id = cursor.fetchone()[0]

        cursor.execute(f"""
        INSERT INTO transactions (id, user_id, wallet_id, category_id, type, amount, note, transaction_date, source, created_at)
        VALUES ('tx-pdf-1-{u_suffix}', ?, ?, ?, 'expense', 45000, 'Makan siang ayam geprek enak', '2026-10-17 12:30:00', 'web', '2026-10-17 12:30:00'),
               ('tx-pdf-2-{u_suffix}', ?, ?, NULL, 'income', 5000000, 'Gaji freelance bulanan', '2026-10-17 09:00:00', 'web', '2026-10-17 09:00:00')
        """, (user_id, w_id, c_id, user_id, w_id))
        conn.commit()
        conn.close()

        # 2. Test generate_pdf_report service directly
        pdf_filename = ReportService.generate_pdf_report(
            user_id=user_id,
            start_date="2026-10-01",
            end_date="2026-10-31",
            category_id=c_id,
            wallet_id=w_id,
            tx_type="expense"
        )
        assert pdf_filename.endswith(".pdf")
        pdf_path = os.path.join(STORAGE_DIR, pdf_filename)
        assert os.path.exists(pdf_path), f"File PDF {pdf_path} harus berhasil dibuat di disk!"
        assert os.path.getsize(pdf_path) > 1000, "Ukuran file PDF harus valid (> 1KB)"

        # 3. Test API POST /api/reports/export/pdf
        token = create_access_token({"sub": user_id, "email": test_email, "role": "user", "plan": "pro"})
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post("/api/reports/export/pdf", json={
            "start_date": "2026-10-01",
            "end_date": "2026-10-31"
        }, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        api_pdf = data["file_name"]
        download_url = data["download_url"]

        # 4. Test API GET /api/reports/download/{file_name}
        down_res = client.get(download_url)
        assert down_res.status_code == 200
        assert down_res.headers.get("content-type") == "application/pdf"
        assert f'attachment; filename="{api_pdf}"' in down_res.headers.get("content-disposition", "")
        assert len(down_res.content) > 1000

        # 5. Test Starter User Rejection
        starter_id = f"starter-{u_suffix}"
        starter_token = create_access_token({"sub": starter_id, "email": f"starter_{u_suffix}@tatadana.id", "role": "user", "plan": "starter"})
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO profiles (id, email, password_hash, full_name, plan) VALUES (?, ?, 'hash', 'Starter User', 'starter')", (starter_id, f"starter_{u_suffix}@tatadana.id"))
        conn.commit()
        conn.close()

        reject_res = client.post("/api/reports/export/pdf", json={}, headers={"Authorization": f"Bearer {starter_token}"})
        assert reject_res.status_code == 403
        assert "eksklusif untuk pengguna paket Pro" in reject_res.json()["detail"]

    def test_02_avatar_upload_and_validation(self):
        """
        Uji Fitur 2: Upload / Edit Foto Profil User
        - Validasi format file gambar (JPG, PNG, WebP vs invalid)
        - Validasi ukuran file (<= 2MB vs > 2MB)
        - Penyimpanan ke Supabase Storage / Fallback Lokal
        - Update kolom avatar_url di tabel profiles
        """
        import io
        import uuid
        import random

        u_suffix = uuid.uuid4().hex[:6]
        user_reg = AuthService.register_user(
            email=f"avatar_tester_{u_suffix}@tatadana.id",
            password="password123",
            full_name="Avatar Tester",
            phone_number=f"0818{random.randint(10000000, 99999999)}"
        )
        user_id = user_reg["user_id"]
        token = create_access_token({"sub": user_id, "email": f"avatar_tester_{u_suffix}@tatadana.id", "role": "user", "plan": "starter"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Test Valid PNG Upload
        fake_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (b"\x00" * 100)
        files = {
            "file": ("profile.png", io.BytesIO(fake_png_bytes), "image/png")
        }
        res = client.post("/api/settings/avatar", files=files, headers=headers)
        assert res.status_code == 200, f"Upload avatar valid gagal: {res.text}"
        data = res.json()
        assert data["success"] is True
        assert "avatar_url" in data
        avatar_url = data["avatar_url"]
        assert "avatar_" in avatar_url

        # Check database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT avatar_url FROM profiles WHERE id = ?", (user_id,))
        saved_avatar = cursor.fetchone()[0]
        conn.close()
        assert saved_avatar == avatar_url

        # 2. Test Invalid MIME Type (e.g. text/plain or pdf)
        bad_files = {
            "file": ("document.pdf", io.BytesIO(b"%PDF-1.4 fake pdf"), "application/pdf")
        }
        bad_res = client.post("/api/settings/avatar", files=bad_files, headers=headers)
        assert bad_res.status_code == 400
        assert "Format file tidak didukung" in bad_res.json()["detail"]

        # 3. Test File Size Exceeded (> 2MB)
        oversized_bytes = b"\x89PNG" + (b"\x00" * (2 * 1024 * 1024 + 100))
        oversized_files = {
            "file": ("huge.png", io.BytesIO(oversized_bytes), "image/png")
        }
        oversized_res = client.post("/api/settings/avatar", files=oversized_files, headers=headers)
        assert oversized_res.status_code == 400
        assert "melebihi batas maksimum 2MB" in oversized_res.json()["detail"]

        # 4. Test Unauthorized Upload
        unauth_res = client.post("/api/settings/avatar", files=files)
        assert unauth_res.status_code == 401

    def test_03_calendar_and_daily_notes(self):
        """
        Uji Fitur 3: Kalender Transaksi Interaktif & Catatan Harian (Daily Notes)
        - Agregasi pemasukan/pengeluaran bulanan per tanggal
        - Simpan, ambil, dan perbarui catatan harian (mood & note_text)
        - Hapus catatan harian
        - Endpoint API GET /api/calendar/month, /day, POST /note, DELETE /note
        - Render template halaman /dashboard/kalender
        """
        import uuid
        import random
        from app.services.calendar_service import CalendarService

        u_suffix = uuid.uuid4().hex[:6]
        user_reg = AuthService.register_user(
            email=f"cal_tester_{u_suffix}@tatadana.id",
            password="password123",
            full_name="Calendar Tester",
            phone_number=f"0817{random.randint(10000000, 99999999)}"
        )
        user_id = user_reg["user_id"]
        token = create_access_token({"sub": user_id, "email": f"cal_tester_{u_suffix}@tatadana.id", "role": "user", "plan": "starter"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Insert sample transactions on 2026-10-15 and 2026-10-17
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM wallets WHERE user_id = ? LIMIT 1", (user_id,))
        w_id = cursor.fetchone()[0]

        cursor.execute(f"""
        INSERT INTO transactions (id, user_id, wallet_id, type, amount, note, transaction_date, source, created_at)
        VALUES ('cal-tx-1-{u_suffix}', ?, ?, 'expense', 75000, 'Belanja mingguan', '2026-10-15 10:00:00', 'web', '2026-10-15 10:00:00'),
               ('cal-tx-2-{u_suffix}', ?, ?, 'income', 250000, 'Bonus cashback', '2026-10-15 14:00:00', 'web', '2026-10-15 14:00:00'),
               ('cal-tx-3-{u_suffix}', ?, ?, 'expense', 50000, 'Makan malam', '2026-10-17 19:00:00', 'web', '2026-10-17 19:00:00')
        """, (user_id, w_id, user_id, w_id, user_id, w_id))
        conn.commit()
        conn.close()

        # 2. Test CalendarService.get_month_calendar_data
        cal_data = CalendarService.get_month_calendar_data(user_id, 2026, 10)
        assert cal_data["year"] == 2026
        assert cal_data["month"] == 10
        assert cal_data["num_days"] == 31
        assert cal_data["total_income"] == 250000
        assert cal_data["total_expense"] == 125000
        assert cal_data["net_cashflow"] == 125000

        day_15 = cal_data["days"]["2026-10-15"]
        assert day_15["income"] == 250000
        assert day_15["expense"] == 75000
        assert day_15["tx_count"] == 2

        # 3. Test Daily Note CRUD via CalendarService
        saved_note = CalendarService.save_daily_note(user_id, "2026-10-15", "Hari yang hemat dan menyenangkan!", "saving")
        assert saved_note["note_text"] == "Hari yang hemat dan menyenangkan!"
        assert saved_note["mood"] == "saving"

        # Verify appears in day details
        day_detail = CalendarService.get_day_details(user_id, "2026-10-15")
        assert day_detail["note"] is not None
        assert day_detail["note"]["note_text"] == "Hari yang hemat dan menyenangkan!"
        assert len(day_detail["transactions"]) == 2

        # 4. Test API Endpoints
        # GET /api/calendar/month
        month_res = client.get("/api/calendar/month?year=2026&month=10", headers=headers)
        assert month_res.status_code == 200
        assert month_res.json()["data"]["total_income"] == 250000

        # GET /api/calendar/day
        day_res = client.get("/api/calendar/day?date=2026-10-15", headers=headers)
        assert day_res.status_code == 200
        assert day_res.json()["data"]["note"]["mood"] == "saving"

        # POST /api/calendar/note
        note_res = client.post("/api/calendar/note", json={
            "date": "2026-10-17",
            "note": "Catatan hari Sabtu santai",
            "mood": "happy"
        }, headers=headers)
        assert note_res.status_code == 200
        assert note_res.json()["data"]["mood"] == "happy"

        # DELETE /api/calendar/note
        del_res = client.delete("/api/calendar/note?date=2026-10-17", headers=headers)
        assert del_res.status_code == 200

        # Verify deleted
        check_del = CalendarService.get_day_details(user_id, "2026-10-17")
        assert check_del["note"] is None

        # 5. Test Web Page Render
        page_res = client.get("/dashboard/kalender", cookies={"tatadana_token": token})
        assert page_res.status_code == 200
        assert "Kalender Transaksi" in page_res.text

    def test_04_tata_ai_chatbot(self):
        """
        Uji Fitur 4: Chatbot Tata AI Terintegrasi di Web Dashboard
        - Context gathering (saldo dompet, ringkasan cashflow, anggaran kategori)
        - Endpoint POST /api/ai/chat/send dengan respon cerdas berbasis data finansial
        - Endpoint GET /api/ai/chat/history untuk memastikan riwayat tersimpan berurutan
        - Endpoint DELETE /api/ai/chat/clear untuk membersihkan riwayat
        - Validasi input kosong (400 atau 422)
        - Pencatatan log interaksi AI di tabel ai_logs
        """
        import uuid
        import random
        u_suffix = uuid.uuid4().hex[:6]
        test_email = f"ai_chat_{u_suffix}@tatadana.id"
        test_phone = f"0812{random.randint(10000000, 99999999)}"

        user_reg = AuthService.register_user(
            email=test_email,
            password="password123",
            full_name="Budi Finansial",
            phone_number=test_phone
        )
        user_id = user_reg["user_id"]
        token = create_access_token({"sub": user_id, "email": test_email, "role": "user", "plan": "pro"})
        headers = {"Authorization": f"Bearer {token}"}

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM wallets WHERE user_id = ? LIMIT 1", (user_id,))
        w_id = cursor.fetchone()[0]

        # Update wallet balance to 3.500.000
        cursor.execute("UPDATE wallets SET balance = 3500000, name = 'BCA Utama' WHERE id = ?", (w_id,))

        # Set budget on a category
        cursor.execute("SELECT id, name FROM categories WHERE user_id = ? AND type = 'expense' LIMIT 1", (user_id,))
        cat_row = cursor.fetchone()
        c_id = cat_row[0]
        c_name = cat_row[1]
        cursor.execute("UPDATE categories SET monthly_budget = 1000000 WHERE id = ?", (c_id,))

        # Add transactions in that category
        cursor.execute(f"""
        INSERT INTO transactions (id, user_id, wallet_id, category_id, type, amount, note, transaction_date, source, created_at)
        VALUES ('ai-tx-1-{u_suffix}', ?, ?, ?, 'expense', 450000, 'Belanja bulanan hemat', '2026-10-17 10:00:00', 'web', '2026-10-17 10:00:00'),
               ('ai-tx-2-{u_suffix}', ?, ?, NULL, 'income', 5000000, 'Gaji bulanan', '2026-10-17 08:00:00', 'web', '2026-10-17 08:00:00')
        """, (user_id, w_id, c_id, user_id, w_id))
        conn.commit()
        conn.close()

        # 1. Test get_financial_context directly
        ctx = AIService.get_financial_context(user_id)
        assert ctx["full_name"] == "Budi Finansial"
        assert ctx["first_name"] == "Budi"
        assert ctx["total_balance"] == 3500000
        assert len(ctx["budgets"]) >= 1

        # 2. Test Greeting inquiry
        res_greet = client.post("/api/ai/chat/send", json={"message": "Halo siapa kamu?"}, headers=headers)
        assert res_greet.status_code == 200
        data_greet = res_greet.json()
        assert data_greet["success"] is True
        assert "Tata AI" in data_greet["reply"]

        # 3. Test Saldo inquiry (context awareness)
        res_bal = client.post("/api/ai/chat/send", json={"message": "Berapa total saldo dompet saya?"}, headers=headers)
        assert res_bal.status_code == 200
        data_bal = res_bal.json()
        assert "3,500,000" in data_bal["reply"] or "3.500.000" in data_bal["reply"] or "BCA Utama" in data_bal["reply"]

        # 4. Test Budget inquiry
        res_bud = client.post("/api/ai/chat/send", json={"message": "Bagaimana status sisa budget saya?"}, headers=headers)
        assert res_bud.status_code == 200
        assert "Anggaran Kategori" in res_bud.json()["reply"] or "budget" in res_bud.json()["reply"].lower()

        # 5. Test Tips inquiry
        res_tips = client.post("/api/ai/chat/send", json={"message": "Beri saya tips hemat minggu ini"}, headers=headers)
        assert res_tips.status_code == 200
        assert "50/30/20" in res_tips.json()["reply"]

        # 6. Test GET /api/ai/chat/history
        res_hist = client.get("/api/ai/chat/history", headers=headers)
        assert res_hist.status_code == 200
        hist_data = res_hist.json()
        assert hist_data["success"] is True
        messages = hist_data["messages"]
        # 4 interactions * 2 = 8 messages (user + assistant)
        assert len(messages) >= 8
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        # 7. Test Empty message validation
        res_err = client.post("/api/ai/chat/send", json={"message": "   "}, headers=headers)
        assert res_err.status_code in [400, 422]

        # 8. Test DELETE /api/ai/chat/clear
        res_clear = client.delete("/api/ai/chat/clear", headers=headers)
        assert res_clear.status_code == 200
        assert res_clear.json()["success"] is True

        # Verify history is now empty
        res_empty = client.get("/api/ai/chat/history", headers=headers)
        assert len(res_empty.json()["messages"]) == 0

        # 9. Verify ai_logs recorded calls
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ai_logs WHERE user_id = ? AND source = 'web_dashboard_chat'", (user_id,))
        log_count = cursor.fetchone()[0]
        conn.close()
        assert log_count >= 4

    def test_05_admin_rbac_and_whatsapp_otp(self):
        """
        Uji Fitur 5: Proteksi Route Admin Panel (RBAC) & Verifikasi WhatsApp OTP
        - Proteksi RBAC: Pengguna umum tidak dapat mengakses web /admin (redirect /dashboard?error=admin_only)
        - Proteksi RBAC API: Pengguna umum mendapat 403 Forbidden pada /api/admin/*
        - Superadmin dapat mengakses web /admin dan /api/admin/* dengan status 200 OK
        - WhatsApp OTP: Endpoint kirim OTP via WhatsApp (POST /api/auth/send-whatsapp-otp)
        - WhatsApp OTP: Verifikasi kode OTP (POST /api/auth/verify-whatsapp-otp)
        - Proteksi & render halaman standalone /verify-otp
        """
        import uuid
        import random
        u_suffix = uuid.uuid4().hex[:6]
        user_email = f"regular_user_{u_suffix}@tatadana.id"
        admin_email = f"superadmin_{u_suffix}@tatadana.id"
        user_phone = f"0813{random.randint(10000000, 99999999)}"

        # 1. Register regular user
        user_reg = AuthService.register_user(
            email=user_email,
            password="password123",
            full_name="User Biasa",
            phone_number=user_phone
        )
        user_id = user_reg["user_id"]
        user_token = create_access_token({"sub": user_id, "email": user_email, "role": "user", "plan": "starter"})
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 2. Setup Superadmin
        admin_id = f"admin-{u_suffix}"
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, role, plan, is_admin, phone_verified)
        VALUES (?, ?, 'dummy_hash', 'Admin Utama', 'superadmin', 'pro', 1, 1)
        """, (admin_id, admin_email))
        conn.commit()
        conn.close()

        admin_token = create_access_token({"sub": admin_id, "email": admin_email, "role": "superadmin", "plan": "pro"})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # --- A. RBAC Web Route Protection ---
        # 1. Unauthenticated request to /admin -> Redirect to /login
        unauth_res = client.get("/admin", follow_redirects=False)
        assert unauth_res.status_code == 302
        assert "/login" in unauth_res.headers.get("location", "")

        # 2. Regular user request to /admin -> Redirect to /dashboard?error=admin_only
        user_web_res = client.get("/admin", cookies={"tatadana_token": user_token}, follow_redirects=False)
        assert user_web_res.status_code == 302
        assert "/dashboard?error=admin_only" in user_web_res.headers.get("location", "")

        # 3. Regular user request to /admin/users -> Redirect to /dashboard?error=admin_only
        user_subadmin_res = client.get("/admin/users", cookies={"tatadana_token": user_token}, follow_redirects=False)
        assert user_subadmin_res.status_code == 302
        assert "/dashboard?error=admin_only" in user_subadmin_res.headers.get("location", "")

        # 4. Superadmin request to /admin -> 200 OK
        admin_web_res = client.get("/admin", cookies={"tatadana_token": admin_token})
        assert admin_web_res.status_code == 200
        assert "TataDana" in admin_web_res.text
        assert "Superadmin" in admin_web_res.text

        # --- B. RBAC API Route Protection ---
        # 1. Regular user accessing /api/admin/users -> 403 Forbidden
        api_forbidden_res = client.get("/api/admin/users", headers=user_headers)
        assert api_forbidden_res.status_code == 403
        assert "Akses khusus Administrator" in api_forbidden_res.json().get("detail", "")

        # 2. Superadmin accessing /api/admin/users -> 200 OK
        api_ok_res = client.get("/api/admin/users", headers=admin_headers)
        assert api_ok_res.status_code == 200
        assert "data" in api_ok_res.json()

        # --- C. WhatsApp OTP Verification Flow ---
        # Check initial state: phone_verified == 0
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_verified FROM profiles WHERE id = ?", (user_id,))
        assert cursor.fetchone()[0] == 0
        conn.close()

        # 1. Request new WhatsApp OTP
        wa_res = client.post("/api/auth/send-whatsapp-otp", json={"user_id": user_id})
        assert wa_res.status_code == 200
        wa_data = wa_res.json()
        assert wa_data["success"] is True
        assert "WhatsApp" in wa_data["message"]
        otp_code = wa_data["otp_preview"]
        assert len(otp_code) == 6

        # 2. Test send WhatsApp OTP using phone number
        wa_phone_res = client.post("/api/auth/send-whatsapp-otp", json={"phone_number": user_phone})
        assert wa_phone_res.status_code == 200
        new_otp = wa_phone_res.json()["otp_preview"]
        assert len(new_otp) == 6

        # 3. Test Invalid OTP verification
        bad_res = client.post("/api/auth/verify-whatsapp-otp", json={"user_id": user_id, "otp_code": "000000"})
        assert bad_res.status_code == 400
        assert "tidak cocok" in bad_res.json().get("detail", "")

        # 4. Test Valid OTP verification
        good_res = client.post("/api/auth/verify-whatsapp-otp", json={"user_id": user_id, "otp_code": new_otp})
        assert good_res.status_code == 200
        assert good_res.json()["phone_verified"] is True

        # Verify database state after verification
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_verified, otp_code FROM profiles WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        assert row["phone_verified"] == 1
        assert row["otp_code"] is None

        # 5. Test /verify-otp page redirection once verified
        verify_page_res = client.get("/verify-otp", cookies={"tatadana_token": user_token}, follow_redirects=False)
        assert verify_page_res.status_code in [302, 307]
        assert "/dashboard" in verify_page_res.headers.get("location", "")

    def test_06_admin_user_detail_and_auto_recording(self):
        """
        Uji Fitur 6: Tabel user baru otomatis tercatat di Admin Panel dan
        Admin Dashboard bisa melihat detail profil user yang terdaftar:
        1. Pendaftaran user baru langsung tercatat di tabel admin (list_users).
        2. Superadmin dapat mengambil detail profil lengkap via GET /api/admin/users/{user_id}/detail.
        3. Validasi isi detail: profile, telegram status, dompet & total saldo, kategori & budget, summary transaksi, status paket langganan.
        4. Keamanan RBAC: User biasa 403 Forbidden, Unauth 401 Unauthorized.
        5. Pemeriksaan elemen UI Admin (Modal detail profil, tombol Lihat Profil, WhatsApp badge).
        """
        import uuid
        import random

        u_suffix = uuid.uuid4().hex[:6]
        admin_email = f"superadmin_feat6_{u_suffix}@tatadana.id"
        admin_id = f"admin-f6-{u_suffix}"

        # 1. Setup Superadmin
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, role, plan, is_admin, phone_verified)
        VALUES (?, ?, 'dummy_hash', 'Superadmin TataDana', 'superadmin', 'pro', 1, 1)
        """, (admin_id, admin_email))
        conn.commit()
        conn.close()

        admin_token = create_access_token({"sub": admin_id, "email": admin_email, "role": "superadmin", "plan": "pro"})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Register a brand new user
        new_user_email = f"auto_user_{u_suffix}@tatadana.id"
        new_user_phone = f"0812{random.randint(10000000, 99999999)}"
        new_user_name = f"User Terdaftar Otomatis {u_suffix}"

        reg_res = AuthService.register_user(
            email=new_user_email,
            password="password123",
            full_name=new_user_name,
            phone_number=new_user_phone
        )
        new_user_id = reg_res["user_id"]
        assert new_user_id is not None

        new_user_token = create_access_token({"sub": new_user_id, "email": new_user_email, "role": "user", "plan": "starter"})
        new_user_headers = {"Authorization": f"Bearer {new_user_token}"}

        # 3. Check auto-recording in Admin Users Table API
        list_res = client.get("/api/admin/users", headers=admin_headers)
        assert list_res.status_code == 200
        users_list = list_res.json()["data"]
        assert len(users_list) > 0

        # Newly registered user should be near the top (ORDER BY created_at DESC)
        matched_user = next((u for u in users_list if u["id"] == new_user_id), None)
        assert matched_user is not None, "User baru harus otomatis muncul di database admin users!"
        assert matched_user["full_name"] == new_user_name
        assert matched_user["email"] == new_user_email
        assert matched_user["phone_number"] == new_user_phone
        assert matched_user["phone_verified"] == 0

        # 4. Search user by name or phone
        search_res = client.get(f"/api/admin/users?q={new_user_name}", headers=admin_headers)
        assert search_res.status_code == 200
        search_data = search_res.json()["data"]
        assert any(u["id"] == new_user_id for u in search_data)

        # 5. Enrich user data for detail test (add telegram link, subscription, transactions)
        conn = get_db()
        cursor = conn.cursor()

        tg_uid = str(random.randint(200000000, 999999999))
        order_id = f"ORDER-TEST-{u_suffix}"

        # Link Telegram
        cursor.execute("""
        INSERT INTO telegram_links (id, user_id, telegram_user_id, telegram_chat_id, telegram_username, is_active, created_at)
        VALUES (?, ?, ?, ?, 'tester_tg_bot', 1, '2026-10-17 12:00:00')
        """, (str(uuid.uuid4()), new_user_id, tg_uid, tg_uid))

        # Add subscription
        cursor.execute("""
        INSERT INTO subscriptions (id, user_id, plan, status, payment_type, order_id, gross_amount, is_approved, created_at)
        VALUES (?, ?, 'pro', 'settlement', 'qris', ?, 49000, 1, '2026-10-17 12:05:00')
        """, (str(uuid.uuid4()), new_user_id, order_id))

        # Get wallet & category
        cursor.execute("SELECT id FROM wallets WHERE user_id = ? LIMIT 1", (new_user_id,))
        w_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM categories WHERE user_id = ? LIMIT 1", (new_user_id,))
        c_id = cursor.fetchone()[0]

        # Insert 2 transactions (income 500,000 and expense 150,000)
        cursor.execute("""
        INSERT INTO transactions (id, user_id, wallet_id, category_id, type, amount, note, transaction_date, source, created_at)
        VALUES (?, ?, ?, ?, 'income', 500000, 'Gaji Freelance', '2026-10-17 10:00:00', 'web', '2026-10-17 10:00:00'),
               (?, ?, ?, ?, 'expense', 150000, 'Belanja Perlengkapan', '2026-10-17 11:30:00', 'web', '2026-10-17 11:30:00')
        """, (f"tx-f6-1-{u_suffix}", new_user_id, w_id, c_id,
              f"tx-f6-2-{u_suffix}", new_user_id, w_id, c_id))

        # Update wallet balance
        cursor.execute("UPDATE wallets SET balance = 350000 WHERE id = ?", (w_id,))
        conn.commit()
        conn.close()

        # 6. Call GET /api/admin/users/{user_id}/detail
        detail_res = client.get(f"/api/admin/users/{new_user_id}/detail", headers=admin_headers)
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["success"] is True

        # Verify Profile
        prof = detail_data["profile"]
        assert prof["id"] == new_user_id
        assert prof["full_name"] == new_user_name
        assert prof["email"] == new_user_email

        # Verify Telegram Link
        tg = detail_data["telegram"]
        assert tg["is_active"] == 1
        assert tg["telegram_username"] == "tester_tg_bot"
        assert str(tg["telegram_user_id"]) == str(tg_uid)

        # Verify Wallets
        wallets = detail_data["wallets"]
        assert len(wallets) >= 1
        assert detail_data["total_balance"] == 350000

        # Verify Categories
        categories = detail_data["categories"]
        assert len(categories) >= 1

        # Verify Financial Summary
        summary = detail_data["financial_summary"]
        assert summary["total_count"] == 2
        assert summary["total_income"] == 500000
        assert summary["total_expense"] == 150000
        assert summary["net_cashflow"] == 350000

        # Verify Subscription
        sub = detail_data["subscription"]
        assert sub is not None
        assert sub["plan"] == "pro"
        assert sub["order_id"] == order_id
        assert sub["is_approved"] == 1

        # Verify Recent Transactions
        recents = detail_data["recent_transactions"]
        assert len(recents) == 2
        assert any(t["note"] == "Gaji Freelance" for t in recents)

        # 7. Test Security & RBAC
        # Regular user trying to view user detail -> 403 Forbidden
        user_attempt_res = client.get(f"/api/admin/users/{new_user_id}/detail", headers=new_user_headers)
        assert user_attempt_res.status_code == 403
        assert "Akses khusus Administrator" in user_attempt_res.json().get("detail", "")

        # Unauthenticated request -> 401 Unauthorized
        unauth_detail_res = client.get(f"/api/admin/users/{new_user_id}/detail")
        assert unauth_detail_res.status_code == 401

        # Non-existent user -> 404 Not Found
        non_existent_res = client.get("/api/admin/users/non-existent-user-id/detail", headers=admin_headers)
        assert non_existent_res.status_code == 404

        # 8. Test Admin Users Web Page contains user-detail-modal and viewUserDetail
        web_res = client.get("/admin/users", cookies={"tatadana_token": admin_token})
        assert web_res.status_code == 200
        assert "user-detail-modal" in web_res.text
        assert "viewUserDetail" in web_res.text
        assert "Lihat Profil" in web_res.text
        assert "WA Verified" in web_res.text

    def test_07_telegram_deep_link_flow(self):
        """
        Uji Alur Penautan Telegram Berformat Deep-Link:
        1. POST /api/telegram/generate-pairing-code menghasilkan deep-link berformat:
           https://t.me/TataDanaFinanceBot?start={link_token}
        2. Periksa ketersediaan tombol 'Hubungkan ke Telegram' di halaman Pengaturan & Dashboard.
        3. Simulasi webhook Telegram menerima /start {link_token} dan menautkan akun pengguna secara otomatis.
        """
        import uuid
        import random
        from app.services.telegram_service import TelegramService

        u_suffix = uuid.uuid4().hex[:6]
        user_email = f"tg_deeplink_{u_suffix}@tatadana.id"
        user_phone = f"0818{random.randint(10000000, 99999999)}"

        # 1. Register User
        reg_res = AuthService.register_user(
            email=user_email,
            password="password123",
            full_name="DeepLink Tester",
            phone_number=user_phone
        )
        user_id = reg_res["user_id"]
        token = create_access_token({"sub": user_id, "email": user_email, "role": "user", "plan": "starter"})
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Call generate pairing code
        gen_res = client.post("/api/telegram/generate-pairing-code", headers=headers)
        assert gen_res.status_code == 200
        data = gen_res.json()["data"]

        link_token = data["link_token"]
        deep_link = data["deep_link"]
        bot_username = data["bot_username"]

        assert bot_username == "TataDanaFinanceBot"
        assert link_token.startswith("TD-")
        expected_deep_link = f"https://t.me/TataDanaFinanceBot?start={link_token}"
        assert deep_link == expected_deep_link

        # 3. Verify HTML templates contain the deep link buttons and handler functions
        # A. Settings Page
        settings_res = client.get("/dashboard/settings?tab=telegram", cookies={"tatadana_token": token})
        assert settings_res.status_code == 200
        assert "Hubungkan ke Telegram" in settings_res.text
        assert "TataDanaFinanceBot" in settings_res.text
        assert "handleConnectTelegram" in settings_res.text
        assert "btn-deep-link" in settings_res.text

        # B. Dashboard / Beranda Page
        beranda_res = client.get("/dashboard", cookies={"tatadana_token": token})
        assert beranda_res.status_code == 200
        assert "Hubungkan ke Telegram" in beranda_res.text
        assert "modal-telegram-connect" in beranda_res.text
        assert "connectTelegramDeepLink" in beranda_res.text
        assert "TataDanaFinanceBot" in beranda_res.text

        # 4. Simulate Telegram Webhook sending /start {link_token}
        tg_user_id = random.randint(300000000, 999999999)
        webhook_payload = {
            "update_id": random.randint(1000000, 9999999),
            "message": {
                "message_id": 1,
                "from": {"id": tg_user_id, "username": f"user_dl_{u_suffix}"},
                "chat": {"id": tg_user_id, "type": "private"},
                "text": f"/start {link_token}"
            }
        }

        hook_res = client.post(
            "/api/telegram/webhook",
            json=webhook_payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
        )
        assert hook_res.status_code == 200
        hook_data = hook_res.json()
        assert hook_data["status"] == "success"
        assert hook_data["action"] == "account_paired"
        assert hook_data["user_id"] == user_id

        # 5. Verify /api/telegram/status reports user is linked
        status_res = client.get("/api/telegram/status", headers=headers)
        assert status_res.status_code == 200
        st_data = status_res.json()["data"]
        assert st_data["is_user_linked"] is True
        assert st_data["user_link"]["telegram_username"] == f"user_dl_{u_suffix}"


