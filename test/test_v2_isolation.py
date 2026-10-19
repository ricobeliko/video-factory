"""Testes direcionados do Guarda de Isolamento da Video Factory V2."""

import os
import unittest

from app.services import isolation_guard


class TestV2IsolationGuard(unittest.TestCase):
    def test_environment_identity(self):
        self.assertEqual(isolation_guard.ENVIRONMENT_IDENTITY, "DEV_V2")

    def test_blocks_production_paths(self):
        with self.assertRaises(isolation_guard.IsolationViolationError):
            isolation_guard.validate_path_isolation(
                r"C:\Projetos\MoneyPrinterTurbo\storage\\video_factory.db",
                purpose="test_prod_block"
            )

    def test_blocks_original_dev_database(self):
        with self.assertRaises(isolation_guard.IsolationViolationError):
            isolation_guard.validate_path_isolation(
                r"D:\Projetos\MoneyPrinterTurbo\storage\\video_factory.db",
                purpose="test_dev_db_block"
            )

    def test_allows_v2_database_path(self):
        v2_db = isolation_guard.get_v2_db_path()
        self.assertIn("video_factory_v2.db", v2_db)
        self.assertIn("moneyprinterturbo-v2", v2_db.lower())
        self.assertNotIn(r"c:\projetos\moneyprinterturbo\storage", v2_db.lower())

    def test_external_publication_blocked_by_default(self):
        self.assertFalse(isolation_guard.is_external_publication_allowed())

    def test_assert_safe_environment(self):
        # Deve rodar sem lançar exceções não tratadas
        isolation_guard.assert_safe_environment()

    def test_production_environment_allows_production_path(self):
        old_env = os.environ.get("MPT_ENVIRONMENT")
        try:
            os.environ["MPT_ENVIRONMENT"] = "PRODUCTION"
            # Em modo de produção, o caminho canônico do PC Forte é permitido sem exceção
            prod_path = r"C:\Projetos\MoneyPrinterTurbo\storage\\video_factory.db"
            res = isolation_guard.validate_path_isolation(
                prod_path,
                purpose="test_prod_execution"
            )
            self.assertEqual(res, prod_path)
            self.assertTrue(isolation_guard.is_external_publication_allowed())
        finally:
            if old_env is not None:
                os.environ["MPT_ENVIRONMENT"] = old_env
            else:
                os.environ.pop("MPT_ENVIRONMENT", None)


if __name__ == "__main__":
    unittest.main()
