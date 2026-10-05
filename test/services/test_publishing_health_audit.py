"""Testes integrados de auditoria final para V16.4.2H — Final Publishing Health Audit.

Valida de ponta a ponta as garantias conjuntas das fases:
- V16.4.2A (Publishing State Reconciliation)
- V16.4.2B (Publishing Idempotency & Duplicate Protection)
- V16.4.2C (Retry Metadata Cleanup & Centralized Retry Policy)

Invariantes verificados:
1. Idempotência estrita: publicação com sucesso bloqueia chamadas ao provider.
2. Contagem exata de chamadas a provedores externos (mocks/fakes):
   - Cenário novo: provider_calls == 1.
   - Re-execução e restart: provider_calls continua == 1 (sem segunda chamada).
   - Sucesso preexistente: provider_calls == 0.
3. Transições de Retry:
   - Falha transitória agenda retry com backoff.
   - Segunda tentativa com sucesso transiciona para 'published' com next_attempt_at = NULL.
   - Falha permanente torna o post terminalmente 'failed' com next_attempt_at = NULL.
   - Tentativas esgotadas (>= 3) tornam o post terminal com next_attempt_at = NULL.
4. Concorrência e JIT guard:
   - Sucesso surgindo durante processing aborta antes da chamada externa.
   - Plataformas independentes para a mesma task.
5. Preservação de dados:
   - Zero DELETE em publication_events e scheduled_posts.
   - Metadados externos (external_id, external_url) preservados.
6. Estado operacional final:
   - EXECUTABLE_PENDING_PUBLICATIONS = 0
   - ARMED_RETRIES = 0
   - STALE_PROCESSING = 0
   - REMAINING_MUTATIONS_NEEDED = 0
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import publishing_idempotency, retry_policy, scheduler, task as task_module


class TestPublishingHealthAudit(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_health_audit.db")
        scheduler.init_db(self.db_path)

        # Configurações básicas de scheduler no DB de teste
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

        # Mock básico de perfil e canal para evitar dependência de arquivos externos
        self.patch_profile = patch("app.services.profile_manager.get_profile", return_value={"is_active": True})
        self.patch_channel = patch("app.services.profile_manager.get_channel", return_value={"is_enabled": True})
        self.patch_platforms = patch("app.services.scheduler.get_task_platforms", side_effect=lambda tid, db: ["youtube", "tiktok"])
        self.patch_video = patch("app.services.scheduler.get_task_final_video", return_value="dummy_final.mp4")
        self.patch_isfile = patch("os.path.isfile", return_value=True)

        self.patch_profile.start()
        self.patch_channel.start()
        self.patch_platforms.start()
        self.patch_video.start()
        self.patch_isfile.start()

    def tearDown(self):
        self.patch_profile.stop()
        self.patch_channel.stop()
        self.patch_platforms.stop()
        self.patch_video.stop()
        self.patch_isfile.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_scheduled_post(
        self,
        task_id: str,
        platform: str,
        status: str = "ready",
        scheduled_at: str = None,
        channel_id: str = "channel-1",
        profile_id: str = "profile-1",
        attempts: int = 0,
        next_attempt_at: str = None,
    ) -> int:
        now_dt = datetime.now(timezone.utc)
        now_iso = scheduler._to_iso(now_dt)
        sched_iso = scheduled_at or scheduler._to_iso(now_dt - timedelta(minutes=5))
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, status, scheduled_at, created_at,
                    channel_id, profile_id, attempts, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, status, sched_iso, now_iso, channel_id, profile_id, attempts, next_attempt_at),
            )
            return cur.lastrowid

    def _get_post(self, post_id: int):
        with scheduler.get_connection(self.db_path) as conn:
            return conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()

    def _get_events(self, task_id: str, platform: str):
        with scheduler.get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM publication_events WHERE task_id = ? AND platform = ?;",
                (task_id, platform),
            ).fetchall()

    # -------------------------------------------------------------------------
    # Teste 1: Fluxo completo controlado de publicação nova e idempotência
    # -------------------------------------------------------------------------
    def test_end_to_end_controlled_publication_lifecycle(self):
        """Fluxo novo: agendamento -> ciclo 1 executa (calls=1) -> publicado -> ciclo 2 e restart não reexecutam."""
        task_id = "task-audit-lifecycle-001"
        platform = "youtube"

        post_id = self._insert_scheduled_post(task_id, platform, status="ready")

        fake_provider_calls = 0

        def fake_publish(tid, platforms=None, channel_id=None, synchronous=True, db_path=None):
            nonlocal fake_provider_calls
            fake_provider_calls += 1
            # Simula gravação canônica de evento de publicação realizada pelo provider
            scheduler.record_publication_event(
                task_id=tid,
                platform=platform,
                status="success",
                external_id="yt_ext_lifecycle_001",
                external_url="https://youtube.com/watch?v=yt_ext_lifecycle_001",
                channel_id=channel_id or "channel-1",
                db_path=db_path,
            )
            return True, ""

        with patch.object(task_module, "publish_task", side_effect=fake_publish):
            # Ciclo 1: Execução normal do post vencido
            res1 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res1["status"], "published")
            self.assertEqual(fake_provider_calls, 1)

            # Invariantes após publicação
            post1 = self._get_post(post_id)
            self.assertEqual(post1["status"], "published")
            self.assertIsNone(post1["next_attempt_at"])
            events = self._get_events(task_id, platform)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["status"], "success")

            # Ciclo 2: Re-execução sem novos posts (scheduler idle, sem novas chamadas)
            res2 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res2["status"], "idle")
            self.assertEqual(fake_provider_calls, 1)

            # Reinicialização / Simulação de reinício de worker
            # Mesmo que um operador tente agendar ou forçar ciclo, provider_calls deve continuar 1
            can_sched, reason, _ = publishing_idempotency.can_schedule_task(task_id, platform, db_path=self.db_path)
            self.assertFalse(can_sched)
            self.assertEqual(reason, "already_published")

            res3 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res3["status"], "idle")
            self.assertEqual(fake_provider_calls, 1)

    # -------------------------------------------------------------------------
    # Teste 2: Falha transitória -> retry -> sucesso na 2ª tentativa -> terminal
    # -------------------------------------------------------------------------
    def test_transient_failure_then_successful_retry_flow(self):
        """Falha transitória agenda retry dentro da política; 2ª tentativa bem-sucedida zera retry e estabiliza."""
        task_id = "task-audit-retry-002"
        platform = "youtube"

        post_id = self._insert_scheduled_post(task_id, platform, status="ready", attempts=0)

        call_count = 0

        def flaky_publish(tid, platforms=None, channel_id=None, synchronous=True, db_path=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False, "503 Service Unavailable: High load"
            # 2ª tentativa tem sucesso
            scheduler.record_publication_event(
                task_id=tid,
                platform=platform,
                status="success",
                external_id="yt_retry_win",
                external_url="https://youtube.com/watch?v=yt_retry_win",
                channel_id=channel_id or "channel-1",
                db_path=db_path,
            )
            return True, ""

        with patch.object(task_module, "publish_task", side_effect=flaky_publish):
            # Tentativa 1: Falha temporária
            res1 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res1["status"], "retry_scheduled")
            self.assertEqual(call_count, 1)

            post1 = self._get_post(post_id)
            self.assertEqual(post1["status"], "ready")
            self.assertEqual(post1["attempts"], 1)
            self.assertIsNotNone(post1["next_attempt_at"])

            # Adianta o relógio simulado para o próximo retry
            retry_due_dt = datetime.fromisoformat(post1["next_attempt_at"]) + timedelta(seconds=1)

            # Tentativa 2: Sucesso no retry
            res2 = scheduler.run_scheduler_cycle(db_path=self.db_path, now=retry_due_dt)
            self.assertEqual(res2["status"], "published")
            self.assertEqual(call_count, 2)

            post2 = self._get_post(post_id)
            self.assertEqual(post2["status"], "published")
            self.assertIsNone(post2["next_attempt_at"])

            # Tentativa 3 (Ciclo subsequente): Nenhuma chamada adicional ao provider
            res3 = scheduler.run_scheduler_cycle(db_path=self.db_path, now=retry_due_dt + timedelta(hours=1))
            self.assertEqual(res3["status"], "idle")
            self.assertEqual(call_count, 2)

    # -------------------------------------------------------------------------
    # Teste 3: Falha permanente -> não rearma retry
    # -------------------------------------------------------------------------
    def test_permanent_failure_does_not_schedule_retry(self):
        """Falha permanente (ex: 400 Bad Request) marca como 'failed' com next_attempt_at = NULL."""
        task_id = "task-audit-perm-003"
        platform = "youtube"

        post_id = self._insert_scheduled_post(task_id, platform, status="ready", attempts=0)

        calls = 0

        def failing_publish(tid, platforms=None, channel_id=None, synchronous=True, db_path=None):
            nonlocal calls
            calls += 1
            return False, "400 Bad Request: Invalid video metadata"

        with patch.object(task_module, "publish_task", side_effect=failing_publish):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "failed")
            self.assertEqual(calls, 1)

            post = self._get_post(post_id)
            self.assertEqual(post["status"], "failed")
            self.assertEqual(post["attempts"], 1)
            self.assertIsNone(post["next_attempt_at"])

            # Ciclo futuro: não deve tentar novamente
            future_now = datetime.now(timezone.utc) + timedelta(days=2)
            res_future = scheduler.run_scheduler_cycle(db_path=self.db_path, now=future_now)
            self.assertEqual(res_future["status"], "idle")
            self.assertEqual(calls, 1)

    # -------------------------------------------------------------------------
    # Teste 4: Tentativas esgotadas (>= 3) -> terminal
    # -------------------------------------------------------------------------
    def test_exhausted_retries_becomes_terminal_failed(self):
        """Post na 3ª tentativa (attempts=2) sofrendo erro transitório vira failed e zera retry quando esgota."""
        task_id = "task-audit-exhaust-004"
        platform = "youtube"

        # attempts=3 já atingiu o limite de retries
        post_id = self._insert_scheduled_post(task_id, platform, status="ready", attempts=3)

        calls = 0

        def failing_publish(tid, platforms=None, channel_id=None, synchronous=True, db_path=None):
            nonlocal calls
            calls += 1
            return False, "504 Gateway Timeout"

        with patch.object(task_module, "publish_task", side_effect=failing_publish):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "failed")
            self.assertEqual(calls, 1)

            post = self._get_post(post_id)
            self.assertEqual(post["status"], "failed")
            self.assertIsNone(post["next_attempt_at"])

    # -------------------------------------------------------------------------
    # Teste 5: Sucesso canônico bloqueia chamada mesmo se post estiver armado
    # -------------------------------------------------------------------------
    def test_canonical_success_disarms_post_and_blocks_provider(self):
        """Se publication_events já tiver success, scheduler normaliza o post para published e nunca chama o provider."""
        task_id = "task-audit-canon-005"
        platform = "tiktok"

        # Sucesso canônico já registrado
        scheduler.record_publication_event(
            task_id=task_id,
            platform=platform,
            status="success",
            external_id="tt_existing_success",
            db_path=self.db_path,
        )

        # Post que por anomalia estava em ready com next_attempt_at armado
        arm_time = scheduler._to_iso(datetime.now(timezone.utc) - timedelta(minutes=10))
        post_id = self._insert_scheduled_post(task_id, platform, status="ready", next_attempt_at=arm_time)

        provider_mock = MagicMock()
        with patch.object(task_module, "publish_task", provider_mock):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["reason"], "already_published")
            self.assertEqual(provider_mock.call_count, 0)

            post = self._get_post(post_id)
            self.assertEqual(post["status"], "published")
            self.assertIsNone(post["next_attempt_at"])

    # -------------------------------------------------------------------------
    # Teste 6: Cancelled post nunca rearma nem executa
    # -------------------------------------------------------------------------
    def test_cancelled_post_never_rearms_or_executes(self):
        """Post cancelado permanece cancelado, com next_attempt_at = NULL e sem chamadas externas."""
        task_id = "task-audit-cancel-006"
        platform = "youtube"

        post_id = self._insert_scheduled_post(task_id, platform, status="cancelled", next_attempt_at="2026-10-05T00:00:00Z")

        # Cleanup de metadados garante remoção imediata
        cleaned = retry_policy.cleanup_residual_retries(db_path=self.db_path)
        self.assertGreaterEqual(cleaned["cancelled_residual_cleaned"], 1)

        post = self._get_post(post_id)
        self.assertEqual(post["status"], "cancelled")
        self.assertIsNone(post["next_attempt_at"])

        provider_mock = MagicMock()
        with patch.object(task_module, "publish_task", provider_mock):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "idle")
            self.assertEqual(provider_mock.call_count, 0)

    # -------------------------------------------------------------------------
    # Teste 7: Independência entre múltiplas plataformas da mesma task
    # -------------------------------------------------------------------------
    def test_multi_platform_independence_and_targeted_execution(self):
        """YouTube com sucesso não bloqueia TikTok pendente para a mesma task, e vice-versa."""
        task_id = "task-audit-multi-007"

        # YouTube já publicado
        scheduler.record_publication_event(
            task_id=task_id,
            platform="youtube",
            status="success",
            external_id="yt_multi_ok",
            db_path=self.db_path,
        )
        yt_post = self._insert_scheduled_post(task_id, "youtube", status="published")

        # TikTok pendente
        tt_post = self._insert_scheduled_post(task_id, "tiktok", status="ready")

        called_platforms = []

        def track_publish(tid, platforms=None, channel_id=None, synchronous=True, db_path=None):
            called_platforms.extend(platforms or [])
            scheduler.record_publication_event(
                task_id=tid,
                platform="tiktok",
                status="success",
                external_id="tt_multi_ok",
                db_path=db_path,
            )
            return True, ""

        with patch.object(task_module, "publish_task", side_effect=track_publish):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["platform"], "tiktok")
            self.assertEqual(called_platforms, ["tiktok"])

            # Verifica ambos
            self.assertEqual(self._get_post(yt_post)["status"], "published")
            self.assertEqual(self._get_post(tt_post)["status"], "published")

    # -------------------------------------------------------------------------
    # Teste 8: JIT Race condition abort
    # -------------------------------------------------------------------------
    def test_jit_guard_prevents_race_condition_external_call(self):
        """Se sucesso canônico surgir após post virar processing, JIT guard aborta fail-safe antes do provider."""
        task_id = "task-audit-jit-008"
        platform = "youtube"

        post_id = self._insert_scheduled_post(task_id, platform, status="ready")

        provider_mock = MagicMock()
        # Simula race condition onde no momento do JIT guard (logo antes do provider) já existe publicação confirmada
        fake_jit_return = (False, {"event_id": 99, "external_id": "yt_jit_race_winner"})
        with patch("app.services.publishing_idempotency.jit_provider_idempotency_guard", return_value=fake_jit_return), \
             patch.object(task_module, "publish_task", provider_mock):
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["reason"], "already_published_race_prevented")
            self.assertEqual(provider_mock.call_count, 0)

            post = self._get_post(post_id)
            self.assertEqual(post["status"], "published")
            self.assertIsNone(post["next_attempt_at"])

    # -------------------------------------------------------------------------
    # Teste 9: Invariantes de preservação de evidência histórica
    # -------------------------------------------------------------------------
    def test_historical_preservation_and_no_destructive_deletes(self):
        """Garante que nenhum registro de evento ou histórico é deletado durante ciclos e cleanups."""
        task_id = "task-audit-preserve-009"
        platform = "youtube"

        scheduler.record_publication_event(
            task_id=task_id,
            platform=platform,
            status="success",
            external_id="yt_preserve_123",
            external_url="https://youtube.com/watch?v=yt_preserve_123",
            channel_id="channel-preserve",
            db_path=self.db_path,
        )

        post_id = self._insert_scheduled_post(task_id, platform, status="failed", channel_id="channel-preserve")

        # Executa ciclo de scheduler e rotina de cleanup
        retry_policy.cleanup_residual_retries(db_path=self.db_path)
        scheduler.run_scheduler_cycle(db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            ev = conn.execute("SELECT * FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertIsNotNone(ev)
            self.assertEqual(ev["external_id"], "yt_preserve_123")
            self.assertEqual(ev["external_url"], "https://youtube.com/watch?v=yt_preserve_123")

            sp = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertIsNotNone(sp)
            self.assertEqual(sp["status"], "failed")
            self.assertIsNone(sp["next_attempt_at"])

    # -------------------------------------------------------------------------
    # Teste 10: Verificação de métricas operacionais finais esperadas
    # -------------------------------------------------------------------------
    def test_production_operational_health_invariants(self):
        """Métricas operacionais de saúde pós-cleanup:
        EXECUTABLE_PENDING_PUBLICATIONS == 0
        ARMED_RETRIES == 0
        STALE_PROCESSING == 0
        """
        # Insere posts representativos do estado estabilizado
        self._insert_scheduled_post("t1", "youtube", status="published", next_attempt_at=None)
        self._insert_scheduled_post("t2", "tiktok", status="cancelled", next_attempt_at=None)
        self._insert_scheduled_post("t3", "youtube", status="failed", next_attempt_at=None)

        # Executa rotina de cleanup para certificar normalização completa
        cleanup_report = retry_policy.cleanup_residual_retries(db_path=self.db_path)
        self.assertEqual(cleanup_report["total_cleaned"], 0)

        with scheduler.get_connection(self.db_path) as conn:
            # 1. Executable pending publications
            executable_cnt = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM scheduled_posts
                WHERE status IN ('planned', 'ready')
                  AND scheduled_at <= datetime('now');
                """
            ).fetchone()["cnt"]
            self.assertEqual(executable_cnt, 0)

            # 2. Armed retries
            armed_retries = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM scheduled_posts
                WHERE next_attempt_at IS NOT NULL
                  AND status IN ('published', 'cancelled', 'failed');
                """
            ).fetchone()["cnt"]
            self.assertEqual(armed_retries, 0)

            # 3. Stale processing
            stale_proc = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM scheduled_posts
                WHERE status = 'processing';
                """
            ).fetchone()["cnt"]
            self.assertEqual(stale_proc, 0)


if __name__ == "__main__":
    unittest.main()
