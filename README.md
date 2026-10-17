# 🍊 TataDana — Smart Personal Finance SaaS via Telegram

> **Tagline:** *Catat keuangan semudah chat — langsung dari Telegram kamu.*

TataDana adalah aplikasi manajemen keuangan pribadi modern terintegrasi dengan Telegram Bot. Pengguna dapat mencatat pemasukan dan pengeluaran secara instan langsung dari chat Telegram menggunakan bahasa alami, rekaman suara (Voice Note), atau foto struk belanja (AI OCR). Setiap transaksi otomatis tersimpan rapi di database Supabase (PostgreSQL) dan dapat dipantau kapan saja lewat dashboard interaktif web app.

---

## 🏗️ Tech Stack & Arsitektur

- **Backend:** FastAPI (Python 3.13 async high performance)
- **Database & Auth:** Supabase (PostgreSQL + Supabase Auth + Row Level Security + Triggers)
- **Laporan & Export:** In-App Report Generator (PDF via ReportLab, Excel via OpenPyXL) disimpan di Supabase Storage
- **Telegram Bot:** 1 bot bersama terintegrasi webhook publik, idempotent update check, parsing LLM structured output
- **AI Multi-Provider:** Google Gemini, OpenAI GPT, DeepSeek (dikonfigurasi via Admin Panel, mode Single / Paralel Failover)
- **Payment Gateway:** Midtrans (Snap & Core API) + opsi transfer manual dengan admin approval workflow
- **Timezone:** 100% Asia/Jakarta (WIB) untuk semua transaksi, reminder, dan reply bot
- **Frontend:** Premium Orange & White Fintech UI, Plus Jakarta Sans, Tailwind CSS, Lucide Icons, Chart.js

---

## 🚀 Panduan Memulai Cepat

### 1. Prasyarat
- Python 3.10+ (atau Python 3.13)
- Akun Telegram (opsional untuk bot Telegram live)

### 2. Setup Lingkungan
Buka folder proyek di terminal:
```bash
cd C:\Users\lenovo\.gemini\antigravity\scratch\tatadana
```

Aktifkan virtual environment:
```powershell
.\venv\Scripts\activate
```

File `.env` sudah otomatis dikonfigurasi dengan enkripsi Fernet untuk local development. Untuk production, lengkapi API keys di `.env`:
```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
MIDTRANS_SERVER_KEY=...
MIDTRANS_CLIENT_KEY=...
WEBHOOK_BASE_URL=http://localhost:8000
```

### 3. Migrasi Supabase
Semua skema database didefinisikan secara deklaratif di folder `supabase/migrations/`:
- `supabase/migrations/20261016000000_init_tatadana.sql`: Seluruh tabel, index, dan RLS policies.
- `supabase/migrations/20261016000001_seed_defaults.sql`: Trigger onboarding dan seed kategori default rekomendasi AI.

### 4. Menjalankan Server
```powershell
.\venv\Scripts\python run.py
```
Akses di browser: **[http://localhost:8000](http://localhost:8000)**

---

## 🔑 Kredensial Demo Siap Pakai

| Peran | Email / Identitas | Password | Keterangan |
| :--- | :--- | :--- | :--- |
| **User Demo** | `demo@tatadana.id` *(atau 081234567890)* | `demo123456` | Sudah memiliki riwayat transaksi, 3 dompet, dan kategori budget |
| **Superadmin** | `admin@tatadana.id` | `admin123456` | Akses penuh admin dashboard, audit log, impersonasi user, AI provider |

---

## 📱 Panduan Integrasi Telegram Bot (@BotFather)

1. Buka aplikasi Telegram dan cari **@BotFather**.
2. Kirim `/newbot`, tentukan nama bot dan username (misal `tatadana_user_bot`).
3. Salin HTTP API Token yang diberikan.
4. Masuk ke Dashboard TataDana &rarr; menu **Settings** &rarr; tab **Integrasi Telegram**.
5. Paste token dan klik tombol **Test Koneksi & Aktifkan Webhook**.
6. Sistem memanggil `getMe` dan mendaftarkan URL webhook secara otomatis dengan badge status 🟢 **Terhubung**.

---

## 💬 Format Pesan & Commands Telegram Bot

### Input Transaksi Alami (Bahasa Indonesia):
- `Beli bakso 15rb` *(Pengeluaran Rp 15.000)*
- `Bensin motor 50k` *(Pengeluaran Rp 50.000)*
- `Gajian bulan ini 8jt` *(Pemasukan Rp 8.000.000)*
- `Dapat komisi freelance 1.5jt` *(Pemasukan Rp 1.500.000)*
- **Voice Note:** Kirim rekaman suara &le; 60 detik (AI mentranskrip otomatis)
- **Foto Struk (Pro):** Foto struk belanjaan (AI Vision mengekstrak item dan harga)

### Commands Bot:
- `/saldo` — Cek saldo semua dompet (Cash, BCA, GoPay, dll)
- `/hari_ini` — Rekap transaksi hari ini
- `/minggu_ini` — Rekap transaksi 7 hari terakhir
- `/bulan_ini` — Rekap bulan berjalan & breakdown kategori
- `/budget` — Status budget bulanan & visual progress bar
- `/sheet` — Tautan ke dashboard web pribadi
- `/bantuan` — Panduan lengkap command bot

---

## 🛡️ Aturan Paket & Enforcement Limit

| Fitur | Starter (Rp 49.000 / bln) | Pro (Rp 99.000 Sekali Bayar) |
| :--- | :---: | :---: |
| **Batas Transaksi** | Maks 50 transaksi / bulan | **Unlimited** |
| **Batas Dompet** | Maks 3 dompet | **Unlimited** |
| **Batas Budget Kategori** | Maks 5 kategori | **Unlimited** |
| **Input Foto Struk (AI Vision)** | ❌ (Diarahkan upgrade) | ✅ Aktif |
| **AI Financial Advisor** | ❌ | ✅ Aktif Otomatis |
| **Export Laporan PDF & Excel** | ❌ (Hanya ringkasan) | ✅ Unlimited on-demand |
| **Voice Note STT** | ✅ (Maks 60s) | ✅ (Maks 60s) |
| **Reminder Harian** | ✅ (Maks 2x/hari) | ✅ (Maks 2x/hari) |

---

## 🧪 Menjalankan Test Suite Otomatis

Seluruh pipeline end-to-end telah diuji dan terverifikasi 100%:
```powershell
.\venv\Scripts\python tests\test_tatadana_e2e.py
.\venv\Scripts\python tests\test_advanced_features.py
```
