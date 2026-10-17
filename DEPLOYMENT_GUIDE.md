# Panduan Deployment & Produksi TataDana

Dokumen ini adalah panduan langkah-demi-langkah untuk merilis aplikasi **TataDana** dari lingkungan pengembangan lokal ke server produksi cloud (**Railway** atau **Render**) dan menghubungkannya dengan Bot Telegram live.

---

## 1. Persiapan File Konfigurasi Produksi

Pastikan file-file berikut telah tersedia di direktori proyek:
- `Procfile` : Menentukan perintah start server pada container cloud (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- `runtime.txt` : Menentukan versi runtime Python (`python-3.11.9`).
- `requirements.txt` : Seluruh dependensi library Python siap instalasi.
- `scripts/set_production_webhook.py` : Skrip helper pendaftaran webhook Telegram.
- `.gitignore` : Memastikan file `.env`, database lokal, dan file temporary **TIDAK** ter-upload ke repositori publik.

---

## 2. Langkah 1: Push Proyek ke GitHub

1. Buka terminal di folder proyek (`tatadana`).
2. Pastikan file `.env` tidak terdeteksi oleh Git:
   ```bash
   git status
   ```
   *(Pastikan `.env` ada di file `.gitignore` dan tidak berwarna hijau/untracked).*

3. Lakukan commit dan push ke GitHub:
   ```bash
   git init
   git add .
   git commit -m "feat: release candidate production tatadana v1.0"
   git branch -M main
   git remote add origin https://github.com/USERNAME_ANDA/tatadana.git
   git push -u origin main
   ```

---

## 3. Langkah 2: Deploy ke Platform Cloud Hosting

Pilih salah satu platform hosting berikut:

### Opsi A: Railway (Rekomendasi — Paling Mudah & Cepat)
1. Buka [railway.app](https://railway.app/) dan login menggunakan akun GitHub Anda.
2. Klik **New Project** &rarr; **Deploy from GitHub repo**.
3. Pilih repositori **tatadana**. Railway akan otomatis mendeteksi Python dan file `Procfile`.
4. Tambahkan **Persistent Volume** (Penyimpanan Tetap SQLite & Laporan):
   - Masuk ke tab **Volumes** di service proyek Anda.
   - Buat volume baru dengan mount path: `/app/storage`.
5. Masuk ke tab **Settings** &rarr; **Networking** &rarr; Klik **Generate Domain** (contoh: `https://tatadana-production.up.railway.app`).
6. Buka tab **Variables** dan isi variabel lingkungan (lihat Bagian 4 di bawah).
7. Railway akan otomatis me-redeploy aplikasi Anda.

---

### Opsi B: Render
1. Buka [render.com](https://render.com/) dan login.
2. Klik **New +** &rarr; **Web Service**.
3. Hubungkan repositori GitHub **tatadana**.
4. Isi konfigurasi:
   - **Name**: `tatadana`
   - **Region**: Singapore (Southeast Asia - latency terendah untuk Indonesia)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Tambahkan **Disk** (Persistent Storage):
   - Masuk ke menu **Disks** &rarr; Add Disk.
   - Mount path: `/opt/render/project/src/storage` (ukuran: 1 GB sudah sangat cukup).
6. Masuk ke tab **Environment** dan isi variabel lingkungan (lihat Bagian 4).
7. Klik **Create Web Service**.

---

## 4. Langkah 3: Konfigurasi Environment Variables (Wajib)

Salin nilai-nilai berikut ke tab **Environment Variables** di dashboard hosting Anda:

| Variabel | Contoh Nilai | Keterangan |
|:---|:---|:---|
| `APP_NAME` | `TataDana` | Nama aplikasi |
| `APP_ENV` | `production` | Mode aplikasi produksi |
| `DEBUG` | `False` | Matikan debug mode di produksi |
| `APP_TIMEZONE` | `Asia/Jakarta` | Zona waktu stempel transaksi (WIB) |
| `SECRET_KEY` | *(String acak minimal 32 karakter)* | Kunci JWT token autentikasi web |
| `ENCRYPTION_KEY` | *(Fernet 32-byte base64)* | Kunci enkripsi API key AI di database |
| `WEBHOOK_BASE_URL` | `https://tatadana-production.up.railway.app` | **URL publik domain hosting Anda (HTTPS, tanpa slash akhir)** |
| `TELEGRAM_BOT_TOKEN` | `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ` | Token Bot Telegram dari [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | *(String acak, contoh: `td_sec_2026_xyz`)* | Secret header validasi request Telegram |
| `SUPABASE_URL` | `https://your-project.supabase.co` | URL project Supabase Anda |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJhbGciOi...` | Service role key Supabase |
| `SUPABASE_STORAGE_BUCKET` | `tatadana-exports` | Bucket storage untuk backup file laporan |
| `GEMINI_API_KEY` | `AIzaSy...` | (Opsional) API Key Google Gemini untuk NLP/Vision |
| `MIDTRANS_SERVER_KEY` | `Mid-server-...` | (Opsional) Server Key Midtrans payment gateway |
| `MIDTRANS_CLIENT_KEY` | `Mid-client-...` | (Opsional) Client Key Midtrans payment gateway |
| `MIDTRANS_IS_PRODUCTION` | `True` | Ubah ke True jika memakai akun live Midtrans |

> [!TIP]
> Untuk membuat `SECRET_KEY` dan `ENCRYPTION_KEY` baru yang aman secara kriptografis di terminal lokal:
> ```bash
> python -c "import secrets; from cryptography.fernet import Fernet; print('SECRET_KEY=' + secrets.token_hex(24)); print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
> ```

---

## 5. Langkah 4: Registrasi Webhook Bot Telegram

Setelah aplikasi berhasil di-deploy dan URL HTTPS publik sudah aktif:

1. Di komputer lokal Anda (atau melalui Web Shell di platform hosting), jalankan:
   ```bash
   python scripts/set_production_webhook.py
   ```
2. Skrip akan otomatis membaca `TELEGRAM_BOT_TOKEN`, `WEBHOOK_BASE_URL`, dan `TELEGRAM_WEBHOOK_SECRET` dari file `.env`, lalu mendaftarkannya ke Telegram API.
3. Anda akan melihat konfirmasi sukses:
   ```
   🎉 [SUKSES] Webhook Telegram Berhasil Dipasang!
   URL: https://tatadana-production.up.railway.app/api/telegram/webhook
   ```
4. Untuk memverifikasi status webhook kapan saja:
   ```bash
   python scripts/set_production_webhook.py --info
   ```

---

## 6. Langkah 5: Checklist Pengujian Pasca-Rilis (Production Verification)

- [ ] **Akses Landing Page Publik**: Buka `https://DOMAIN_ANDA/` di browser. Pastikan halaman termuat dengan responsif dan cepat.
- [ ] **Registrasi Pengguna Baru**: Buka `/register`, daftarkan nomor HP Indonesia, input OTP demo/SMS, dan selesaikan wizard 3 pertanyaan onboarding.
- [ ] **Penautan Akun Telegram**:
  1. Masuk ke `/dashboard/settings`.
  2. Klik tombol **Hubungkan Telegram** untuk menyalin One-Time Pairing Code (format: `TD-XXXXXX`).
  3. Buka bot Anda di Telegram dan ketik `/start TD-XXXXXX`.
  4. Bot harus membalas konfirmasi bahwa akun Anda telah terhubung!
- [ ] **Uji Catat Transaksi Telegram**:
  1. Kirim chat: `Beli makan siang 35rb`.
  2. Bot akan membalas rincian pengeluaran, kategori, sisa saldo, dan progres budget.
  3. Buka dashboard web (`/dashboard/transaksi`), pastikan transaksi baru langsung muncul dengan stempel waktu WIB yang akurat.
- [ ] **Uji Ekspor Laporan**:
  1. Buka `/dashboard/laporan`.
  2. Unduh laporan Excel dan PDF untuk memastikan file berhasil digenerate di server.
- [ ] **Akses Superadmin**:
  1. Masuk menggunakan akun admin di `/admin`.
  2. Pastikan overview statistik sistem, kelola pengguna, audit log, dan provider AI berfungsi normal.

---

🎉 **Selamat! Aplikasi FinTech TataDana Anda kini telah resmi aktif di lingkungan produksi cloud.**
