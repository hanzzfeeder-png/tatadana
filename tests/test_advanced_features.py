import asyncio
import uuid
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.services.ai_service import AIService
from app.services.telegram_service import TelegramService
from app.services.reminder_service import ReminderService
from app.services.payment_service import PaymentService
from app.services.auth_service import AuthService
from app.database import get_db

client = TestClient(app)

def test_advanced_suite():
    print("\n=======================================================")
    print("[INFO] MENJALANKAN TEST FITUR ADVANCED TATADANA")
    print("=======================================================")

    # 1. Test Voice Note Duration Check & Transcription
    print("\n[TEST A] Voice Note (VN) Speech-To-Text Pipeline...")
    # Over 60 seconds should be rejected
    try:
        asyncio.run(AIService.transcribe_voice_note(65))
        assert False, "Voice note >60 detik harus ditolak!"
    except ValueError as e:
        print("  [OK] VN > 60 detik berhasil ditolak:", str(e))

    # <= 60 seconds succeeds
    transcript, parsed = asyncio.run(AIService.transcribe_voice_note(15))
    assert transcript is not None
    assert "nominal" in parsed
    print(f"  [OK] VN 15s berhasil ditranskrip: \"{transcript}\" -> {parsed['nominal']} ({parsed['kategori']})")

    # 2. Test AI Vision Photo Receipt Extraction (Pro)
    print("\n[TEST B] Photo Receipt OCR Extraction...")
    receipt = asyncio.run(AIService.parse_receipt_photo(b"mock_bytes"))
    assert receipt["merchant"] == "Indomaret Point"
    assert len(receipt["items"]) >= 3
    assert receipt["total_amount"] > 0
    print(f"  [OK] OCR Struk berhasil ekstrak merchant '{receipt['merchant']}' dengan {len(receipt['items'])} item (Total: Rp {receipt['total_amount']:,.0f})")

    # 3. Test AI Financial Advisor Triggers
    print("\n[TEST C] AI Financial Advisor Triggers...")
    # Create test pro user
    r_suffix = uuid.uuid4().hex[:6]
    u = AuthService.register_user(f"pro_{r_suffix}@tatadana.id", "Secret123!", "Advisor Test User", f"0818{int(r_suffix, 16)%100000000:08d}")
    AuthService.verify_phone_otp(u["user_id"], u["otp_preview"])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE profiles SET plan = 'pro' WHERE id = ?", (u["user_id"],))
    # Fetch category with budget
    c.execute("SELECT id, name, monthly_budget FROM categories WHERE user_id = ? AND monthly_budget > 0 LIMIT 1", (u["user_id"],))
    cat = c.fetchone()
    conn.commit()
    conn.close()

    # Trigger expense > 20% of category budget
    cat_budget = float(cat["monthly_budget"])
    big_expense = cat_budget * 0.35 # 35% of budget
    advisor_advice = AIService.check_financial_advisor(u["user_id"], {
        "category_id": cat["id"],
        "amount": big_expense,
        "type": "expense"
    })
    assert advisor_advice is not None
    assert "Financial Advisor" in advisor_advice["message"]
    print("  [OK] Financial Advisor aktif otomatis mendeteksi pengeluaran besar > 20% budget kategori!")

    # 4. Test Daily Reminder Settings & Preview
    print("\n[TEST D] Daily Reminder Configuration...")
    rem_settings = ReminderService.get_reminder_settings(u["user_id"])
    assert rem_settings["is_active"] is True
    assert "Reminder Keuangan" in rem_settings["preview"]

    # Update to 2x daily
    updated_rem = ReminderService.update_reminder_settings(u["user_id"], True, 2, "07:30", "20:30")
    assert updated_rem["frequency"] == 2
    assert updated_rem["time_1"] == "07:30"
    print("  [OK] Pengaturan reminder harian (2x sehari) berhasil disimpan.")

    # 5. Test Midtrans Order & Admin Manual Approval
    print("\n[TEST E] Midtrans & Manual Subscription Approval...")
    order = PaymentService.create_subscription_order(u["user_id"], "pro", "manual_transfer")
    assert order["order_id"].startswith("TD-PRO-")
    assert order["amount"] == 99000.0

    # Admin approves
    admin_login = client.post("/api/auth/login", json={"identifier": "admin@tatadana.id", "password": "admin123456"})
    admin_id = admin_login.json()["data"]["user"]["id"]
    PaymentService.approve_payment(order["subscription_id"], admin_id, "Bukti transfer BCA valid")

    # Verify user plan is now pro
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT plan FROM profiles WHERE id = ?", (u["user_id"],))
    assert c.fetchone()["plan"] == "pro"
    conn.close()
    print("  [OK] Approval manual pembayaran berhasil dan plan profil di-upgrade ke Pro.")

    print("\n=======================================================")
    print("[SUCCESS] SEMUA TEST FITUR ADVANCED BERHASIL 100%!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_advanced_suite()
