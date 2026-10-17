-- =============================================================================
-- Migration: 20261016000001_seed_defaults.sql
-- Description: Automatic user onboarding trigger & default categories provisioning
-- =============================================================================

-- Function to automatically provision defaults for new user
CREATE OR REPLACE FUNCTION public.handle_new_user_setup()
RETURNS TRIGGER AS $$
DECLARE
    v_wallet_id UUID;
BEGIN
    -- 1. Create Default Profile if not exists
    INSERT INTO public.profiles (id, email, full_name, role, plan, phone_verified, default_currency)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', 'Pengguna TataDana'),
        COALESCE(NEW.raw_user_meta_data->>'role', 'user'),
        'starter',
        FALSE,
        'IDR'
    )
    ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email;

    -- 2. Create Default Wallet (Cash / Dompet Utama)
    INSERT INTO public.wallets (user_id, name, type, balance, is_default, icon, color)
    VALUES (NEW.id, 'Dompet Utama (Cash)', 'cash', 0.00, TRUE, '👛', '#FF6B00')
    RETURNING id INTO v_wallet_id;

    -- 3. Provision AI-Recommended Default Categories
    INSERT INTO public.categories (user_id, name, type, icon, color, monthly_budget, is_system)
    VALUES
        (NEW.id, 'Makanan & Minuman', 'expense', '🍜', '#FF6B00', 1500000.00, TRUE),
        (NEW.id, 'Transportasi', 'expense', '🚗', '#3B82F6', 500000.00, TRUE),
        (NEW.id, 'Hiburan & Hobi', 'expense', '🎮', '#8B5CF6', 300000.00, TRUE),
        (NEW.id, 'Tagihan & Utilitas', 'expense', '🏠', '#EF4444', 750000.00, TRUE),
        (NEW.id, 'Kesehatan', 'expense', '💊', '#10B981', 250000.00, TRUE),
        (NEW.id, 'Belanja Kebutuhan', 'expense', '👕', '#F59E0B', 500000.00, TRUE),
        (NEW.id, 'Pendidikan & Buku', 'expense', '📚', '#6366F1', 200000.00, TRUE),
        (NEW.id, 'Gaji Bulanan', 'income', '💰', '#059669', 0.00, TRUE),
        (NEW.id, 'Penghasilan Tambahan', 'income', '💼', '#10B981', 0.00, TRUE);

    -- 4. Create Default Reminder Settings
    INSERT INTO public.reminders (user_id, is_active, frequency, time_1, time_2)
    VALUES (NEW.id, TRUE, 1, '20:00:00', '08:00:00')
    ON CONFLICT (user_id) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger on auth.users after insert
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_setup();
