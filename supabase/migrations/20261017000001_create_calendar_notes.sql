-- =============================================================================
-- Migration: 20261017000001_create_calendar_notes.sql
-- Description: Tabel Catatan Harian Kalender Keuangan (Daily Financial Notes)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.calendar_daily_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    note_date DATE NOT NULL,
    note_text TEXT NOT NULL,
    mood TEXT DEFAULT 'neutral' CHECK (mood IN ('happy', 'neutral', 'sad', 'saving', 'splurge')),
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('Asia/Jakarta', NOW()),
    updated_at TIMESTAMPTZ DEFAULT TIMEZONE('Asia/Jakarta', NOW()),
    CONSTRAINT unique_user_daily_note UNIQUE (user_id, note_date)
);

-- Index untuk pencarian cepat berdasarkan user dan tanggal
CREATE INDEX IF NOT EXISTS idx_calendar_notes_user_date ON public.calendar_daily_notes(user_id, note_date);

-- Enable RLS
ALTER TABLE public.calendar_daily_notes ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Users can view their own calendar notes"
    ON public.calendar_daily_notes
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own calendar notes"
    ON public.calendar_daily_notes
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own calendar notes"
    ON public.calendar_daily_notes
    FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own calendar notes"
    ON public.calendar_daily_notes
    FOR DELETE
    USING (auth.uid() = user_id);
