import unittest
import uuid
from datetime import datetime, timedelta
from app.database import get_db, init_db
from app.services.transaction_service import TransactionService
from app.services.report_service import ReportService
from app.config import get_wib_str

class TestStage2TransactionsAndReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.user1_id = f"u1_{uuid.uuid4().hex[:8]}"
        self.user2_id = f"u2_{uuid.uuid4().hex[:8]}"
        now = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()

        # Seed profiles
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User 1', 'starter', 'user', ?)",
                       (self.user1_id, f"{self.user1_id}@test.id", now))
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, 'hash', 'User 2', 'starter', 'user', ?)",
                       (self.user2_id, f"{self.user2_id}@test.id", now))

        # Seed User 1 Wallets
        self.u1_w_cash = f"w_cash_{uuid.uuid4().hex[:8]}"
        self.u1_w_bank = f"w_bank_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'Cash U1', 'cash', 100000.0, ?)",
                       (self.u1_w_cash, self.user1_id, now))
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'BCA U1', 'bank', 500000.0, ?)",
                       (self.u1_w_bank, self.user1_id, now))

        # Seed User 1 Categories
        self.u1_cat_food = f"cat_food_{uuid.uuid4().hex[:8]}"
        self.u1_cat_salary = f"cat_sal_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Makanan', 'expense', ?)",
                       (self.u1_cat_food, self.user1_id, now))
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Gaji', 'income', ?)",
                       (self.u1_cat_salary, self.user1_id, now))

        # Seed User 2 Wallet & Category
        self.u2_w = f"w_u2_{uuid.uuid4().hex[:8]}"
        self.u2_cat = f"cat_u2_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'Wallet U2', 'bank', 300000.0, ?)",
                       (self.u2_w, self.user2_id, now))
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Hobi U2', 'expense', ?)",
                       (self.u2_cat, self.user2_id, now))

        conn.commit()
        conn.close()

    def test_income_increases_balance_and_checks_category(self):
        """Memastikan transaksi pemasukan menambah saldo dan memvalidasi jenis kategori"""
        # 1. Pemasukan sah
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_bank,
            tx_type="income",
            amount=200000.0,
            category_id=self.u1_cat_salary,
            note="Bonus proyek"
        )
        self.assertIsNotNone(tx["id"])

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_bank,))
        new_balance = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(new_balance, 700000.0) # 500k + 200k

        # 2. Pemasukan dengan kategori pengeluaran harus ditolak
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_w_bank,
                tx_type="income",
                amount=50000.0,
                category_id=self.u1_cat_food # Kategori expense!
            )
        self.assertIn("tidak cocok untuk transaksi bertipe pemasukan", str(ctx.exception))

    def test_expense_decreases_balance_and_checks_nominal(self):
        """Memastikan pengeluaran memotong saldo dan menolak nominal <= 0"""
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_cash,
            tx_type="expense",
            amount=35000.0,
            category_id=self.u1_cat_food,
            note="Makan siang"
        )

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_cash,))
        new_balance = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(new_balance, 65000.0) # 100k - 35k

        # Nominal nol atau negatif ditolak
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_w_cash,
                tx_type="expense",
                amount=0.0
            )
        self.assertIn("lebih besar dari Rp 0", str(ctx.exception))

    def test_transfer_atomic_balances(self):
        """Memastikan transfer antar-dompet mengurangi asal dan menambah tujuan secara atomik"""
        # Transfer 150.000 dari BCA ke Cash
        # BCA awal: 500.000 -> 350.000
        # Cash awal: 100.000 -> 250.000
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_bank,
            target_wallet_id=self.u1_w_cash,
            tx_type="transfer",
            amount=150000.0,
            note="Tarik tunai ATM"
        )

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_bank,))
        bca_balance = cursor.fetchone()[0]
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_cash,))
        cash_balance = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(bca_balance, 350000.0)
        self.assertEqual(cash_balance, 250000.0)

    def test_date_validation(self):
        """Memastikan validasi format tanggal dan batasan tahun wajar"""
        # Format valid YYYY-MM-DD
        tx1 = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_cash,
            tx_type="expense",
            amount=10000.0,
            transaction_date="2026-10-15"
        )
        self.assertIn("2026-10-15", tx1["transaction_date"])

        # Format tidak valid
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_w_cash,
                tx_type="expense",
                amount=10000.0,
                transaction_date="tanggal-kemarin"
            )
        self.assertIn("Format tanggal tidak valid", str(ctx.exception))

        # Tahun tidak wajar
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_w_cash,
                tx_type="expense",
                amount=10000.0,
                transaction_date="1980-05-12"
            )
        self.assertIn("Tahun tanggal transaksi tidak wajar", str(ctx.exception))

    def test_transaction_crud_edit_and_delete(self):
        """Memastikan proses Lihat, Edit (Update), dan Hapus (Delete) mengembalikan saldo secara akurat"""
        # 1. Buat transaksi pengeluaran Rp 50.000 di Cash (100k -> 50k)
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_cash,
            tx_type="expense",
            amount=50000.0,
            category_id=self.u1_cat_food,
            note="Sarapan"
        )
        tx_id = tx["id"]

        # 2. Lihat detail (Get by ID)
        fetched = TransactionService.get_transaction_by_id(tx_id, self.user1_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["amount"], 50000.0)

        # 3. Edit (Update): Ubah nominal menjadi Rp 20.000 (Saldo harusnya 100k - 20k = 80k)
        updated = TransactionService.update_transaction(
            tx_id=tx_id,
            user_id=self.user1_id,
            amount=20000.0,
            note="Sarapan murah"
        )
        self.assertEqual(updated["amount"], 20000.0)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_cash,))
        cash_balance = cursor.fetchone()[0]
        self.assertEqual(cash_balance, 80000.0)

        # 4. Hapus (Delete): Saldo harus kembali utuh ke 100.000
        del_res = TransactionService.delete_transaction(tx_id, self.user1_id)
        self.assertTrue(del_res["deleted"])

        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_w_cash,))
        reverted_balance = cursor.fetchone()[0]
        self.assertEqual(reverted_balance, 100000.0)

        # Verifikasi baris sudah terhapus
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE id = ?", (tx_id,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_cross_user_isolation_on_crud(self):
        """Memastikan Pengguna 1 tidak bisa melihat, mengedit, atau menghapus transaksi Pengguna 2"""
        # User 2 membuat transaksi
        tx_u2 = TransactionService.create_transaction(
            user_id=self.user2_id,
            wallet_id=self.u2_w,
            tx_type="expense",
            amount=40000.0,
            category_id=self.u2_cat,
            note="Transaksi User 2"
        )
        tx2_id = tx_u2["id"]

        # User 1 mencoba lihat detail transaksi User 2
        view_attempt = TransactionService.get_transaction_by_id(tx2_id, self.user1_id)
        self.assertIsNone(view_attempt)

        # User 1 mencoba edit transaksi User 2
        with self.assertRaises(ValueError) as ctx:
            TransactionService.update_transaction(
                tx_id=tx2_id,
                user_id=self.user1_id,
                amount=99999.0
            )
        self.assertIn("Transaksi tidak ditemukan atau bukan milik Anda", str(ctx.exception))

        # User 1 mencoba hapus transaksi User 2
        with self.assertRaises(ValueError) as ctx:
            TransactionService.delete_transaction(tx2_id, self.user1_id)
        self.assertIn("Transaksi tidak ditemukan atau bukan milik Anda", str(ctx.exception))

    def test_financial_report_engine_excludes_transfers_and_calculates_breakdown(self):
        """
        Memastikan Mesin Laporan Keuangan:
        1. Menghitung total income, total expense, dan net cashflow secara akurat.
        2. TIDAK memasukkan transaksi transfer ke dalam total income maupun expense.
        3. Menghitung rincian pengeluaran per kategori beserta persentasenya.
        4. Menyajikan ringkasan transfer secara terpisah.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. Pemasukan Rp 1.000.000
        TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_bank,
            tx_type="income",
            amount=1000000.0,
            category_id=self.u1_cat_salary,
            note="Gaji Bulanan",
            transaction_date=f"{today} 09:00:00"
        )

        # 2. Pengeluaran Makan Rp 300.000
        TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_cash,
            tx_type="expense",
            amount=300000.0,
            category_id=self.u1_cat_food,
            note="Makan & Groceries",
            transaction_date=f"{today} 12:00:00"
        )

        # 3. Transfer Internal Rp 200.000 dari BCA ke Cash
        TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_w_bank,
            target_wallet_id=self.u1_w_cash,
            tx_type="transfer",
            amount=200000.0,
            note="Pindah dana internal",
            transaction_date=f"{today} 15:00:00"
        )

        # Generate Laporan untuk Hari Ini
        report = ReportService.get_report_summary(self.user1_id, start_date=today, end_date=today)

        # Verifikasi Inti:
        # Pemasukan = 1.000.000 (Bukan 1.200.000)
        # Pengeluaran = 300.000 (Bukan 500.000)
        # Net Cashflow = 1.000.000 - 300.000 = 700.000
        self.assertEqual(report["total_income"], 1000000.0)
        self.assertEqual(report["total_expense"], 300000.0)
        self.assertEqual(report["net_cashflow"], 700000.0)

        # Verifikasi Transfer Terisolasi
        self.assertEqual(report["transfer_summary"]["total_volume"], 200000.0)
        self.assertEqual(report["transfer_summary"]["count"], 1)

        # Verifikasi Breakdown Kategori
        self.assertGreaterEqual(len(report["category_breakdown"]), 1)
        cat_item = report["category_breakdown"][0]
        self.assertEqual(cat_item["name"], "Makanan")
        self.assertEqual(cat_item["total_spent"], 300000.0)
        self.assertEqual(cat_item["percentage"], 100.0) # Satu-satunya pengeluaran

        # Uji Error jika start_date > end_date
        with self.assertRaises(ValueError) as ctx:
            ReportService.get_report_summary(self.user1_id, start_date="2026-12-31", end_date="2026-01-01")
        self.assertIn("tidak boleh lebih besar", str(ctx.exception))

if __name__ == "__main__":
    unittest.main(verbosity=2)
