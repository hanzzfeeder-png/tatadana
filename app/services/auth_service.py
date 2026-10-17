import uuid
import re
from typing import Dict, Any, Optional
from datetime import timedelta
from app.database import get_db
from app.config import get_wib_now, get_wib_str
from app.security import hash_password, verify_password, create_access_token, generate_otp

class AuthService:
    @staticmethod
    def register_user(email: str, password: str, full_name: str, phone_number: str) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()

        # Check existing email
        cursor.execute("SELECT id FROM profiles WHERE email = ?", (email.lower().strip(),))
        if cursor.fetchone():
            conn.close()
            raise ValueError("Email sudah terdaftar. Silakan login atau gunakan email lain.")

        # Validate password length
        if not password or len(password) < 8:
            conn.close()
            raise ValueError("Password minimal 8 karakter.")

        # Clean and format phone number (Indonesian format 08xxx, +62xxx, or 628xxx)
        clean_phone = re.sub(r'[^0-9]', '', phone_number)
        if clean_phone.startswith('62'):
            clean_phone = '0' + clean_phone[2:]
        if not clean_phone.startswith('08') or len(clean_phone) < 10 or len(clean_phone) > 15:
            conn.close()
            raise ValueError("Nomor WhatsApp tidak valid. Gunakan format nomor Indonesia (contoh: 08123456789 atau +628123456789).")

        cursor.execute("SELECT id FROM profiles WHERE phone_number = ?", (clean_phone,))
        if cursor.fetchone():
            conn.close()
            raise ValueError("Nomor HP sudah terdaftar pada akun lain.")

        user_id = str(uuid.uuid4())
        pwd_hash = hash_password(password)
        now = get_wib_str()
        otp = generate_otp()
        otp_expires = get_wib_str(get_wib_now() + timedelta(minutes=15))

        # Insert Profile
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, phone_number, phone_verified, otp_code, otp_expires_at, plan, role, default_currency, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'starter', 'user', 'IDR', ?, ?)
        """, (user_id, email.lower().strip(), pwd_hash, full_name.strip(), clean_phone, otp, otp_expires, now, now))

        # Auto-provision Default Wallet (Dompet Tunai)
        w_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT INTO wallets (id, user_id, name, type, balance, is_default, icon, color, created_at, updated_at)
        VALUES (?, ?, 'Dompet Tunai', 'cash', 0.0, 1, '👛', '#FF6B00', ?, ?)
        """, (w_id, user_id, now, now))

        # Auto-provision AI Recommended Categories
        default_categories = [
            (str(uuid.uuid4()), user_id, 'Makanan & Minuman', 'expense', '🍜', '#FF6B00', 1500000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Transportasi', 'expense', '🚗', '#3B82F6', 500000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Hiburan & Hobi', 'expense', '🎮', '#8B5CF6', 300000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Tagihan & Utilitas', 'expense', '🏠', '#EF4444', 750000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Kesehatan', 'expense', '💊', '#10B981', 250000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Belanja Kebutuhan', 'expense', '👕', '#F59E0B', 500000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Pendidikan & Buku', 'expense', '📚', '#6366F1', 200000.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Gaji Bulanan', 'income', '💰', '#059669', 0.0, 1, now),
            (str(uuid.uuid4()), user_id, 'Penghasilan Tambahan', 'income', '💼', '#10B981', 0.0, 1, now)
        ]
        cursor.executemany("""
        INSERT INTO categories (id, user_id, name, type, icon, color, monthly_budget, is_system, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_categories)

        # Provision Reminder
        cursor.execute("""
        INSERT INTO reminders (id, user_id, is_active, frequency, time_1, time_2, created_at, updated_at)
        VALUES (?, ?, 1, 1, '20:00', '08:00', ?, ?)
        """, (str(uuid.uuid4()), user_id, now, now))

        conn.commit()
        conn.close()

        token = create_access_token({"sub": user_id, "email": email, "role": "user", "plan": "starter"})
        return {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "phone_number": clean_phone,
            "phone_verified": False,
            "otp_preview": otp, # For development & testing convenience
            "token": token
        }

    @staticmethod
    def verify_phone_otp(user_id: str, otp_code: str) -> bool:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT otp_code, otp_expires_at FROM profiles WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError("Pengguna tidak ditemukan")

        stored_otp = row["otp_code"]
        now = get_wib_str()

        if stored_otp != otp_code.strip():
            conn.close()
            raise ValueError("Kode OTP tidak cocok. Silakan periksa kembali.")

        cursor.execute("""
        UPDATE profiles
        SET phone_verified = 1, otp_code = NULL, otp_expires_at = NULL, updated_at = ?
        WHERE id = ?
        """, (now, user_id))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def resend_otp(user_id: str) -> str:
        conn = get_db()
        cursor = conn.cursor()
        new_otp = generate_otp()
        now = get_wib_str()
        expires = get_wib_str(get_wib_now() + timedelta(minutes=15))
        cursor.execute("""
        UPDATE profiles
        SET otp_code = ?, otp_expires_at = ?, updated_at = ?
        WHERE id = ?
        """, (new_otp, expires, now, user_id))
        conn.commit()
        conn.close()
        return new_otp

    @staticmethod
    def complete_onboarding(user_id: str, selected_categories: Optional[list] = None, wallet_name: Optional[str] = None) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()

        # 1. Pastikan Dompet Default Tersedia
        cursor.execute("SELECT id FROM wallets WHERE user_id = ?", (user_id,))
        existing_wallet = cursor.fetchone()
        if not existing_wallet:
            w_id = str(uuid.uuid4())
            w_name = wallet_name.strip() if wallet_name and wallet_name.strip() else "Dompet Tunai"
            cursor.execute("""
            INSERT INTO wallets (id, user_id, name, type, balance, is_default, icon, color, created_at, updated_at)
            VALUES (?, ?, ?, 'cash', 0.0, 1, '👛', '#FF6B00', ?, ?)
            """, (w_id, user_id, w_name, now, now))

        # 2. Simpan Kategori yang Disetujui Pengguna
        if selected_categories:
            for cat in selected_categories:
                name = cat.get("name")
                if not name:
                    continue
                c_type = cat.get("type", "expense")
                icon = cat.get("icon", "🏷️")
                color = cat.get("color", "#FF6B00")
                monthly_budget = float(cat.get("monthly_budget", 0.0))
                
                cursor.execute("SELECT id FROM categories WHERE user_id = ? AND name = ?", (user_id, name))
                c_row = cursor.fetchone()
                if not c_row:
                    cursor.execute("""
                    INSERT INTO categories (id, user_id, name, type, icon, color, monthly_budget, is_system, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """, (str(uuid.uuid4()), user_id, name, c_type, icon, color, monthly_budget, now))
                else:
                    cursor.execute("""
                    UPDATE categories SET monthly_budget = ? WHERE id = ?
                    """, (monthly_budget, c_row["id"]))

        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ?", (user_id,))
        total_cats = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM wallets WHERE user_id = ?", (user_id,))
        total_wallets = cursor.fetchone()[0]
        conn.close()

        return {
            "success": True,
            "message": "Onboarding berhasil diselesaikan!",
            "categories_count": total_cats,
            "wallets_count": total_wallets,
            "redirect_url": "/dashboard"
        }

    @staticmethod
    def login_user(identifier: str, password: str) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        id_clean = identifier.strip().lower()
        
        # Check by email or cleaned phone (08xx or 628xx)
        clean_phone = re.sub(r'[^0-9]', '', identifier)
        if clean_phone.startswith('62'):
            clean_phone = '0' + clean_phone[2:]

        cursor.execute("""
        SELECT id, email, password_hash, full_name, phone_number, phone_verified, plan, role, avatar_url, default_currency
        FROM profiles
        WHERE email = ? OR phone_number = ? OR phone_number = ?
        """, (id_clean, identifier.strip(), clean_phone))
        user = cursor.fetchone()
        conn.close()

        if not user or not verify_password(password, user["password_hash"]):
            raise ValueError("Email / Nomor HP atau password salah.")

        token = create_access_token({
            "sub": user["id"],
            "email": user["email"],
            "role": user["role"],
            "plan": user["plan"]
        })

        return {
            "token": token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "phone_number": user["phone_number"],
                "phone_verified": bool(user["phone_verified"]),
                "plan": user["plan"],
                "role": user["role"],
                "avatar_url": user["avatar_url"],
                "default_currency": user["default_currency"]
            }
        }
