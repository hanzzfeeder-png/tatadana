-- =============================================================================
-- Migration: 20261016000002_create_budgets_table.sql
-- Description: Dedicated monthly budgets table with Row Level Security (RLS)
-- Author: Tim TataDana
-- Timezone: Asia/Jakarta (WIB)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.budgets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
    month_year VARCHAR(7) NOT NULL, -- Format periode 'YYYY-MM', contoh: '2026-10'
    amount_limit NUMERIC(15, 2) NOT NULL CHECK (amount_limit > 0),
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Jakarta'),
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Jakarta'),
    CONSTRAINT uq_user_category_month UNIQUE(user_id, category_id, month_year)
);

-- Index untuk mempercepat query budget bulanan di dashboard
CREATE INDEX IF NOT EXISTS idx_budgets_user_period ON public.budgets(user_id, month_year);
CREATE INDEX IF NOT EXISTS idx_budgets_category ON public.budgets(category_id);

-- Aktifkan Row Level Security (RLS)
ALTER TABLE public.budgets ENABLE ROW LEVEL SECURITY;

-- Kebijakan Akses (RLS Policies): Hanya pemilik data yang berhak mengakses
CREATE POLICY "Users can view own budgets" ON public.budgets
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own budgets" ON public.budgets
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own budgets" ON public.budgets
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own budgets" ON public.budgets
    FOR DELETE USING (auth.uid() = user_id);
