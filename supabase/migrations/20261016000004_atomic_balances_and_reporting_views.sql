-- =============================================================================
-- Migration: 20261016000004_atomic_balances_and_reporting_views.sql
-- Description: Atomisitas Saldo Dompet & Mesin Laporan Keuangan Bebas Transfer
-- Architecture: Database Trigger Atomik + Constraint Integritas + Reporting View
-- Timezone: Asia/Jakarta (WIB)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. DATABASE CONSTRAINTS: Integritas Jenis Transaksi & Transfer
-- -----------------------------------------------------------------------------
-- Memastikan transfer wajib memiliki target_wallet_id yang berbeda dengan wallet_id,
-- dan transaksi non-transfer tidak boleh memiliki target_wallet_id.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_transfer_target_wallet_integrity'
    ) THEN
        ALTER TABLE public.transactions
        ADD CONSTRAINT chk_transfer_target_wallet_integrity
        CHECK (
            (type = 'transfer' AND target_wallet_id IS NOT NULL AND target_wallet_id <> wallet_id) OR
            (type IN ('expense', 'income') AND target_wallet_id IS NULL)
        );
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. TRIGGER ATOMISITAS SALDO DOMPET (AUTOMATIC WALLET BALANCE SYNC)
-- -----------------------------------------------------------------------------
-- Menjamin setiap kali ada transaksi DITAMBAH, DIUBAH, atau DIHAPUS,
-- saldo dompet dihitung secara atomik di dalam transaksi database yang sama.

CREATE OR REPLACE FUNCTION public.sync_wallet_balances_on_transaction()
RETURNS TRIGGER AS $$
DECLARE
    v_now TIMESTAMPTZ := (NOW() AT TIME ZONE 'Asia/Jakarta');
BEGIN
    -- ---------------------------------------------------------
    -- KASUS 1: PENGHAPUSAN TRANSAKSI (DELETE)
    -- ---------------------------------------------------------
    IF (TG_OP = 'DELETE') THEN
        -- Batalkan efek transaksi lama (kembalikan saldo)
        IF OLD.type = 'expense' THEN
            UPDATE public.wallets
            SET balance = balance + OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
        ELSIF OLD.type = 'income' THEN
            UPDATE public.wallets
            SET balance = balance - OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
        ELSIF OLD.type = 'transfer' AND OLD.target_wallet_id IS NOT NULL THEN
            UPDATE public.wallets
            SET balance = balance + OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
            UPDATE public.wallets
            SET balance = balance - OLD.amount, updated_at = v_now
            WHERE id = OLD.target_wallet_id;
        END IF;
        RETURN OLD;

    -- ---------------------------------------------------------
    -- KASUS 2: PERUBAHAN TRANSAKSI (UPDATE)
    -- ---------------------------------------------------------
    ELSIF (TG_OP = 'UPDATE') THEN
        -- [A] Batalkan efek nilai transaksi lama
        IF OLD.type = 'expense' THEN
            UPDATE public.wallets
            SET balance = balance + OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
        ELSIF OLD.type = 'income' THEN
            UPDATE public.wallets
            SET balance = balance - OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
        ELSIF OLD.type = 'transfer' AND OLD.target_wallet_id IS NOT NULL THEN
            UPDATE public.wallets
            SET balance = balance + OLD.amount, updated_at = v_now
            WHERE id = OLD.wallet_id;
            UPDATE public.wallets
            SET balance = balance - OLD.amount, updated_at = v_now
            WHERE id = OLD.target_wallet_id;
        END IF;

        -- [B] Terapkan nilai transaksi baru
        IF NEW.type = 'expense' THEN
            UPDATE public.wallets
            SET balance = balance - NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
        ELSIF NEW.type = 'income' THEN
            UPDATE public.wallets
            SET balance = balance + NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
        ELSIF NEW.type = 'transfer' AND NEW.target_wallet_id IS NOT NULL THEN
            UPDATE public.wallets
            SET balance = balance - NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
            UPDATE public.wallets
            SET balance = balance + NEW.amount, updated_at = v_now
            WHERE id = NEW.target_wallet_id;
        END IF;
        RETURN NEW;

    -- ---------------------------------------------------------
    -- KASUS 3: PENAMBAHAN TRANSAKSI BARU (INSERT)
    -- ---------------------------------------------------------
    ELSIF (TG_OP = 'INSERT') THEN
        IF NEW.type = 'expense' THEN
            UPDATE public.wallets
            SET balance = balance - NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
        ELSIF NEW.type = 'income' THEN
            UPDATE public.wallets
            SET balance = balance + NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
        ELSIF NEW.type = 'transfer' AND NEW.target_wallet_id IS NOT NULL THEN
            UPDATE public.wallets
            SET balance = balance - NEW.amount, updated_at = v_now
            WHERE id = NEW.wallet_id;
            UPDATE public.wallets
            SET balance = balance + NEW.amount, updated_at = v_now
            WHERE id = NEW.target_wallet_id;
        END IF;
        RETURN NEW;
    END IF;

    RETURN NULL;
END;
-- -----------------------------------------------------------------------------
-- 2. PENCEGAHAN DOUBLE-COUNTING & FUNGSI REKONSILIASI SALDO
-- -----------------------------------------------------------------------------
-- [CATATAN PENTING ARSITEKTUR KEUANGAN]:
-- Backend TataDana (FastAPI TransactionService) sudah mengelola pemotongan dan penambahan
-- saldo secara atomik di level aplikasi (ACID Transaction with Rollback).
-- Jika trigger di bawah ini diaktifkan bersamaan saat backend berjalan, saldo akan
-- terhitung DUA KALI (Double-Counting)!
-- Oleh karena itu, fungsi disediakan di database untuk kebutuhan audit / opsional,
-- tetapi pemicu (trigger) otomatisnya dinonaktifkan secara default.

-- Fungsi Audit & Rekonsiliasi Saldo (Menghitung saldo murni berdasarkan buku besar transaksi):
CREATE OR REPLACE FUNCTION public.reconcile_wallet_balance(p_wallet_id UUID)
RETURNS NUMERIC(15, 2) AS $$
DECLARE
    v_total_income NUMERIC(15, 2);
    v_total_expense NUMERIC(15, 2);
    v_total_transfer_out NUMERIC(15, 2);
    v_total_transfer_in NUMERIC(15, 2);
    v_calculated_balance NUMERIC(15, 2);
BEGIN
    SELECT COALESCE(SUM(amount), 0.00) INTO v_total_income 
    FROM public.transactions WHERE wallet_id = p_wallet_id AND type = 'income';

    SELECT COALESCE(SUM(amount), 0.00) INTO v_total_expense 
    FROM public.transactions WHERE wallet_id = p_wallet_id AND type = 'expense';

    SELECT COALESCE(SUM(amount), 0.00) INTO v_total_transfer_out 
    FROM public.transactions WHERE wallet_id = p_wallet_id AND type = 'transfer';

    SELECT COALESCE(SUM(amount), 0.00) INTO v_total_transfer_in 
    FROM public.transactions WHERE target_wallet_id = p_wallet_id AND type = 'transfer';

    v_calculated_balance := v_total_income - v_total_expense - v_total_transfer_out + v_total_transfer_in;
    RETURN v_calculated_balance;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- -----------------------------------------------------------------------------
-- 3. SQL FUNCTION UNTUK RINGKASAN LAPORAN KEUANGAN
-- -----------------------------------------------------------------------------
-- Menghitung total pemasukan, total pengeluaran, net cashflow, dan transfer
-- secara terpisah agar transfer internal TIDAK mengotori pemasukan/pengeluaran.

CREATE OR REPLACE FUNCTION public.get_financial_summary(
    p_user_id UUID,
    p_start_date TIMESTAMPTZ DEFAULT NULL,
    p_end_date TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    total_income NUMERIC(15, 2),
    total_expense NUMERIC(15, 2),
    net_cashflow NUMERIC(15, 2),
    total_transfers NUMERIC(15, 2),
    transfer_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0.00)::NUMERIC(15, 2) AS total_income,
        COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0.00)::NUMERIC(15, 2) AS total_expense,
        (
            COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0.00) -
            COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0.00)
        )::NUMERIC(15, 2) AS net_cashflow,
        COALESCE(SUM(CASE WHEN t.type = 'transfer' THEN t.amount ELSE 0 END), 0.00)::NUMERIC(15, 2) AS total_transfers,
        COUNT(CASE WHEN t.type = 'transfer' THEN 1 END)::BIGINT AS transfer_count
    FROM public.transactions t
    WHERE t.user_id = p_user_id
      AND (p_start_date IS NULL OR t.transaction_date >= p_start_date)
      AND (p_end_date IS NULL OR t.transaction_date <= p_end_date);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
