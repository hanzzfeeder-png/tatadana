-- =============================================================================
-- Migration: 20261016000003_enforce_transaction_wallet_ownership.sql
-- Description: Proteksi Ketat Kepemilikan Wallet & Kategori pada Transaksi
-- Architecture: Database Trigger + RLS WITH CHECK (Multi-Layer Defense)
-- Timezone: Asia/Jakarta (WIB)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. FUNGSI TRIGGER: Validasi Kepemilikan Wallet & Kategori (Database Constraint)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.check_transaction_ownership()
RETURNS TRIGGER AS $$
BEGIN
    -- [1] Verifikasi Dompet Asal (wallet_id): Wajib milik pengguna transaksi
    IF NOT EXISTS (
        SELECT 1 FROM public.wallets
        WHERE id = NEW.wallet_id AND user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'Akses Ditolak: Dompet asal (wallet_id: %) bukan milik pengguna ini (user_id: %)!', NEW.wallet_id, NEW.user_id;
    END IF;

    -- [2] Verifikasi Dompet Tujuan (target_wallet_id) jika jenis transfer
    IF NEW.target_wallet_id IS NOT NULL THEN
        -- Dompet asal dan target tidak boleh sama
        IF NEW.wallet_id = NEW.target_wallet_id THEN
            RAISE EXCEPTION 'Akses Ditolak: Dompet asal dan dompet tujuan transfer tidak boleh sama!';
        END IF;

        -- Dompet target wajib milik pengguna transaksi yang sama
        IF NOT EXISTS (
            SELECT 1 FROM public.wallets
            WHERE id = NEW.target_wallet_id AND user_id = NEW.user_id
        ) THEN
            RAISE EXCEPTION 'Akses Ditolak: Dompet tujuan transfer (target_wallet_id: %) bukan milik pengguna ini!', NEW.target_wallet_id;
        END IF;
    END IF;

    -- [3] Verifikasi Kategori (category_id) jika diisi
    IF NEW.category_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.categories
            WHERE id = NEW.category_id AND user_id = NEW.user_id
        ) THEN
            RAISE EXCEPTION 'Akses Ditolak: Kategori transaksi (category_id: %) bukan milik pengguna ini!', NEW.category_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Pasang Trigger untuk operasi INSERT dan UPDATE pada tabel transactions
DROP TRIGGER IF EXISTS trg_check_transaction_ownership ON public.transactions;
CREATE TRIGGER trg_check_transaction_ownership
    BEFORE INSERT OR UPDATE ON public.transactions
    FOR EACH ROW
    EXECUTE FUNCTION public.check_transaction_ownership();

-- -----------------------------------------------------------------------------
-- 2. PENINGKATAN KEBIJAKAN ROW LEVEL SECURITY (RLS WITH CHECK)
-- -----------------------------------------------------------------------------
-- Memperkuat RLS agar PostgreSQL menolak request di level RLS bahkan sebelum trigger berjalan.

-- Update Policy INSERT: Memastikan user_id, wallet_id, dan target_wallet_id milik user login
DROP POLICY IF EXISTS "Users can insert own transactions" ON public.transactions;
CREATE POLICY "Users can insert own transactions" ON public.transactions
FOR INSERT WITH CHECK (
    auth.uid() = user_id
    AND EXISTS (
        SELECT 1 FROM public.wallets w
        WHERE w.id = wallet_id AND w.user_id = auth.uid()
    )
    AND (
        target_wallet_id IS NULL OR EXISTS (
            SELECT 1 FROM public.wallets tw
            WHERE tw.id = target_wallet_id AND tw.user_id = auth.uid()
        )
    )
);

-- Update Policy UPDATE: Memastikan user_id, wallet_id, dan target_wallet_id tetap milik user login
DROP POLICY IF EXISTS "Users can update own transactions" ON public.transactions;
CREATE POLICY "Users can update own transactions" ON public.transactions
FOR UPDATE USING (auth.uid() = user_id)
WITH CHECK (
    auth.uid() = user_id
    AND EXISTS (
        SELECT 1 FROM public.wallets w
        WHERE w.id = wallet_id AND w.user_id = auth.uid()
    )
    AND (
        target_wallet_id IS NULL OR EXISTS (
            SELECT 1 FROM public.wallets tw
            WHERE tw.id = target_wallet_id AND tw.user_id = auth.uid()
        )
    )
);
