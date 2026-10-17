-- =============================================================================
-- Migration: 20261016000005_telegram_pairing_and_idempotency.sql
-- Description: Tabel One-Time Pairing Token (Hashed) & Penguatan Idempotency
-- Architecture: Hashed One-Time Tokens + RLS + Race-Condition Safe Updates
-- Timezone: Asia/Jakarta (WIB)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. TABEL TELEGRAM PAIR TOKENS (One-Time Token Penautan Akun Aman)
-- -----------------------------------------------------------------------------
-- Menyimpan token acak dalam bentuk hash (SHA-256) dengan masa berlaku 10 menit
-- dan batasan maksimal percobaan (max_attempts = 5) untuk mencegah brute-force.

CREATE TABLE IF NOT EXISTS public.telegram_pair_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_preview TEXT NOT NULL, -- Contoh: 'TD-A1B2...' untuk ditampilkan di UI
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Jakarta')
);

-- Indeks untuk lookup cepat berdasarkan hash token
CREATE INDEX IF NOT EXISTS idx_pair_tokens_hash ON public.telegram_pair_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_pair_tokens_user ON public.telegram_pair_tokens(user_id);

-- Aktifkan Row Level Security (RLS)
ALTER TABLE public.telegram_pair_tokens ENABLE ROW LEVEL SECURITY;

-- Pengguna hanya boleh melihat dan membuat token miliknya sendiri
CREATE POLICY "Users can manage own pair tokens" ON public.telegram_pair_tokens
    FOR ALL USING (auth.uid() = user_id);

-- -----------------------------------------------------------------------------
-- 2. PENGUATAN TABEL TELEGRAM UPDATES (IDEMPOTENCY & RACE-CONDITION PROTECTION)
-- -----------------------------------------------------------------------------
-- Memastikan kolom update_id adalah PRIMARY KEY agar penanganan concurrent request
-- dari Telegram tertolak otomatis di level constraint jika update_id identik masuk bersamaan.

CREATE TABLE IF NOT EXISTS public.telegram_updates (
    update_id BIGINT PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Jakarta')
);
