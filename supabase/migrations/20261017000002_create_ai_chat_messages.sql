-- =============================================================================
-- Migration: 20261017000002_create_ai_chat_messages.sql
-- Description: Tabel Riwayat Percakapan Tata AI Assistant di Web Dashboard
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.ai_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    message TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('Asia/Jakarta', NOW())
);

-- Index untuk query riwayat percakapan berdasarkan user dan urutan waktu
CREATE INDEX IF NOT EXISTS idx_ai_chat_user_created ON public.ai_chat_messages(user_id, created_at ASC);

-- Enable Row Level Security (RLS)
ALTER TABLE public.ai_chat_messages ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Users can view their own chat messages"
    ON public.ai_chat_messages
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own chat messages"
    ON public.ai_chat_messages
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete their own chat messages"
    ON public.ai_chat_messages
    FOR DELETE
    USING (auth.uid() = user_id);
