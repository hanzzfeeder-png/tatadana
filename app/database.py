import sqlite3
import json
import uuid
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.config import settings, get_wib_now, get_wib_str

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "tatadana.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Profiles
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        phone_number TEXT UNIQUE,
        phone_verified INTEGER DEFAULT 0,
        otp_code TEXT,
        otp_expires_at TEXT,
        plan TEXT NOT NULL DEFAULT 'free',
        role TEXT NOT NULL DEFAULT 'user',
        is_admin INTEGER DEFAULT 0,
        avatar_url TEXT,
        default_currency TEXT NOT NULL DEFAULT 'IDR',
        created_at TEXT,
        updated_at TEXT
    );
    """)
    try:
        cursor.execute("ALTER TABLE profiles ADD COLUMN is_admin INTEGER DEFAULT 0")
    except Exception:
        pass

    # Wallets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'bank',
        balance REAL NOT NULL DEFAULT 0.0,
        is_default INTEGER NOT NULL DEFAULT 0,
        icon TEXT DEFAULT '👛',
        color TEXT DEFAULT '#FF6B00',
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Categories
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        icon TEXT NOT NULL DEFAULT '🏷️',
        color TEXT NOT NULL DEFAULT '#FF6B00',
        monthly_budget REAL DEFAULT 0.0,
        is_system INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Transactions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        wallet_id TEXT NOT NULL,
        target_wallet_id TEXT,
        category_id TEXT,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        note TEXT,
        transaction_date TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'web',
        receipt_url TEXT,
        receipt_items TEXT DEFAULT '[]',
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (wallet_id) REFERENCES wallets(id),
        FOREIGN KEY (category_id) REFERENCES categories(id)
    );
    """)

    # Telegram Links
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_links (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        telegram_user_id INTEGER UNIQUE NOT NULL,
        telegram_chat_id INTEGER NOT NULL,
        telegram_username TEXT,
        phone_number TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Telegram Updates (Idempotency)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_updates (
        update_id INTEGER PRIMARY KEY,
        processed_at TEXT
    );
    """)

    # Telegram Pair Tokens (Hashed, 10 min expiry, max attempts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_pair_tokens (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        token_hash TEXT UNIQUE NOT NULL,
        token_preview TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Bot Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bot_settings (
        id TEXT PRIMARY KEY,
        bot_token_encrypted TEXT NOT NULL,
        webhook_url TEXT,
        is_connected INTEGER DEFAULT 0,
        bot_username TEXT,
        last_tested_at TEXT,
        updated_at TEXT
    );
    """)

    # AI Providers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_providers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        provider_type TEXT NOT NULL,
        model_name TEXT NOT NULL,
        api_key_encrypted TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 1,
        mode TEXT DEFAULT 'single',
        created_at TEXT,
        updated_at TEXT
    );
    """)

    # AI Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        source TEXT NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        status TEXT NOT NULL,
        error_message TEXT,
        created_at TEXT
    );
    """)

    # Subscriptions & Payments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        plan TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        payment_type TEXT NOT NULL,
        order_id TEXT UNIQUE NOT NULL,
        gross_amount REAL NOT NULL,
        payment_proof_url TEXT,
        is_approved INTEGER DEFAULT 0,
        admin_notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Export History
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS export_history (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        storage_url TEXT NOT NULL,
        period_start TEXT,
        period_end TEXT,
        download_count INTEGER DEFAULT 0,
        expires_at TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Reminders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id TEXT PRIMARY KEY,
        user_id TEXT UNIQUE NOT NULL,
        is_active INTEGER DEFAULT 1,
        frequency INTEGER DEFAULT 1,
        time_1 TEXT DEFAULT '08:00',
        time_2 TEXT DEFAULT '20:00',
        last_sent_date TEXT,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # Admin Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_audit_logs (
        id TEXT PRIMARY KEY,
        admin_id TEXT NOT NULL,
        action TEXT NOT NULL,
        target_user_id TEXT,
        details TEXT,
        ip_address TEXT,
        created_at TEXT
    );
    """)

    # Calendar Daily Notes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS calendar_daily_notes (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        note_date TEXT NOT NULL,
        note_text TEXT NOT NULL,
        mood TEXT DEFAULT 'neutral',
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(user_id, note_date),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    # AI Chat Messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_chat_messages (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        message TEXT NOT NULL,
        tokens INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    seed_initial_data(conn)
    conn.close()

def seed_initial_data(conn):
    cursor = conn.cursor()
    from app.security import hash_password

    # Check if admin exists
    cursor.execute("SELECT id FROM profiles WHERE email = 'admin@tatadana.id'")
    admin = cursor.fetchone()
    if not admin:
        admin_id = str(uuid.uuid4())
        now = get_wib_str()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, phone_number, phone_verified, plan, role, default_currency, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, 'pro', 'superadmin', 'IDR', ?, ?)
        """, (admin_id, 'admin@tatadana.id', hash_password('admin123456'), 'Super Admin TataDana', '081122334455', now, now))

    # Check if demo user exists
    cursor.execute("SELECT id FROM profiles WHERE email = 'demo@tatadana.id'")
    demo = cursor.fetchone()
    if not demo:
        demo_id = str(uuid.uuid4())
        now = get_wib_str()
        cursor.execute("""
        INSERT INTO profiles (id, email, password_hash, full_name, phone_number, phone_verified, plan, role, default_currency, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, 'pro', 'user', 'IDR', ?, ?)
        """, (demo_id, 'demo@tatadana.id', hash_password('demo123456'), 'Budi Pratama', '081234567890', now, now))

        # Seed Wallets for Demo User
        w_cash_id = str(uuid.uuid4())
        w_bca_id = str(uuid.uuid4())
        w_gopay_id = str(uuid.uuid4())

        cursor.execute("""
        INSERT INTO wallets (id, user_id, name, type, balance, is_default, icon, color, created_at, updated_at)
        VALUES 
            (?, ?, 'Dompet Tunai', 'cash', 1250000.0, 1, '💵', '#FF6B00', ?, ?),
            (?, ?, 'Bank BCA (Payroll)', 'bank', 8750000.0, 0, '🏦', '#3B82F6', ?, ?),
            (?, ?, 'GoPay & OVO', 'ewallet', 450000.0, 0, '📱', '#10B981', ?, ?)
        """, (w_cash_id, demo_id, now, now, w_bca_id, demo_id, now, now, w_gopay_id, demo_id, now, now))

        # Seed Categories for Demo User
        cats = [
            (str(uuid.uuid4()), demo_id, 'Makanan & Minuman', 'expense', '🍜', '#FF6B00', 2500000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Transportasi', 'expense', '🚗', '#3B82F6', 800000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Hiburan & Hobi', 'expense', '🎮', '#8B5CF6', 600000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Tagihan & Utilitas', 'expense', '🏠', '#EF4444', 1200000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Kesehatan', 'expense', '💊', '#10B981', 400000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Belanja Kebutuhan', 'expense', '👕', '#F59E0B', 1000000.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Gaji Bulanan', 'income', '💰', '#059669', 0.0, 1, now),
            (str(uuid.uuid4()), demo_id, 'Freelance & Side Job', 'income', '💼', '#10B981', 0.0, 1, now)
        ]
        cursor.executemany("""
        INSERT INTO categories (id, user_id, name, type, icon, color, monthly_budget, is_system, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, cats)

        # Seed Sample Transactions for Demo User
        cat_map = {name: cid for cid, _, name, _, _, _, _, _, _ in cats}
        
        # Today and recent dates
        t1 = get_wib_str(get_wib_now() - timedelta(days=0, hours=2))
        t2 = get_wib_str(get_wib_now() - timedelta(days=0, hours=5))
        t3 = get_wib_str(get_wib_now() - timedelta(days=1, hours=3))
        t4 = get_wib_str(get_wib_now() - timedelta(days=2, hours=4))
        t5 = get_wib_str(get_wib_now() - timedelta(days=5, hours=1))
        t6 = get_wib_str(get_wib_now() - timedelta(days=15))

        sample_txs = [
            (str(uuid.uuid4()), demo_id, w_bca_id, None, cat_map['Gaji Bulanan'], 'income', 12000000.0, 'Gaji Pokok & Tunjangan Oktober', t6, 'web', None, '[]', t6),
            (str(uuid.uuid4()), demo_id, w_gopay_id, None, cat_map['Makanan & Minuman'], 'expense', 45000.0, 'Makan siang Nasi Padang + Es Teh', t1, 'telegram_text', None, '[]', t1),
            (str(uuid.uuid4()), demo_id, w_cash_id, None, cat_map['Transportasi'], 'expense', 20000.0, 'Bensin motor & parkir', t2, 'telegram_text', None, '[]', t2),
            (str(uuid.uuid4()), demo_id, w_bca_id, None, cat_map['Tagihan & Utilitas'], 'expense', 450000.0, 'Tagihan Listrik PLN & Wi-Fi', t3, 'web', None, '[]', t3),
            (str(uuid.uuid4()), demo_id, w_cash_id, None, cat_map['Belanja Kebutuhan'], 'expense', 185000.0, 'Belanja bulanan Supermarket Indomaret', t4, 'telegram_photo', None, json.dumps([
                {"name": "Minyak Goreng 2L", "price": 38000, "category": "Belanja Kebutuhan"},
                {"name": "Beras 5kg", "price": 75000, "category": "Belanja Kebutuhan"},
                {"name": "Sabun & Shampoo", "price": 42000, "category": "Belanja Kebutuhan"},
                {"name": "Kopi Sachet", "price": 30000, "category": "Makanan & Minuman"}
            ]), t4),
            (str(uuid.uuid4()), demo_id, w_gopay_id, None, cat_map['Freelance & Side Job'], 'income', 1500000.0, 'Project Landing Page Client', t5, 'web', None, '[]', t5)
        ]

        cursor.executemany("""
        INSERT INTO transactions (id, user_id, wallet_id, target_wallet_id, category_id, type, amount, note, transaction_date, source, receipt_url, receipt_items, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sample_txs)

        # Reminder settings
        cursor.execute("""
        INSERT INTO reminders (id, user_id, is_active, frequency, time_1, time_2, created_at, updated_at)
        VALUES (?, ?, 1, 1, '20:00', '08:00', ?, ?)
        """, (str(uuid.uuid4()), demo_id, now, now))

    # Seed Default AI Providers (Gemini, OpenAI, DeepSeek)
    cursor.execute("SELECT COUNT(*) FROM ai_providers")
    if cursor.fetchone()[0] == 0:
        now = get_wib_str()
        ai_list = [
            (str(uuid.uuid4()), 'Google Gemini Pro & Flash', 'gemini', 'gemini-1.5-flash', settings.encrypt(settings.GEMINI_API_KEY or 'dummy_gemini_key'), 1, 1, 'single', now, now),
            (str(uuid.uuid4()), 'OpenAI GPT-4o & GPT-4o-mini', 'openai', 'gpt-4o-mini', settings.encrypt(settings.OPENAI_API_KEY or 'dummy_openai_key'), 0, 2, 'single', now, now),
            (str(uuid.uuid4()), 'DeepSeek V3 & R1', 'deepseek', 'deepseek-chat', settings.encrypt(settings.DEEPSEEK_API_KEY or 'dummy_deepseek_key'), 0, 3, 'single', now, now)
        ]
        cursor.executemany("""
        INSERT INTO ai_providers (id, name, provider_type, model_name, api_key_encrypted, is_active, priority, mode, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ai_list)

    conn.commit()
