import os
from datetime import datetime
import pytz
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

WIB = pytz.timezone('Asia/Jakarta')

def get_wib_now() -> datetime:
    return datetime.now(WIB)

def get_wib_str(dt: datetime = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt is None:
        dt = get_wib_now()
    elif dt.tzinfo is None:
        dt = pytz.utc.localize(dt).astimezone(WIB)
    else:
        dt = dt.astimezone(WIB)
    return dt.strftime(fmt)

def format_wib_display(dt: datetime = None) -> str:
    """Format: Kamis, 16 Oktober 2026 — 19:30 WIB"""
    if dt is None:
        dt = get_wib_now()
    elif dt.tzinfo is None:
        dt = pytz.utc.localize(dt).astimezone(WIB)
    else:
        dt = dt.astimezone(WIB)

    hari_map = {
        'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
        'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
    }
    bulan_map = {
        'January': 'Januari', 'February': 'Februari', 'March': 'Maret',
        'April': 'April', 'May': 'Mei', 'June': 'Juni',
        'July': 'Juli', 'August': 'Agustus', 'September': 'September',
        'October': 'Oktober', 'November': 'November', 'December': 'Desember'
    }

    hari = hari_map.get(dt.strftime('%A'), dt.strftime('%A'))
    tgl = dt.strftime('%d')
    bln = bulan_map.get(dt.strftime('%B'), dt.strftime('%B'))
    thn = dt.strftime('%Y')
    jam = dt.strftime('%H:%M')

    return f"{hari}, {tgl} {bln} {thn} — {jam} WIB"

class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "TataDana")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_TIMEZONE: str = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "tatadana-secret-key-indonesia-wib-2026")
    WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    
    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_STORAGE_BUCKET: str = os.getenv("SUPABASE_STORAGE_BUCKET", "tatadana-exports")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "TataDanaFinanceBot").strip().lstrip("@")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "tatadana-webhook-secret-token-key-2026")

    # Midtrans
    MIDTRANS_SERVER_KEY: str = os.getenv("MIDTRANS_SERVER_KEY", "")
    MIDTRANS_CLIENT_KEY: str = os.getenv("MIDTRANS_CLIENT_KEY", "")
    MIDTRANS_IS_PRODUCTION: bool = os.getenv("MIDTRANS_IS_PRODUCTION", "False").lower() == "true"

    # AI Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    AI_ACTIVE_PROVIDER: str = os.getenv("AI_ACTIVE_PROVIDER", "gemini")
    AI_FAILOVER_MODE: str = os.getenv("AI_FAILOVER_MODE", "single")

    # Encryption
    _raw_enc_key = os.getenv("ENCRYPTION_KEY", "")
    try:
        FERNET = Fernet(_raw_enc_key.encode() if _raw_enc_key else Fernet.generate_key())
    except Exception:
        FERNET = Fernet(Fernet.generate_key())

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        if not plaintext:
            return ""
        return cls.FERNET.encrypt(plaintext.encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return cls.FERNET.decrypt(ciphertext.encode()).decode()
        except Exception:
            return ciphertext

settings = Settings()
