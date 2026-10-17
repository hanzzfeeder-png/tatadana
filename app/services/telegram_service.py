import os
import re
import json
import uuid
import hashlib
import secrets
import sqlite3
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import httpx
from app.database import get_db
from app.config import settings, get_wib_now, get_wib_str, format_wib_display
from app.services.ai_service import AIService
from app.services.wallet_service import WalletService
from app.services.transaction_service import TransactionService
from app.services.budget_service import BudgetService

class TelegramService:
    _pairing_lock = threading.Lock()
    @staticmethod
    async def test_and_set_bot_token(token: str, webhook_base_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Step 3-4 from Part 5:
        1. Calls GET https://api.telegram.org/bot<TOKEN>/getMe
        2. If valid, calls POST https://api.telegram.org/bot<TOKEN>/setWebhook
        3. Saves encrypted token to bot_settings
        """
        clean_token = token.strip()
        if not clean_token:
            return {"ok": False, "message": "Token Telegram Bot tidak boleh kosong."}

        base_url = webhook_base_url or settings.WEBHOOK_BASE_URL
        webhook_endpoint = f"{base_url.rstrip('/')}/api/telegram/webhook"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Test getMe
            try:
                me_res = await client.get(f"https://api.telegram.org/bot{clean_token}/getMe")
                me_data = me_res.json()
            except Exception as e:
                return {"ok": False, "message": f"Koneksi ke server Telegram gagal: {str(e)}"}

            if not me_data.get("ok"):
                error_desc = me_data.get("description", "Token tidak valid.")
                return {"ok": False, "message": f"Error Telegram: {error_desc}"}

            bot_info = me_data.get("result", {})
            bot_username = bot_info.get("username", "")

            # 2. Set Webhook
            try:
                hook_res = await client.post(
                    f"https://api.telegram.org/bot{clean_token}/setWebhook",
                    json={"url": webhook_endpoint, "drop_pending_updates": True}
                )
                hook_data = hook_res.json()
            except Exception as e:
                hook_data = {"ok": False, "description": str(e)}

        # 3. Save to database
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()
        enc_token = settings.encrypt(clean_token)

        cursor.execute("SELECT id FROM bot_settings LIMIT 1")
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
            UPDATE bot_settings
            SET bot_token_encrypted = ?, webhook_url = ?, is_connected = 1,
                bot_username = ?, last_tested_at = ?, updated_at = ?
            WHERE id = ?
            """, (enc_token, webhook_endpoint, bot_username, now, now, existing["id"]))
        else:
            import uuid
            cursor.execute("""
            INSERT INTO bot_settings (id, bot_token_encrypted, webhook_url, is_connected, bot_username, last_tested_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """, (str(uuid.uuid4()), enc_token, webhook_endpoint, bot_username, now, now))

        conn.commit()
        conn.close()

        return {
            "ok": True,
            "bot_username": bot_username,
            "webhook_url": webhook_endpoint,
            "webhook_status": hook_data.get("ok", False),
            "webhook_description": hook_data.get("description", "Berhasil didaftarkan.")
        }

    @staticmethod
    def get_bot_status() -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bot_settings LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {"is_connected": False, "bot_username": None, "last_tested_at": None}
        return {
            "is_connected": bool(row["is_connected"]),
            "bot_username": row["bot_username"],
            "webhook_url": row["webhook_url"],
            "last_tested_at": row["last_tested_at"]
        }

    @staticmethod
    def get_current_bot_token() -> Optional[str]:
        # 1. Prioritas Utama: Environment variable langsung (selalu segar & tidak bergantung database)
        env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if env_token:
            return env_token
        if getattr(settings, "TELEGRAM_BOT_TOKEN", None) and settings.TELEGRAM_BOT_TOKEN.strip():
            return settings.TELEGRAM_BOT_TOKEN.strip()

        # 2. Fallback: Cek tabel bot_settings di database
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT bot_token_encrypted FROM bot_settings WHERE is_connected = 1 LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row and row["bot_token_encrypted"]:
                decrypted = settings.decrypt(row["bot_token_encrypted"])
                if decrypted and ":" in decrypted:
                    return decrypted
        except Exception as e:
            print(f"[WARN] Gagal membaca bot_token dari database: {e}")

        return None

    @staticmethod
    async def send_telegram_message(chat_id: int, text: str, parse_mode: Optional[str] = "Markdown") -> bool:
        token = TelegramService.get_current_bot_token()
        if not token:
            print(f"[TELEGRAM ERROR] Gagal mengirim pesan: TELEGRAM_BOT_TOKEN kosong atau belum disetel di Railway environment variables!")
            return False

        masked = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "***"
        print(f"[TELEGRAM SEND] Mengirim pesan ke chat_id={chat_id} (Bot: {masked}, parse_mode={parse_mode})...")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                body = {"chat_id": chat_id, "text": text}
                if parse_mode:
                    body["parse_mode"] = parse_mode

                res = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=body
                )

                if res.status_code == 200:
                    print(f"[TELEGRAM SUCCESS] Pesan berhasil terkirim ke chat_id={chat_id}")
                    return True

                print(f"[TELEGRAM WARN] SendMessage Telegram API merespon HTTP {res.status_code}: {res.text}")

                # Auto-Retry: Jika Telegram menolak karena formatting/parsing entity markdown, kirim ulang sebagai plain text
                if parse_mode:
                    print(f"[TELEGRAM RETRY] Mengirim ulang tanpa parse_mode (plain text) ke chat_id={chat_id}...")
                    retry_res = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": text}
                    )
                    if retry_res.status_code == 200:
                        print(f"[TELEGRAM SUCCESS] Fallback plain text berhasil terkirim ke chat_id={chat_id}")
                        return True
                    else:
                        print(f"[TELEGRAM ERROR] Retry plain text juga gagal HTTP {retry_res.status_code}: {retry_res.text}")
                        return False

                return False
        except Exception as e:
            print(f"[TELEGRAM EXCEPTION] Terjadi error saat menghubungi Telegram API: {e}")
            return False

    @staticmethod
    def is_update_processed(update_id: int) -> bool:
        """
        Pencegahan Race Condition Idempotency:
        Memanfaatkan Primary Key update_id pada database. Jika 2 request identik
        masuk bersamaan, hanya 1 yang berhasil insert (return False = proses baru).
        Request kedua akan gagal constraint dan di-rollback (return True = skip).
        """
        conn = get_db()
        cursor = conn.cursor()
        try:
            now_str = get_wib_str()
            cursor.execute("INSERT INTO telegram_updates (update_id, processed_at) VALUES (?, ?)", (update_id, now_str))
            conn.commit()
            return False
        except Exception:
            conn.rollback()
            return True
        finally:
            conn.close()

    @staticmethod
    def find_user_by_telegram(tg_user_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT p.*, tl.telegram_chat_id
        FROM profiles p
        JOIN telegram_links tl ON tl.user_id = p.id
        WHERE tl.telegram_user_id = ? AND tl.is_active = 1
        """, (tg_user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def generate_pairing_token(user_id: str) -> Dict[str, Any]:
        """
        Membuat token penautan akun sekali pakai (One-Time Pairing Token).
        - Acak secara kriptografis (secrets)
        - Kedaluwarsa dalam 10 menit
        - Disimpan dalam bentuk hash SHA-256
        - Maksimal 5x percobaan salah
        """
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_now()
        expires_at = now + timedelta(minutes=10)
        now_str = get_wib_str(now)
        expires_str = get_wib_str(expires_at)

        # Hapus token lama yang belum digunakan milik user ini
        cursor.execute("DELETE FROM telegram_pair_tokens WHERE user_id = ?", (user_id,))

        # Format token: TD-XXXXXX (mudah diketik atau di-klik via deep link)
        raw_code = f"TD-{secrets.token_hex(3).upper()}"
        token_hash = hashlib.sha256(raw_code.encode()).hexdigest()
        token_preview = f"{raw_code[:5]}***"
        token_id = str(uuid.uuid4())

        cursor.execute("""
        INSERT INTO telegram_pair_tokens (id, user_id, token_hash, token_preview, attempts, max_attempts, expires_at, created_at)
        VALUES (?, ?, ?, ?, 0, 5, ?, ?)
        """, (token_id, user_id, token_hash, token_preview, expires_str, now_str))

        conn.commit()
        conn.close()

        return {
            "token": raw_code,
            "expires_at": expires_str,
            "expires_in_seconds": 600
        }

    @staticmethod
    def consume_pairing_token(raw_token: str, tg_user_id: int, tg_chat_id: int, username: Optional[str] = None) -> Dict[str, Any]:
        """
        Memvalidasi dan mengonsumsi token penautan akun secara atomik.
        Jika token valid, akun langsung dikaitkan dan token dimusnahkan (single-use).
        Diproteksi dengan thread-safe lock dan atomic database delete.
        """
        clean_token = raw_token.strip().upper()
        token_hash = hashlib.sha256(clean_token.encode()).hexdigest()

        with TelegramService._pairing_lock:
            conn = get_db()
            cursor = conn.cursor()
            now_str = get_wib_str()

            try:
                cursor.execute("SELECT * FROM telegram_pair_tokens WHERE token_hash = ?", (token_hash,))
                row = cursor.fetchone()
                if not row:
                    return {
                        "success": False,
                        "message": "Kode penautan tidak valid atau sudah digunakan. Silakan buat kode baru di Dashboard Web TataDana."
                    }

                token_id = row["id"]
                user_id = row["user_id"]
                attempts = int(row["attempts"])
                max_attempts = int(row["max_attempts"])
                expires_at = row["expires_at"]

                # 1. Cek batas percobaan salah
                if attempts >= max_attempts:
                    cursor.execute("DELETE FROM telegram_pair_tokens WHERE id = ?", (token_id,))
                    conn.commit()
                    return {
                        "success": False,
                        "message": "Kode penautan telah hangus karena melebihi batas percobaan. Silakan buat kode baru di Dashboard Web."
                    }

                # Increment jumlah percobaan
                cursor.execute("UPDATE telegram_pair_tokens SET attempts = attempts + 1 WHERE id = ?", (token_id,))

                # 2. Cek masa berlaku (10 menit)
                if expires_at < now_str:
                    cursor.execute("DELETE FROM telegram_pair_tokens WHERE id = ?", (token_id,))
                    conn.commit()
                    return {
                        "success": False,
                        "message": "Kode penautan telah kedaluwarsa (hanya berlaku 10 menit). Silakan buat kode baru di Dashboard Web."
                    }

                # 3. Token valid! Tautkan identitas Telegram ke akun TataDana
                cursor.execute("SELECT full_name, phone_number FROM profiles WHERE id = ?", (user_id,))
                profile = cursor.fetchone()
                full_name = profile["full_name"] if profile else "Pengguna TataDana"
                phone = profile["phone_number"] if profile else None

                cursor.execute("""
                INSERT INTO telegram_links (id, user_id, telegram_user_id, telegram_chat_id, telegram_username, phone_number, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE
                SET user_id = EXCLUDED.user_id, telegram_chat_id = EXCLUDED.telegram_chat_id, telegram_username = EXCLUDED.telegram_username, updated_at = EXCLUDED.updated_at
                """, (str(uuid.uuid4()), user_id, tg_user_id, tg_chat_id, username, phone, now_str, now_str))

                # 4. Musnahkan token agar tidak bisa digunakan kembali (single-use)
                cursor.execute("DELETE FROM telegram_pair_tokens WHERE id = ?", (token_id,))
                if cursor.rowcount == 0:
                    conn.rollback()
                    return {
                        "success": False,
                        "message": "Kode penautan sudah digunakan oleh permintaan lain."
                    }

                conn.commit()

                return {
                    "success": True,
                    "user_id": user_id,
                    "full_name": full_name
                }
            except Exception as e:
                conn.rollback()
                return {"success": False, "message": f"Terjadi kesalahan saat memproses penautan: {str(e)}"}
            finally:
                conn.close()

    @staticmethod
    def link_telegram_account_direct(user_id: str, tg_user_id: int, tg_chat_id: int, username: Optional[str] = None) -> bool:
        """Metode penautan langsung yang digunakan hanya oleh sesi web terautentikasi (simulasi)"""
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()
        cursor.execute("SELECT phone_number FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        phone = p["phone_number"] if p else None

        cursor.execute("""
        INSERT INTO telegram_links (id, user_id, telegram_user_id, telegram_chat_id, telegram_username, phone_number, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE
        SET user_id = EXCLUDED.user_id, telegram_chat_id = EXCLUDED.telegram_chat_id, updated_at = EXCLUDED.updated_at
        """, (str(uuid.uuid4()), user_id, tg_user_id, tg_chat_id, username, phone, now, now))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    async def process_telegram_webhook(update_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main Webhook Dispatcher:
        1. Memeriksa Idempotency via update_id secara atomik (Anti-Race Condition)
        2. Memvalidasi penautan akun melalui One-Time Pairing Token
        3. Memproses transaksi dan command menggunakan user_id yang sah
        """
        update_id = update_payload.get("update_id")
        if not update_id:
            return {"status": "ignored", "reason": "no_update_id"}

        # Idempotency check atomik: mencegah pemrosesan ganda saat Telegram melakukan retry
        if TelegramService.is_update_processed(update_id):
            return {"status": "skipped", "reason": "already_processed"}

        msg = update_payload.get("message") or update_payload.get("edited_message")
        if not msg:
            return {"status": "ignored", "reason": "no_message"}

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        from_user = msg.get("from", {})
        tg_user_id = from_user.get("id")
        username = from_user.get("username")
        text = (msg.get("text") or "").strip()

        # 1. Cek apakah identitas Telegram ini sudah tertaut dengan akun TataDana
        user = TelegramService.find_user_by_telegram(tg_user_id)

        # 2. Cek apakah pesan berisi kode penautan (/start TD-XXXXXX atau TD-XXXXXX)
        pairing_code_candidate = None
        if text.startswith("/start "):
            pairing_code_candidate = text[7:].strip()
        elif text.upper().startswith("TD-") and len(text.strip()) in (9, 10, 11):
            pairing_code_candidate = text.strip()

        if pairing_code_candidate:
            consume_res = TelegramService.consume_pairing_token(pairing_code_candidate, tg_user_id, chat_id, username)
            if consume_res["success"]:
                await TelegramService.send_telegram_message(
                    chat_id,
                    f"🎉 *Akun Berhasil Terhubung!*\n\n"
                    f"Selamat datang, *{consume_res['full_name']}*!\n"
                    "Akun TataDana kamu sekarang sudah aktif di bot ini.\n\n"
                    "Mulai catat transaksi semudah kirim chat, contoh:\n"
                    "• `Beli nasi padang 25rb`\n"
                    "• `Bensin motor 30k`\n"
                    "• `Gajian 6jt`\n\n"
                    "Ketik /bantuan untuk melihat menu lainnya."
                )
                return {"status": "success", "action": "account_paired", "user_id": consume_res["user_id"]}
            else:
                await TelegramService.send_telegram_message(
                    chat_id,
                    f"❌ *Penautan Gagal*\n\n{consume_res['message']}"
                )
                return {"status": "error", "reason": "invalid_pairing_token"}

        # 3. Jika akun belum tertaut dan bukan perintah penautan valid
        if not user:
            print(f"[WEBHOOK] Pengguna Telegram {tg_user_id} (chat_id={chat_id}) belum tertaut. Mengirim panduan selamat datang...")
            welcome_text = (
                "👋 *Halo! Selamat datang di TataDana Bot*\n\n"
                "Akun Telegram kamu belum terhubung dengan akun TataDana.\n\n"
                "*Cara Menghubungkan Akun Secara Aman:*\n"
                "1. Buka dan masuk ke *Dashboard Web TataDana*\n"
                "2. Masuk ke menu *Pengaturan* → tab *Integrasi Telegram*\n"
                "3. Klik tombol *Hubungkan Telegram* untuk mendapatkan kode penautan (10 menit)\n"
                "4. Kirim kode tersebut ke sini (contoh: `/start TD-XXXXXX`)."
            )
            delivered = await TelegramService.send_telegram_message(chat_id, welcome_text)
            print(f"[WEBHOOK] Status pengiriman pesan selamat datang: {delivered}")
            return {"status": "waiting_link", "message_delivered": delivered}

        # 4. IDENTITAS TERVERIFIKASI: user_id HANYA diambil dari relasi telegram_links
        user_id = user["id"]
        user_name = user["full_name"]
        plan = user["plan"]

        # 5. Handle Bot Commands

        if text.startswith("/"):
            return await TelegramService.handle_bot_commands(user_id, user_name, chat_id, text)

        # 3. Handle Voice Note (Audio) Input
        voice = msg.get("voice") or msg.get("audio")
        if voice:
            duration = voice.get("duration", 0)
            if duration > 60:
                await TelegramService.send_telegram_message(
                    chat_id,
                    "⏱️ *Durasi Voice Note Terlalu Panjang*\n\n"
                    "Maksimal durasi voice note adalah 60 detik demi efisiensi. "
                    "Silakan kirim rekaman yang lebih singkat ya."
                )
                return {"status": "error", "reason": "vn_duration_exceeded"}

            try:
                transcript, parsed = await AIService.transcribe_voice_note(duration, user_id=user_id)
                if parsed.get("error"):
                    await TelegramService.send_telegram_message(
                        chat_id,
                        "⚠️ *TataDana belum memahami rekaman suara kamu.*\n\n"
                        f"🎙️ Transkrip: \"_{transcript}_\"\n\n"
                        "Pastikan menyebutkan nominal dan keperluannya dengan jelas, atau ketik langsung via teks.\n"
                        "Contoh: `Makan siang 25rb`"
                    )
                    return {"status": "error", "reason": "unclear_vn"}

                return await TelegramService.record_parsed_transaction(
                    user_id, chat_id, parsed, source="telegram_voice", transcript_note=transcript
                )
            except Exception as e:
                await TelegramService.send_telegram_message(chat_id, f"❌ Terjadi kesalahan saat memproses voice note: {str(e)}")
                return {"status": "error", "error": str(e)}

        # 4. Handle Photo Receipt Input (Pro Feature)
        photo = msg.get("photo")
        if photo:
            if plan != "pro":
                await TelegramService.send_telegram_message(
                    chat_id,
                    "🔒 *Fitur Khusus TataDana Pro*\n\n"
                    "Input transaksi via foto struk belanja dengan AI Vision hanya tersedia untuk pengguna *TataDana Pro*.\n\n"
                    "🚀 Upgrade sekarang ke Pro (hanya Rp99.000 sekali bayar) untuk menikmati:\n"
                    "• Scan struk belanja otomatis tanpa batas\n"
                    "• AI Financial Advisor\n"
                    "• Laporan & Export Excel/PDF lengkap\n\n"
                    "Kunjungi menu Settings di dashboard web untuk upgrade!"
                )
                return {"status": "blocked", "reason": "starter_plan_restriction"}

            # Process Receipt
            parsed_receipt = await AIService.parse_receipt_photo(b"", user_id=user_id)
            return await TelegramService.record_receipt_transaction(user_id, chat_id, parsed_receipt)

        # 5. Handle Text Input
        if text:
            parsed = await AIService.parse_natural_text_transaction(text, user_id=user_id)
            if parsed.get("error"):
                await TelegramService.send_telegram_message(
                    chat_id,
                    "⚠️ *Maaf, TataDana belum memahami pesan transaksimu.*\n\n"
                    "Pastikan menyertakan nominal dan keperluannya ya.\n\n"
                    "💡 *Contoh format yang benar:*\n"
                    "• `Beli bakso 15rb`\n"
                    "• `Bensin motor 25ribu`\n"
                    "• `Kopi susu 18k`\n"
                    "• `Gajian 5jt`"
                )
                return {"status": "error", "reason": "unclear_text"}

            return await TelegramService.record_parsed_transaction(user_id, chat_id, parsed, source="telegram_text")

        return {"status": "unhandled"}

    @staticmethod
    async def record_parsed_transaction(
        user_id: str,
        chat_id: int,
        parsed: Dict[str, Any],
        source: str = "telegram_text",
        transcript_note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Saves transaction and generates the exact formatted reply from Part 4.4 / 4.5.
        """
        default_wallet = WalletService.get_default_wallet(user_id)
        if not default_wallet:
            await TelegramService.send_telegram_message(chat_id, "❌ Kamu belum memiliki dompet aktif. Silakan buat dompet di dashboard web.")
            return {"status": "error", "reason": "no_wallet"}

        tx_type = parsed.get("jenis", "expense")
        nominal = float(parsed.get("nominal", 0))
        cat_name = parsed.get("kategori", "Makanan & Minuman")
        note = parsed.get("catatan", "")

        # Find or match category
        categories = BudgetService.get_categories(user_id)
        matched_cat = next((c for c in categories if c["name"].lower() == cat_name.lower()), None)
        if not matched_cat and categories:
            matched_cat = categories[0]

        category_id = matched_cat["id"] if matched_cat else None
        cat_icon = matched_cat["icon"] if matched_cat else "🏷️"
        cat_display_name = matched_cat["name"] if matched_cat else cat_name

        try:
            tx = TransactionService.create_transaction(
                user_id=user_id,
                wallet_id=default_wallet["id"],
                tx_type=tx_type,
                amount=nominal,
                category_id=category_id,
                note=note,
                source=source
            )
        except ValueError as e:
            # Limit reached or validation error
            await TelegramService.send_telegram_message(chat_id, f"⚠️ *Perhatian:* {str(e)}")
            return {"status": "limit_reached", "message": str(e)}

        # Fetch updated wallet balance
        updated_wallet = WalletService.get_wallet_by_id(default_wallet["id"], user_id)
        new_balance = updated_wallet["balance"] if updated_wallet else 0.0

        wib_time = format_wib_display()

        # Build Format Reply
        if tx_type == "expense":
            # Budget Status
            b_status = BudgetService.get_single_category_budget_status(user_id, category_id) if category_id else None
            budget_section = ""
            if b_status and b_status["monthly_budget"] > 0:
                budget_section = (
                    f"\n\n📊 *Budget {cat_display_name} bulan ini:*\n"
                    f"{b_status['progress_bar']} {b_status['percent']}% — sisa Rp{b_status['remaining']:,.0f}"
                )
                if b_status["is_exceeded"]:
                    budget_section += "\n⚠️ _Budget kategori ini sudah terlampaui! Kurangi pengeluaran ya._"
                elif b_status["is_over_80"]:
                    budget_section += "\n⚡ _Peringatan: Budget sudah terpakai lebih dari 80%!_"

            vn_line = f"🎙️ Transkrip: \"_{transcript_note}_\"\n" if transcript_note else ""

            reply = (
                f"📅 {wib_time}\n"
                f"{vn_line}"
                f"💸 *Pengeluaran tercatat!*\n"
                f"├ Nominal : Rp{nominal:,.0f}\n"
                f"├ Kategori : {cat_icon} {cat_display_name}\n"
                f"├ Dompet : 👛 {default_wallet['name']}\n"
                f"├ Catatan : {note}\n"
                f"└ Saldo : Rp{new_balance:,.0f}"
                f"{budget_section}"
            )
        else: # income
            vn_line = f"🎙️ Transkrip: \"_{transcript_note}_\"\n" if transcript_note else ""
            reply = (
                f"📅 {wib_time}\n"
                f"{vn_line}"
                f"💰 *Pemasukan tercatat!*\n"
                f"├ Nominal : Rp{nominal:,.0f}\n"
                f"├ Kategori : 💼 Pemasukan\n"
                f"├ Dompet : 👛 {default_wallet['name']}\n"
                f"└ Saldo baru : Rp{new_balance:,.0f}\n\n"
                f"💪 _Semangat terus! Jangan lupa sisihkan untuk tabungan ya._"
            )

        # Check AI Financial Advisor (Pro)
        advisor = AIService.check_financial_advisor(user_id, tx)
        if advisor and advisor.get("message"):
            reply += f"\n\n{advisor['message']}"

        await TelegramService.send_telegram_message(chat_id, reply)
        return {"status": "success", "transaction_id": tx["id"]}

    @staticmethod
    async def record_receipt_transaction(user_id: str, chat_id: int, parsed_receipt: Dict[str, Any]) -> Dict[str, Any]:
        """
        Saves OCR photo receipt transaction with multi-item breakdown.
        """
        default_wallet = WalletService.get_default_wallet(user_id)
        total_amount = parsed_receipt["total_amount"]
        merchant = parsed_receipt["merchant"]
        items = parsed_receipt["items"]

        categories = BudgetService.get_categories(user_id)
        matched_cat = next((c for c in categories if "belanja" in c["name"].lower()), categories[0] if categories else None)
        category_id = matched_cat["id"] if matched_cat else None

        tx = TransactionService.create_transaction(
            user_id=user_id,
            wallet_id=default_wallet["id"],
            tx_type="expense",
            amount=total_amount,
            category_id=category_id,
            note=f"Belanja {merchant} ({len(items)} item)",
            source="telegram_photo",
            receipt_items=items
        )

        updated_wallet = WalletService.get_wallet_by_id(default_wallet["id"], user_id)
        new_balance = updated_wallet["balance"] if updated_wallet else 0.0

        item_preview = "\n".join([f"• {it['name']} : Rp{it['price']:,}" for it in items[:4]])
        reply = (
            f"📅 {format_wib_display()}\n"
            f"🧾 *Struk Belanja Tercatat! (AI OCR)*\n"
            f"├ Merchant : 🏪 {merchant}\n"
            f"├ Total : Rp{total_amount:,.0f}\n"
            f"├ Dompet : 👛 {default_wallet['name']}\n"
            f"├ Item Terdeteksi ({len(items)}):\n{item_preview}\n"
            f"└ Saldo Baru : Rp{new_balance:,.0f}\n\n"
            f"✨ _Rincian item lengkap tersimpan rapi dan dapat di-expand di tabel Laporan web TataDana._"
        )

        await TelegramService.send_telegram_message(chat_id, reply)
        return {"status": "success", "transaction_id": tx["id"]}

    @staticmethod
    async def handle_bot_commands(user_id: str, user_name: str, chat_id: int, text: str) -> Dict[str, Any]:
        cmd = text.split()[0].lower()

        if cmd in ["/start", "/mulai"]:
            reply = (
                f"👋 Halo *{user_name}*!\n\n"
                "TataDana siap membantu mencatat keuanganmu dengan super cepat.\n\n"
                "📌 *Command yang tersedia:*\n"
                "• /saldo — Cek saldo semua dompet\n"
                "• /hari\\_ini — Rekap transaksi hari ini\n"
                "• /minggu\\_ini — Rekap transaksi 7 hari terakhir\n"
                "• /bulan\\_ini — Rekap bulan berjalan & kategori\n"
                "• /budget — Status budget semua kategori\n"
                "• /sheet — Link ke dashboard web pribadi kamu\n"
                "• /bantuan — Panduan lengkap fitur bot"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd == "/saldo":
            wallets = WalletService.get_wallets(user_id)
            total_balance = sum(w["balance"] for w in wallets)
            lines = [f"{w.get('icon', '👛')} *{w['name']}*: Rp{w['balance']:,.0f}" for w in wallets]
            reply = (
                f"👛 *Saldo Dompet Kamu*\n\n"
                + "\n".join(lines) +
                f"\n\n━━━━━━━━━━━━━━━\n"
                f"💰 *Total Saldo:* Rp{total_balance:,.0f}"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd in ["/hari_ini", "/hariini", "/hari"]:
            now_str = get_wib_now().strftime("%Y-%m-%d")
            from app.services.report_service import ReportService
            summary = ReportService.get_report_summary(user_id, start_date=now_str, end_date=now_str)
            reply = (
                f"📅 *Rekap Transaksi Hari Ini*\n"
                f"Tanggal: {now_str}\n\n"
                f"🟢 Pemasukan: Rp{summary['total_income']:,.0f}\n"
                f"🔴 Pengeluaran: Rp{summary['total_expense']:,.0f}\n"
                f"⚖️ Selisih (Cashflow): Rp{summary['net_cashflow']:,.0f}"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd in ["/minggu_ini", "/mingguini", "/minggu"]:
            start_str = (get_wib_now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end_str = get_wib_now().strftime("%Y-%m-%d")
            from app.services.report_service import ReportService
            summary = ReportService.get_report_summary(user_id, start_date=start_str, end_date=end_str)
            reply = (
                f"📊 *Rekap 7 Hari Terakhir*\n"
                f"Periode: {start_str} s/d {end_str}\n\n"
                f"🟢 Total Masuk: Rp{summary['total_income']:,.0f}\n"
                f"🔴 Total Keluar: Rp{summary['total_expense']:,.0f}\n"
                f"⚖️ Net Cashflow: Rp{summary['net_cashflow']:,.0f}"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd in ["/bulan_ini", "/bulanini", "/bulan"]:
            now = get_wib_now()
            start_str = now.strftime("%Y-%m-01")
            from app.services.report_service import ReportService
            summary = ReportService.get_report_summary(user_id, start_date=start_str)
            
            top_lines = [f"• {c.get('icon', '🏷️')} {c['name']}: Rp{c['total_spent']:,.0f}" for c in summary["top_categories"]]
            top_section = "\n".join(top_lines) if top_lines else "_Belum ada pengeluaran bulan ini._"

            reply = (
                f"🗓️ *Rekap Keuangan Bulan {now.strftime('%B %Y')}*\n\n"
                f"🟢 Pemasukan : Rp{summary['total_income']:,.0f}\n"
                f"🔴 Pengeluaran : Rp{summary['total_expense']:,.0f}\n"
                f"⚖️ Cashflow : Rp{summary['net_cashflow']:,.0f}\n\n"
                f"🏆 *Top Kategori Pengeluaran:*\n"
                f"{top_section}"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd == "/budget":
            b_list = BudgetService.get_budget_statuses(user_id)
            if not b_list:
                reply = "🎯 *Belum ada budget yang diatur.* Atur budget kategori kamu di dashboard web TataDana."
            else:
                lines = []
                for b in b_list:
                    if b["monthly_budget"] > 0:
                        lines.append(f"{b['icon']} *{b['name']}*\n{b['progress_bar']} {b['percent']}% (Sisa: Rp{b['remaining']:,.0f})")
                reply = "🎯 *Status Budget Bulan Ini:*\n\n" + ("\n\n".join(lines) if lines else "Belum ada kategori dengan budget > 0.")
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd == "/sheet":
            reply = (
                f"📊 *Akses Dashboard & Laporan Lengkap*\n\n"
                f"Buka dashboard pribadimu untuk melihat grafik interaktif, filter laporan lengkap, dan download Excel/PDF:\n"
                f"👉 {settings.WEBHOOK_BASE_URL}/dashboard\n\n"
                f"_Semua transaksi otomatis tersinkronisasi real-time!_"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        if cmd in ["/bantuan", "/help"]:
            reply = (
                "ℹ️ *Panduan Penggunaan TataDana Bot*\n\n"
                "1️⃣ *Catat via Teks:*\n"
                "Ketik langsung pengeluaran/pemasukanmu:\n"
                "• `Beli nasi padang 25rb`\n"
                "• `Kopi susu 18k`\n"
                "• `Gajian bulan ini 8jt`\n\n"
                "2️⃣ *Catat via Suara (VN):*\n"
                "Kirim voice note durasi maks 60 detik. AI akan otomatis mentranskrip dan mencatat nominal serta kategorinya.\n\n"
                "3️⃣ *Catat via Foto Struk (Pro):*\n"
                "Kirim foto struk belanjaanmu. AI Vision akan mengekstrak item dan harga secara otomatis!\n\n"
                "4️⃣ *Commands Tersedia:*\n"
                "/saldo — Cek saldo semua dompet\n"
                "/hari\\_ini — Rekap transaksi hari ini\n"
                "/minggu\\_ini — Rekap 7 hari terakhir\n"
                "/bulan\\_ini — Rekap bulan berjalan\n"
                "/budget — Cek sisa budget kategori\n"
                "/sheet — Link dashboard TataDana\n"
                "/bantuan — Buka menu panduan ini"
            )
            await TelegramService.send_telegram_message(chat_id, reply)
            return {"status": "command", "cmd": cmd}

        await TelegramService.send_telegram_message(
            chat_id,
            "❓ Command tidak dikenali. Ketik /bantuan untuk melihat daftar perintah yang tersedia."
        )
        return {"status": "unknown_command"}
