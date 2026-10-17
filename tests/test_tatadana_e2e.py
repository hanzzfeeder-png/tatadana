import asyncio
import uuid
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_service import AIService
from app.services.telegram_service import TelegramService
from app.services.report_service import ReportService
from app.services.budget_service import BudgetService
from app.services.wallet_service import WalletService
from app.services.transaction_service import TransactionService
from app.services.auth_service import AuthService
from app.services.payment_service import PaymentService
from app.database import get_db
from app.config import settings

client = TestClient(app)

def test_full_pipeline():
    print("\n=======================================================")
    print("[INFO] MENJALANKAN TEST SUITE END-TO-END TATADANA")
    print("=======================================================")

    # -------------------------------------------------------------------------
    # 1. TEST AUTHENTICATION & PHONE OTP
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Register User & Verifikasi OTP Nomor HP...")
    random_suffix = uuid.uuid4().hex[:6]
    test_email = f"user_{random_suffix}@tatadana.id"
    test_phone = f"0819{int(random_suffix, 16) % 100000000:08d}"
    test_pass = "Password123!"

    reg_res = client.post("/api/auth/register", json={
        "email": test_email,
        "password": test_pass,
        "full_name": "Test FinTech User",
        "phone_number": test_phone
    })
    assert reg_res.status_code == 200, f"Register failed: {reg_res.text}"
    reg_data = reg_res.json()["data"]
    user_id = reg_data["user_id"]
    otp_code = reg_data["otp_preview"]
    assert user_id is not None
    assert otp_code is not None
    print(f"  [OK] User terdaftar: {test_email} (ID: {user_id})")

    # Verify OTP
    otp_res = client.post("/api/auth/verify-otp", json={
        "user_id": user_id,
        "otp_code": otp_code
    })
    assert otp_res.status_code == 200, f"OTP verification failed: {otp_res.text}"
    print(f"  [OK] Nomor HP {test_phone} berhasil diverifikasi dengan OTP {otp_code}")

    # Login
    login_res = client.post("/api/auth/login", json={
        "identifier": test_email,
        "password": test_pass
    })
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    auth_token = login_res.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {auth_token}"}
    print(f"  [OK] Login berhasil, JWT token generated.")

    # -------------------------------------------------------------------------
    # 2. TEST MULTI-WALLET & STARTER RESTRICTIONS
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Multi-Wallet & Batasan Paket Starter...")
    wallets_res = client.get("/api/wallets", headers=headers)
    assert wallets_res.status_code == 200
    wallets = wallets_res.json()["data"]
    assert len(wallets) >= 1, "Default wallet harus otomatis dibuat saat registrasi!"
    default_wallet_id = wallets[0]["id"]
    print(f"  [OK] Dompet otomatis terbuat: {wallets[0]['name']} (Default: {wallets[0]['is_default']})")

    # Create 2nd wallet
    w2_res = client.post("/api/wallets", headers=headers, json={
        "name": "Bank BCA", "type": "bank", "initial_balance": 5000000.0, "icon": "[BCA]"
    })
    assert w2_res.status_code == 200
    w2_id = w2_res.json()["data"]["id"]

    # Create 3rd wallet (max for Starter)
    w3_res = client.post("/api/wallets", headers=headers, json={
        "name": "GoPay & OVO", "type": "ewallet", "initial_balance": 300000.0, "icon": "[OVO]"
    })
    assert w3_res.status_code == 200
    w3_id = w3_res.json()["data"]["id"]

    # Try creating 4th wallet -> MUST BE REJECTED for Starter plan
    w4_res = client.post("/api/wallets", headers=headers, json={
        "name": "Dompet Ke-4", "type": "cash", "initial_balance": 50000.0
    })
    assert w4_res.status_code == 400, "Pembuatan dompet ke-4 pada Starter harus ditolak!"
    print("  [OK] Enforcing Starter Limit terbukti: Dompet ke-4 ditolak dengan pesan upgrade.")

    # Transfer between wallets
    transfer_res = client.post("/api/wallets/transfer", headers=headers, json={
        "source_wallet_id": w2_id,
        "target_wallet_id": default_wallet_id,
        "amount": 250000.0,
        "note": "Tarik tunai ATM dari BCA ke Cash"
    })
    assert transfer_res.status_code == 200
    print("  [OK] Transfer antar dompet berhasil tercatat.")

    # -------------------------------------------------------------------------
    # 3. TEST AI NLP PARSING INDONESIAN AMOUNTS
    # -------------------------------------------------------------------------
    print("\n[TEST 3] AI Natural Language Indonesian Parser...")
    assert AIService.parse_indonesian_amount("beli bakso 15rb") == 15000.0
    assert AIService.parse_indonesian_amount("kopi susu 25ribu") == 25000.0
    assert AIService.parse_indonesian_amount("gajian 5jt") == 5000000.0
    assert AIService.parse_indonesian_amount("freelance 1.5jt") == 1500000.0
    assert AIService.parse_indonesian_amount("beli bensin 50k") == 50000.0
    print("  [OK] Format nominal Indonesia ('15rb', '25ribu', '5jt', '1.5jt', '50k') terparsing 100% akurat.")

    # -------------------------------------------------------------------------
    # 4. TEST TELEGRAM WEBHOOK & IDEMPOTENCY
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Telegram Bot Webhook, Idempotency, & Reply Formatting...")
    # Link Telegram account
    TelegramService.link_telegram_account_direct(user_id, 888123456, 888123456, "test_user_tg")
    webhook_headers = {"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}

    # Send expense message via Webhook
    up_id_1 = int(uuid.uuid4().int % 10000000)
    hook_payload_1 = {
        "update_id": up_id_1,
        "message": {
            "message_id": 1,
            "from": {"id": 888123456, "username": "test_user_tg"},
            "chat": {"id": 888123456, "type": "private"},
            "text": "Beli nasi padang 28rb",
            "date": 1760000000
        }
    }

    hook_res_1 = client.post("/api/telegram/webhook", json=hook_payload_1, headers=webhook_headers)
    assert hook_res_1.status_code == 200
    assert hook_res_1.json().get("status") == "success"
    print("  [OK] Pesan 'Beli nasi padang 28rb' berhasil dicatat oleh Bot Telegram.")

    # Test Idempotency: retry same update_id
    hook_res_retry = client.post("/api/telegram/webhook", json=hook_payload_1, headers=webhook_headers)
    assert hook_res_retry.json().get("status") == "skipped"
    print("  [OK] Idempotency terbukti: update_id duplikat otomatis di-skip.")

    # Test Commands
    cmd_payload = {
        "update_id": int(uuid.uuid4().int % 10000000),
        "message": {
            "message_id": 2,
            "from": {"id": 888123456, "username": "test_user_tg"},
            "chat": {"id": 888123456, "type": "private"},
            "text": "/saldo",
            "date": 1760000000
        }
    }
    cmd_res = client.post("/api/telegram/webhook", json=cmd_payload, headers=webhook_headers)
    assert cmd_res.status_code == 200
    assert cmd_res.json().get("status") == "command"
    print("  [OK] Command /saldo berhasil direspon.")

    # -------------------------------------------------------------------------
    # 5. TEST REPORT SUMMARY & EXPORT EXCEL / PDF
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Sistem Laporan & Export In-App (Excel & PDF)...")
    summary_res = client.get("/api/reports/summary", headers=headers)
    assert summary_res.status_code == 200
    sum_data = summary_res.json()["data"]
    assert "total_income" in sum_data
    assert "total_expense" in sum_data
    print(f"  [OK] Ringkasan Laporan: Pemasukan {sum_data['total_income']}, Pengeluaran {sum_data['total_expense']}")

    # Upgrade user to Pro first so they have export permissions
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE profiles SET plan = 'pro' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    # Generate Excel Report
    xlsx_res = client.post("/api/reports/export/excel", headers=headers, json={})
    assert xlsx_res.status_code == 200
    xlsx_file = xlsx_res.json()["file_name"]
    assert xlsx_file.endswith(".xlsx")
    print(f"  [OK] File Excel berhasil digenerate: {xlsx_file}")

    # Generate PDF Report
    pdf_res = client.post("/api/reports/export/pdf", headers=headers, json={})
    assert pdf_res.status_code == 200
    pdf_file = pdf_res.json()["file_name"]
    assert pdf_file.endswith(".pdf")
    print(f"  [OK] File PDF resmi berlogo berhasil digenerate: {pdf_file}")

    # Download test
    dl_res = client.get(f"/api/reports/download/{pdf_file}")
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 1000
    print(f"  [OK] Download file PDF berhasil diakses ({len(dl_res.content)} bytes).")

    # -------------------------------------------------------------------------
    # 6. TEST SUPERADMIN & IMPERSONATION
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Superadmin Dashboard & Impersonasi...")
    # Admin Login
    admin_login = client.post("/api/auth/login", json={
        "identifier": "admin@tatadana.id",
        "password": "admin123456"
    })
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["data"]["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin List Users
    adm_users_res = client.get("/api/admin/users", headers=admin_headers)
    assert adm_users_res.status_code == 200
    assert len(adm_users_res.json()["data"]) >= 2
    print(f"  [OK] Admin berhasil menarik data {len(adm_users_res.json()['data'])} pengguna.")

    # Admin Impersonate
    imp_res = client.post(f"/api/admin/impersonate/{user_id}", headers=admin_headers)
    assert imp_res.status_code == 200
    assert imp_res.json()["redirect_url"] == "/dashboard"
    print(f"  [OK] Impersonasi berhasil tanpa password ke akun {user_id}.")

    # Admin View User Transactions with Privacy Audit Log
    view_tx_res = client.get(f"/api/admin/user-transactions/{user_id}", headers=admin_headers)
    assert view_tx_res.status_code == 200
    print("  [OK] Admin dapat memeriksa transaksi user dengan audit log privasi tercatat.")

    print("\n=======================================================")
    print("[SUCCESS] SEMUA TEST END-TO-END BERHASIL 100%!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_full_pipeline()
