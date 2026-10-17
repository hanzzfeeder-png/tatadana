#!/usr/bin/env python3
"""
=============================================================================
TataDana Production Webhook Helper
=============================================================================
Script ini digunakan untuk mendaftarkan URL webhook produksi aplikasi TataDana
ke Telegram Bot API.

Penggunaan:
    python scripts/set_production_webhook.py           # Registrasi webhook
    python scripts/set_production_webhook.py --info    # Cek status webhook saat ini
    python scripts/set_production_webhook.py --delete  # Hapus webhook aktif
=============================================================================
"""

import os
import sys
import argparse
import httpx
from dotenv import load_dotenv

# Load .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

def mask_token(token: str) -> str:
    """Menyamarkan token bot untuk keamanan log."""
    if not token or len(token) < 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"

def get_webhook_info():
    """Mengambil status webhook saat ini dari Telegram API."""
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN belum disetel di .env atau environment variable.")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
    print(f"\n[INFO] Memeriksa status webhook Telegram (Token: {mask_token(TELEGRAM_BOT_TOKEN)})...")
    
    try:
        resp = httpx.get(url, timeout=15.0)
        data = resp.json()
        if data.get("ok"):
            res = data.get("result", {})
            print("=======================================================")
            print("STATUS WEBHOOK TELEGRAM SAAT INI:")
            print("=======================================================")
            print(f"URL Webhook       : {res.get('url') or '(Belum dipasang)'}")
            print(f"Custom Cert       : {res.get('has_custom_certificate')}")
            print(f"Pending Updates   : {res.get('pending_update_count', 0)}")
            print(f"Max Connections   : {res.get('max_connections', 40)}")
            print(f"IP Address        : {res.get('ip_address', '-')}")
            if res.get("last_error_date"):
                print(f"Last Error Date   : {res.get('last_error_date')}")
                print(f"Last Error Message: {res.get('last_error_message')}")
            print("=======================================================\n")
        else:
            print(f"[GAGAL] Telegram API mengembalikan error: {data.get('description')}")
    except Exception as e:
        print(f"[ERROR] Gagal menghubungi Telegram API: {str(e)}")

def delete_webhook():
    """Menghapus webhook aktif dari Telegram API."""
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN belum disetel di .env atau environment variable.")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
    print(f"\n[INFO] Menghapus webhook Telegram...")
    try:
        resp = httpx.post(url, json={"drop_pending_updates": True}, timeout=15.0)
        data = resp.json()
        if data.get("ok"):
            print("[SUKSES] Webhook berhasil dihapus dari Telegram. Bot sekarang dalam mode polling.")
        else:
            print(f"[GAGAL] Gagal menghapus webhook: {data.get('description')}")
    except Exception as e:
        print(f"[ERROR] Gagal menghubungi Telegram API: {str(e)}")

def set_production_webhook():
    """Mendaftarkan URL webhook produksi ke Telegram API."""
    print("=======================================================")
    print("TATADANA - REGISTRASI WEBHOOK PRODUKSI")
    print("=======================================================")

    # Validasi Token
    if not TELEGRAM_BOT_TOKEN:
        print("\n[ERROR] TELEGRAM_BOT_TOKEN kosong!")
        print("Pastikan Anda sudah mengisi TELEGRAM_BOT_TOKEN di environment variables atau file .env.")
        sys.exit(1)

    # Validasi URL
    if not WEBHOOK_BASE_URL:
        print("\n[ERROR] WEBHOOK_BASE_URL kosong!")
        print("Pastikan Anda sudah mengisi WEBHOOK_BASE_URL (contoh: https://tatadana-production.up.railway.app).")
        sys.exit(1)

    clean_base_url = WEBHOOK_BASE_URL.rstrip("/")
    if not clean_base_url.startswith("https://"):
        print(f"\n[PERINGATAN] Telegram API mewajibkan protokol HTTPS publik!")
        print(f"URL Anda saat ini: {clean_base_url}")
        if clean_base_url.startswith("http://localhost"):
            print("[INFO] 'http://localhost' tidak dapat diakses langsung oleh server Telegram.")
            print("Gunakan Ngrok / Cloudflare Tunnel jika ingin menguji webhook nyata di lokal,")
            print("atau pasang URL domain production dari Railway/Render.")
            confirm = input("\nLanjutkan registrasi tetap? (y/N): ").strip().lower()
            if confirm != "y":
                print("Dibatalkan.")
                sys.exit(0)

    target_webhook_url = f"{clean_base_url}/api/telegram/webhook"
    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"

    payload = {
        "url": target_webhook_url,
        "allowed_updates": ["message", "edited_message"]
    }

    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET
        print(f"[INFO] Header keamanan X-Telegram-Bot-Api-Secret-Token diaktifkan.")

    print(f"\n[1/2] Menghubungi Telegram API...")
    print(f"• Target Webhook URL: {target_webhook_url}")
    print(f"• Bot Token         : {mask_token(TELEGRAM_BOT_TOKEN)}")

    try:
        resp = httpx.post(telegram_api_url, json=payload, timeout=20.0)
        data = resp.json()

        print(f"\n[2/2] Respons Telegram:")
        if data.get("ok"):
            print("-------------------------------------------------------")
            print("🎉 [SUKSES] Webhook Telegram Berhasil Dipasang!")
            print(f"Pesan: {data.get('description', 'Webhook was set')}")
            print(f"URL  : {target_webhook_url}")
            print("-------------------------------------------------------")
            print("Semua pesan chat ke Bot sekarang otomatis diteruskan ke server TataDana.\n")
        else:
            print("-------------------------------------------------------")
            print(f"❌ [GAGAL] Registrasi Webhook Ditolak Telegram:")
            print(f"Kode Error : {data.get('error_code')}")
            print(f"Keterangan : {data.get('description')}")
            print("-------------------------------------------------------\n")
    except Exception as e:
        print(f"\n[ERROR] Terjadi kesalahan jaringan saat request: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="TataDana Telegram Webhook Manager")
    parser.add_argument("--info", action="store_true", help="Cek status webhook saat ini")
    parser.add_argument("--delete", action="store_true", help="Hapus konfigurasi webhook aktif")
    args = parser.parse_args()

    if args.info:
        get_webhook_info()
    elif args.delete:
        delete_webhook()
    else:
        set_production_webhook()

if __name__ == "__main__":
    main()
