import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.services.telegram_service import TelegramService
from app.security import get_current_user
from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])

class TestTokenRequest(BaseModel):
    token: str
    webhook_base_url: Optional[str] = None

class SimulateMessageRequest(BaseModel):
    message: str
    type: str = "text" # text, vn, photo
    duration: int = 5 # for VN

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Endpoint Penerima Webhook Telegram:
    1. Memvalidasi Secret Token Telegram (X-Telegram-Bot-Api-Secret-Token)
    2. Menolak akses tidak sah dengan 401 Unauthorized
    3. Tidak mencatat token rahasia ke log
    """
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    if expected_secret:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not secret_header or not secrets.compare_digest(secret_header, expected_secret):
            raise HTTPException(status_code=401, detail="Akses ditolak: Secret token webhook tidak valid.")

    try:
        payload = await request.json()
        update_id = payload.get("update_id")
        has_msg = bool(payload.get("message"))
        print(f"[WEBHOOK INCOMING] update_id={update_id}, has_message={has_msg}")
        result = await TelegramService.process_telegram_webhook(payload)
        print(f"[WEBHOOK RESULT] update_id={update_id}, result={result}")
        return result
    except Exception as e:
        print(f"[WEBHOOK ERROR] {str(e)}")
        return {"status": "error", "message": str(e)}

@router.post("/generate-pairing-code")
def generate_pairing_code(user: dict = Depends(get_current_user)):
    """
    Membuat One-Time Pairing Token (10 menit) untuk menautkan akun web ke bot Telegram.
    Hanya bisa diakses oleh pengguna yang sudah login ke akun miliknya sendiri.
    Token disimpan dalam bentuk hash SHA-256.
    """
    token_info = TelegramService.generate_pairing_token(user["id"])
    bot_status = TelegramService.get_bot_status()
    bot_username = bot_status.get("bot_username") or "TataDanaBot"
    deep_link = f"https://t.me/{bot_username}?start={token_info['token']}"
    return {
        "success": True,
        "data": {
            **token_info,
            "bot_username": bot_username,
            "deep_link": deep_link
        }
    }

@router.post("/test-connection")
async def test_bot_connection(req: TestTokenRequest, user: dict = Depends(get_current_user)):
    """
    Dipanggil saat pengguna menguji koneksi token bot di Settings -> Integrasi Telegram.
    Memanggil getMe -> setWebhook dengan secret_token -> menyimpan token terenkripsi.
    """
    res = await TelegramService.test_and_set_bot_token(req.token, req.webhook_base_url)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.get("/status")
def get_bot_status(user: dict = Depends(get_current_user)):
    bot_info = TelegramService.get_bot_status()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT telegram_user_id, telegram_username, phone_number, is_active, created_at
    FROM telegram_links
    WHERE user_id = ? AND is_active = 1
    LIMIT 1
    """, (user["id"],))
    link = cursor.fetchone()
    conn.close()

    user_link = None
    if link:
        user_link = {
            "telegram_user_id": link["telegram_user_id"],
            "telegram_username": link["telegram_username"],
            "phone_number": link["phone_number"],
            "linked_at": link["created_at"]
        }

    return {
        "success": True,
        "data": {
            **bot_info,
            "user_link": user_link,
            "is_user_linked": user_link is not None
        }
    }

@router.post("/unlink")
def unlink_telegram_account(user: dict = Depends(get_current_user)):
    """Memutuskan penautan akun Telegram pengguna saat ini"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM telegram_links WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Tautan akun Telegram Anda berhasil diputuskan."}

@router.post("/simulate-chat")
async def simulate_chat(req: SimulateMessageRequest, user: dict = Depends(get_current_user)):
    """
    Simulasi pesan chat Telegram langsung dari kotak interaktif web UI.
    Identitas user terikat ke sesi login pengguna saat ini.
    """
    user_id = user["id"]
    chat_id = 999999999 # virtual chat id

    fake_update = {
        "update_id": int(request_counter()),
        "message": {
            "message_id": 101,
            "from": {
                "id": 999999999,
                "first_name": user["full_name"],
                "username": "user_demo"
            },
            "chat": {
                "id": chat_id,
                "first_name": user["full_name"],
                "type": "private"
            },
            "date": 1760000000
        }
    }

    # Tautkan user secara sah ke chat simulasi
    TelegramService.link_telegram_account_direct(user_id, 999999999, chat_id, "user_demo")

    if req.type == "vn":
        fake_update["message"]["voice"] = {"duration": req.duration, "file_id": "mock_voice_file"}
    elif req.type == "photo":
        fake_update["message"]["photo"] = [{"file_id": "mock_photo_file"}]
    else:
        fake_update["message"]["text"] = req.message

    res = await TelegramService.process_telegram_webhook(fake_update)
    return {"success": True, "result": res}

_counter = 500000
def request_counter():
    global _counter
    _counter += 1
    return _counter
