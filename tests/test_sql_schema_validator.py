import os
import re
import unittest

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "supabase", "migrations")

class TestSupabaseSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql_files = sorted([
            os.path.join(MIGRATIONS_DIR, f)
            for f in os.listdir(MIGRATIONS_DIR)
            if f.endswith(".sql")
        ])
        cls.combined_sql = ""
        for fpath in cls.sql_files:
            with open(fpath, "r", encoding="utf-8") as f:
                cls.combined_sql += f.read() + "\n"

    def test_migration_files_present(self):
        """Memastikan minimal 3 file migrasi tersedia di supabase/migrations"""
        self.assertGreaterEqual(len(self.sql_files), 3)
        filenames = [os.path.basename(f) for f in self.sql_files]
        self.assertIn("20261016000000_init_tatadana.sql", filenames)
        self.assertIn("20261016000001_seed_defaults.sql", filenames)
        self.assertIn("20261016000002_create_budgets_table.sql", filenames)

    def test_core_tables_exist(self):
        """Memastikan 5 tabel inti TataDana didefinisikan secara eksplisit"""
        core_tables = ["profiles", "wallets", "categories", "transactions", "budgets"]
        for table in core_tables:
            pattern = rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?{table}\s*\("
            match = re.search(pattern, self.combined_sql, re.IGNORECASE)
            self.assertIsNotNone(match, f"Tabel {table} harus didefinisikan dalam SQL migrasi.")

    def test_foreign_keys_and_user_isolation(self):
        """Memastikan tabel wallets, categories, transactions, budgets terikat ke profiles(id)"""
        dependent_tables = ["wallets", "categories", "transactions", "budgets"]
        for table in dependent_tables:
            # Cari blok CREATE TABLE untuk tabel terkait
            table_match = re.search(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?{table}\s*\((.*?)\);", self.combined_sql, re.IGNORECASE | re.DOTALL)
            self.assertIsNotNone(table_match, f"Blok CREATE TABLE untuk {table} tidak ditemukan.")
            table_body = table_match.group(1)
            
            # Cek user_id mengarah ke profiles(id)
            self.assertTrue(
                "user_id" in table_body and ("profiles(id)" in table_body or "public.profiles(id)" in table_body),
                f"Tabel {table} wajib memiliki user_id yang merujuk ke profiles(id) dengan ON DELETE CASCADE"
            )

    def test_rls_enabled_for_all_core_tables(self):
        """Memastikan Row Level Security (RLS) diaktifkan untuk semua tabel data pengguna"""
        core_tables = ["profiles", "wallets", "categories", "transactions", "budgets"]
        for table in core_tables:
            pattern = rf"ALTER\s+TABLE\s+(?:public\.)?{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY\s*;"
            match = re.search(pattern, self.combined_sql, re.IGNORECASE)
            self.assertIsNotNone(match, f"Tabel {table} wajib memiliki perintah ENABLE ROW LEVEL SECURITY;")

    def test_rls_policies_for_budgets(self):
        """Memastikan tabel budgets memiliki RLS policy lengkap (SELECT, INSERT, UPDATE, DELETE)"""
        for op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
            pattern = rf"CREATE\s+POLICY\s+.*?ON\s+(?:public\.)?budgets\s+FOR\s+{op}\s+"
            match = re.search(pattern, self.combined_sql, re.IGNORECASE)
            self.assertIsNotNone(match, f"Tabel budgets wajib memiliki kebijakan RLS untuk operasi {op}")

    def test_indonesian_wib_timezone_consistency(self):
        """Memastikan timezone default disetel ke Asia/Jakarta (WIB)"""
        self.assertIn("Asia/Jakarta", self.combined_sql)

    def test_transaction_ownership_trigger_and_rls(self):
        """Memastikan trigger kepemilikan wallet dan penguatan RLS terdefinisi"""
        filenames = [os.path.basename(f) for f in self.sql_files]
        self.assertIn("20261016000003_enforce_transaction_wallet_ownership.sql", filenames)
        self.assertIn("trg_check_transaction_ownership", self.combined_sql)
        self.assertIn("check_transaction_ownership", self.combined_sql)
        self.assertIn("BEFORE INSERT OR UPDATE ON public.transactions", self.combined_sql)

    def test_stage2_atomic_trigger_and_reporting_sql(self):
        """Memastikan constraint integritas transfer, fungsi rekonsiliasi, dan fungsi laporan kas murni terdefinisi"""
        filenames = [os.path.basename(f) for f in self.sql_files]
        self.assertIn("20261016000004_atomic_balances_and_reporting_views.sql", filenames)
        self.assertIn("chk_transfer_target_wallet_integrity", self.combined_sql)
        self.assertIn("reconcile_wallet_balance", self.combined_sql)
        self.assertIn("get_financial_summary", self.combined_sql)

    def test_stage3_telegram_pairing_sql(self):
        """Memastikan tabel telegram_pair_tokens dan RLS-nya terdefinisi dalam skema migrasi"""
        filenames = [os.path.basename(f) for f in self.sql_files]
        self.assertIn("20261016000005_telegram_pairing_and_idempotency.sql", filenames)
        self.assertIn("telegram_pair_tokens", self.combined_sql)
        self.assertIn("token_hash", self.combined_sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", self.combined_sql)
        self.assertIn("telegram_updates", self.combined_sql)

if __name__ == "__main__":
    unittest.main(verbosity=2)
