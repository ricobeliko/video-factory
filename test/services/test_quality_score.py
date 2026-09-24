import os
import shutil
import tempfile
import unittest

from app.models import const
from app.services import analytics, quality_score, safety_gate


class TestQualityScore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_quality_")
        self.db_path = os.path.join(self.test_dir, "quality_test.db")
        quality_score.DB_PATH = self.db_path
        safety_gate.DB_PATH = self.db_path
        analytics.DB_PATH = self.db_path
        quality_score.init_quality_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        analytics.init_analytics_db(self.db_path)

    def tearDown(self):
        quality_score.DB_PATH = None
        safety_gate.DB_PATH = None
        analytics.DB_PATH = None
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_deterministic_score(self):
        """1. A avaliação de qualidade deve ser 100% determinística para os mesmos inputs."""
        res1 = quality_score.evaluate_quality(
            topic="Por que os oceanos são salgados?",
            niche="Curiosidades",
            hook_text="Você sabia que os oceanos têm tanto sal que cobririam a Terra?",
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=68.0,
            db_path=self.db_path,
        )
        res2 = quality_score.evaluate_quality(
            topic="Por que os oceanos são salgados?",
            niche="Curiosidades",
            hook_text="Você sabia que os oceanos têm tanto sal que cobririam a Terra?",
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=68.0,
            db_path=self.db_path,
        )
        self.assertEqual(res1["quality_score"], res2["quality_score"])
        self.assertEqual(res1["quality_label"], res2["quality_label"])
        self.assertEqual(res1["components"], res2["components"])

    def test_02_missing_components_redistribute_weight(self):
        """2. Ausência de componentes (ex: sem trend_id ou sem histórico) redistribui o peso proporcionalmente."""
        # Sem trend, sem source_confidence, sem historical_performance
        res = quality_score.evaluate_quality(
            topic="Como funciona um motor a combustão?",
            niche="Ciência",
            hook_text="Como uma gota de combustível move uma tonelada?",
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=65.0,
            db_path=self.db_path,
        )
        self.assertIsNone(res["components"]["trend_strength"])
        self.assertIsNone(res["components"]["source_confidence"])
        self.assertIsNone(res["components"]["historical_performance"])
        # Score final deve estar no intervalo válido [0, 100]
        self.assertGreaterEqual(res["quality_score"], 0.0)
        self.assertLessEqual(res["quality_score"], 100.0)

    def test_03_strong_hook_vs_generic_intro(self):
        """3. Hook direto e instigante pontua significativamente melhor que introdução genérica."""
        score_strong, _ = quality_score.calculate_hook_strength("Por que os aviões não voam no espaço?")
        score_generic, _ = quality_score.calculate_hook_strength("Hoje vamos falar sobre aviões voando no espaço.")
        self.assertGreater(score_strong, score_generic)
        self.assertGreaterEqual(score_strong - score_generic, 30.0)

    def test_04_repeated_hook_loses_score(self):
        """4. Hook repetido no histórico recente perde pontuação por redundância."""
        recent = ["Você sabia que os gatos dormem 16 horas por dia?"]
        fresh_score, _ = quality_score.calculate_hook_strength(
            "Por que os gatos ronronam?", recent_hooks=recent
        )
        repeated_score, _ = quality_score.calculate_hook_strength(
            "Você sabia que os gatos dormem 16 horas por dia?", recent_hooks=recent
        )
        self.assertGreater(fresh_score, repeated_score)

    def test_05_repeated_topic_loses_originality(self):
        """5. Tema idêntico ou muito similar ao histórico recente perde originalidade."""
        recent = ["Por que os oceanos são salgados?"]
        orig_fresh, _ = quality_score.calculate_originality("Como os vulcões entram em erupção?", recent)
        orig_repeat, _ = quality_score.calculate_originality("Por que o oceano é salgado?", recent)
        self.assertGreater(orig_fresh, orig_repeat)
        self.assertLess(orig_repeat, 40.0)

    def test_06_trend_id_reuses_trend_score(self):
        """6. Presença de trend_id calcula trend strength combinando trend e opportunity score."""
        score_none, _ = quality_score.calculate_trend_strength(trend_id=None)
        self.assertIsNone(score_none)

        score_trend, _ = quality_score.calculate_trend_strength(
            trend_id="tid-123", trend_score=80.0, opportunity_score=85.0, verification="multi"
        )
        self.assertIsNotNone(score_trend)
        self.assertGreaterEqual(score_trend, 85.0)

    def test_07_source_confidence_conversion(self):
        """7. Conversão determinística de source_confidence: HIGH=100, MEDIUM=70, LOW=40."""
        sc_high, _ = quality_score.calculate_source_confidence("HIGH")
        sc_med, _ = quality_score.calculate_source_confidence("MEDIUM")
        sc_low, _ = quality_score.calculate_source_confidence("LOW")
        sc_none, _ = quality_score.calculate_source_confidence(None)

        self.assertEqual(sc_high, 100.0)
        self.assertEqual(sc_med, 70.0)
        self.assertEqual(sc_low, 40.0)
        self.assertIsNone(sc_none)

    def test_08_repetition_risk_inverted(self):
        """8. Repetition risk invertido: baixo risco = score alto, alto risco = score baixo."""
        recent = [
            {"topic": "Mistérios do Triângulo das Bermudas", "narrative_structure": "investigative_mystery"},
            {"topic": "Mistérios de Atlântida", "narrative_structure": "investigative_mystery"},
        ]
        # Alto risco (tópico similar e mesma estrutura repetida)
        score_high_risk, _ = quality_score.calculate_repetition_risk(
            "Mistérios do Triângulo das Bermudas",
            narrative_structure="investigative_mystery",
            recent_items=recent,
        )
        # Baixo risco (tópico diferente)
        score_low_risk, _ = quality_score.calculate_repetition_risk(
            "Como funciona uma usina solar?",
            narrative_structure="explainer",
            recent_items=recent,
        )
        self.assertGreater(score_low_risk, score_high_risk)

    def test_09_narrative_fit_investigative(self):
        """9. Narrative fit para investigative_mystery pontua alto com termos de mistério/enigma."""
        fit_good, _ = quality_score.calculate_narrative_fit(
            "O mistério do navio que desapareceu sem deixar pistas",
            narrative_structure=const.STRUCTURE_MYSTERY,
        )
        fit_neutral, _ = quality_score.calculate_narrative_fit(
            "Receita fácil de pão caseiro",
            narrative_structure=const.STRUCTURE_MYSTERY,
        )
        self.assertGreater(fit_good, fit_neutral)
        self.assertGreaterEqual(fit_good, 85.0)

    def test_10_narrative_fit_explainer(self):
        """10. Narrative fit para explainer pontua alto com termos de explicação científica/causal."""
        fit_good, _ = quality_score.calculate_narrative_fit(
            "Entenda como funciona a gravidade e a física por que caímos",
            narrative_structure=const.STRUCTURE_EXPLAINER,
        )
        self.assertGreaterEqual(fit_good, 85.0)

    def test_11_duration_fit_cross_platform(self):
        """11. Duration fit para cross_platform: 62-75s recebe 100, <60s penalizado."""
        fit_ideal, _ = quality_score.calculate_duration_fit(
            actual_duration=68.0, preset=const.PRESET_CROSS_PLATFORM
        )
        fit_short, _ = quality_score.calculate_duration_fit(
            actual_duration=45.0, preset=const.PRESET_CROSS_PLATFORM
        )
        self.assertEqual(fit_ideal, 100.0)
        self.assertLessEqual(fit_short, 35.0)

    def test_12_historical_performance_none_under_3_samples(self):
        """12. Historical performance retorna estritamente None quando existem menos de 3 amostras."""
        # Salva apenas 2 amostras no analytics
        analytics.save_snapshot(
            task_id="t1", platform="youtube", narrative_structure="investigative_mystery",
            views=1000, likes=100, db_path=self.db_path
        )
        analytics.save_snapshot(
            task_id="t2", platform="youtube", narrative_structure="investigative_mystery",
            views=1200, likes=110, db_path=self.db_path
        )

        hist_score, _ = quality_score.calculate_historical_performance_signal(
            narrative_structure="investigative_mystery", db_path=self.db_path
        )
        self.assertIsNone(hist_score)

    def test_13_historical_performance_used_with_3_or_more_samples(self):
        """13. Historical performance é calculado quando há 3 ou mais amostras no histórico."""
        # Adiciona a 3ª amostra
        for i in range(1, 4):
            analytics.save_snapshot(
                task_id=f"t-hist-{i}", platform="youtube", narrative_structure="explainer",
                views=2000 * i, likes=150 * i, db_path=self.db_path
            )

        hist_score, reasons = quality_score.calculate_historical_performance_signal(
            narrative_structure="explainer", db_path=self.db_path
        )
        self.assertIsNotNone(hist_score)
        self.assertGreater(len(reasons), 0)

    def test_14_visual_match_concrete_over_abstract(self):
        """14. Termos visuais concretos (mar, avião) pontuam melhor que conceitos puramente abstratos."""
        score_concrete, _ = quality_score.calculate_visual_match_potential("Oceano profundo e tubarão gigante")
        score_abstract, _ = quality_score.calculate_visual_match_potential("Significado existencial e dilema moral da mente")
        self.assertGreater(score_concrete, score_abstract)
        self.assertGreaterEqual(score_concrete, 85.0)
        self.assertLessEqual(score_abstract, 55.0)

    def test_15_operational_tiers_strong_good_review_weak(self):
        """15. Classificação correta nas faixas operacionais STRONG, GOOD, REVIEW e WEAK."""
        self.assertEqual(quality_score.determine_quality_label(90.0), quality_score.LABEL_STRONG)
        self.assertEqual(quality_score.determine_quality_label(85.0), quality_score.LABEL_STRONG)
        self.assertEqual(quality_score.determine_quality_label(77.0), quality_score.LABEL_GOOD)
        self.assertEqual(quality_score.determine_quality_label(70.0), quality_score.LABEL_GOOD)
        self.assertEqual(quality_score.determine_quality_label(60.0), quality_score.LABEL_REVIEW)
        self.assertEqual(quality_score.determine_quality_label(55.0), quality_score.LABEL_REVIEW)
        self.assertEqual(quality_score.determine_quality_label(45.0), quality_score.LABEL_WEAK)

    def test_16_persistence(self):
        """16. Persistência correta na tabela content_quality_scores."""
        eval_res = quality_score.evaluate_quality(
            topic="Como os relâmpagos se formam na atmosfera?",
            niche="Ciência",
            hook_text="O que gera a energia de um raio?",
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=65.0,
            persist=True,
            db_path=self.db_path,
        )
        self.assertIsNotNone(eval_res["id"])

        recent = quality_score.get_recent_quality_scores(limit=5, db_path=self.db_path)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["topic"], "Como os relâmpagos se formam na atmosfera?")
        self.assertEqual(recent[0]["quality_label"], eval_res["quality_label"])

    def test_17_reasons_generation(self):
        """17. Gera justificativas estruturadas (reasons) destacando pontos fortes e pontos de atenção."""
        eval_res = quality_score.evaluate_quality(
            topic="Por que os aviões deixam rastros no céu?",
            niche="Curiosidades",
            hook_text="Você sabia que os rastros de avião são nuvens artificiais?",
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=66.0,
            db_path=self.db_path,
        )
        self.assertGreaterEqual(len(eval_res["reasons"]), 2)
        self.assertTrue(any("+" in r or "-" in r for r in eval_res["reasons"]))

    def test_18_quality_score_does_not_alter_safety_gate(self):
        """18. Quality score é independente e não substitui nem altera os vereditos do Safety Gate."""
        # Safety Gate avalia limites de segurança (PASS / REVIEW / BLOCK)
        sg_assessment = safety_gate.evaluate_script_safety(
            task_id="task-test-sg",
            topic="Vídeo de Teste",
            script="Texto curto com poucas palavras.",
            preset=const.PRESET_CROSS_PLATFORM,
            db_path=self.db_path,
        )
        # Quality Score avalia potencial de conteúdo
        q_eval = quality_score.evaluate_quality(
            topic="Vídeo de Teste",
            preset=const.PRESET_CROSS_PLATFORM,
            script_text="Texto curto com poucas palavras.",
            db_path=self.db_path,
        )
        # Safety Gate mantém seus status e regras originais
        self.assertIn(sg_assessment["safety_status"], [const.SAFETY_STATUS_PASS, const.SAFETY_STATUS_REVIEW, const.SAFETY_STATUS_BLOCK])
        # Quality Score tem sua própria escala 0-100 e label
        self.assertIn(q_eval["quality_label"], [quality_score.LABEL_STRONG, quality_score.LABEL_GOOD, quality_score.LABEL_REVIEW, quality_score.LABEL_WEAK])

    def test_19_rss_single_source_never_100(self):
        """19. RSS single_source nunca resulta em confidence 100, mesmo se confidence_str for HIGH."""
        score, _ = quality_score.calculate_source_confidence(
            confidence_str="HIGH",
            source="rss",
            source_count=1,
            verification="single_source",
        )
        self.assertNotEqual(score, 100.0)
        self.assertLessEqual(score, 70.0)

    def test_20_rss_single_source_results_in_70(self):
        """20. RSS single_source resulta em 70 (MEDIUM normalizado)."""
        score, _ = quality_score.calculate_source_confidence(
            confidence_str="HIGH",
            source="rss",
            source_count=1,
            verification="single_source",
        )
        self.assertEqual(score, 70.0)

    def test_21_google_trends_official_results_in_100(self):
        """21. Google Trends oficial pode resultar em 100 (HIGH)."""
        score, _ = quality_score.calculate_source_confidence(
            confidence_str="HIGH",
            source="google_trends",
            source_count=1,
            verification="single_source",
        )
        self.assertEqual(score, 100.0)

    def test_22_multi_source_results_in_100(self):
        """22. multi_source pode resultar em 100 (HIGH)."""
        score, _ = quality_score.calculate_source_confidence(
            confidence_str="HIGH",
            source="rss",
            source_count=2,
            verification="multi_source",
        )
        self.assertEqual(score, 100.0)

    def test_23_relevance_score_v4_prevailed_over_lexical(self):
        """23. relevance_score vindo da V4 prevalece sobre fallback lexical."""
        score, reasons = quality_score.calculate_niche_relevance(
            topic="Curiosidades incríveis sobre ciência e mistérios",
            niche="Curiosidades",
            trend_relevance_score=25.0,
        )
        self.assertEqual(score, 25.0)
        self.assertTrue(any("Trend Radar" in r for r in reasons))

    def test_24_political_item_with_relevance_v4_keeps_20_in_v6(self):
        """24. item político com relevance V4 = 20 mantém relevância 20 na V6."""
        eval_res = quality_score.evaluate_quality(
            topic="Cármen Lúcia: 7 curiosidades sobre a ministra do STF que pediu desculpas ao povo brasileiro",
            niche="Curiosidades",
            trend_id="trend-carmen-stf",
            trend_score=35.0,
            relevance_score=20.0,
            source="rss",
            verification="single_source",
            source_confidence="HIGH",
            db_path=self.db_path,
        )
        self.assertEqual(eval_res["components"]["niche_relevance"], 20.0)
        self.assertEqual(eval_res["components"]["source_confidence"], 70.0)
        self.assertLess(eval_res["quality_score"], 68.0)

        # Fallback lexical sem V4 também detecta menção institucional/STF e aplica 20 no nicho Curiosidades
        eval_fallback = quality_score.evaluate_quality(
            topic="Cármen Lúcia: 7 curiosidades sobre a ministra do STF que pediu desculpas ao povo brasileiro",
            niche="Curiosidades",
            db_path=self.db_path,
        )
        self.assertEqual(eval_fallback["components"]["niche_relevance"], 20.0)

    def test_25_refresh_reload_preserves_trend_id_and_data(self):
        """25. refresh/reload preserva trend_id e dados necessários via get_recent_quality_scores."""
        from app.services import trend_radar
        trend_radar.init_trend_db(self.db_path)
        with quality_score.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trend_items (
                    trend_id, title, normalized_topic, source, source_count, verification,
                    trend_score, novelty_score, relevance_score, source_confidence, opportunity_score,
                    collected_at, niche, language, region, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "test-trend-123", "Tema de Tendência Teste", "tema de tendencia teste", "rss", 1, "single_source",
                    60.0, 50.0, 45.0, "HIGH", 52.0,
                    "2026-09-17T00:00:00Z", "Curiosidades", "pt-BR", "BR", "USED"
                ),
            )

        eval_res = quality_score.evaluate_quality(
            topic="Tema de Tendência Teste",
            trend_id="test-trend-123",
            niche="Curiosidades",
            persist=True,
            db_path=self.db_path,
        )
        self.assertEqual(eval_res["components"]["niche_relevance"], 45.0)
        self.assertEqual(eval_res["components"]["source_confidence"], 70.0)

        recent = quality_score.get_recent_quality_scores(limit=5, db_path=self.db_path)
        self.assertGreaterEqual(len(recent), 1)
        found = next((r for r in recent if r.get("trend_id") == "test-trend-123"), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["source"], "rss")
        self.assertEqual(found["verification"], "single_source")
        self.assertEqual(found["relevance_score"], 45.0)

    def test_26_idea_without_trend_id_works_fine(self):
        """26. ideia sem trend_id continua funcionando sem inventar sinal de tendência."""
        eval_res = quality_score.evaluate_quality(
            topic="Por que os oceanos são salgados se a água dos rios é doce?",
            niche="Curiosidades",
            trend_id=None,
            db_path=self.db_path,
        )
        self.assertIsNone(eval_res["components"]["trend_strength"])
        self.assertIsNone(eval_res["components"]["source_confidence"])
        self.assertGreaterEqual(eval_res["components"]["niche_relevance"], 80.0)
        self.assertGreaterEqual(eval_res["quality_score"], 65.0)
        self.assertIn(eval_res["quality_label"], [quality_score.LABEL_GOOD, quality_score.LABEL_STRONG])


    def test_27_quality_score_excludes_current_task_self_comparison(self):
        """27. Regressão V15-C: task presente em monetization_safety não se auto-compara.
        
        Garante:
        A) Current task presente em monetization_safety não se compara consigo mesma.
        B) Outra task com tópico/hook idêntico continua penalizada.
        C) Tópicos diferentes não recebem artificialmente originality=0 e repetition=40.
        D) Threshold continua 70 (LABEL_GOOD >= 70.0, LABEL_REVIEW < 70.0).
        E) Pesos COMPONENT_WEIGHTS permanecem intactos.
        F) Persistência continua funcionando sem mutação de schema.
        """
        import sqlite3

        current_task_id = "task-v15c-current"
        current_topic = "Por que Júpiter possui uma tempestade gigante?"
        current_hook = "Você sabia que a tempestade de Júpiter dura centenas de anos?"

        # E) Validar pesos nominais intocados
        expected_weights = {
            "hook_strength": 0.15,
            "originality": 0.15,
            "trend_strength": 0.10,
            "niche_relevance": 0.10,
            "source_confidence": 0.05,
            "repetition_risk": 0.10,
            "narrative_fit": 0.10,
            "duration_fit": 0.10,
            "historical_performance": 0.10,
            "visual_match": 0.05,
        }
        self.assertEqual(quality_score.COMPONENT_WEIGHTS, expected_weights)
        self.assertAlmostEqual(sum(quality_score.COMPONENT_WEIGHTS.values()), 1.0, places=4)

        # D) Validar que o threshold operacional de aprovação continua 70.0
        self.assertEqual(quality_score.determine_quality_label(70.0), quality_score.LABEL_GOOD)
        self.assertEqual(quality_score.determine_quality_label(69.9), quality_score.LABEL_REVIEW)

        # Inserir histórico com a própria task (simulando a etapa anterior do fluxo autônomo onde
        # o safety gate é gravado antes do quality score)
        with sqlite3.connect(self.db_path) as conn:
            # Task histórica legítima diferente
            conn.execute(
                """
                INSERT INTO monetization_safety (
                    task_id, topic, preset, narrative_structure, word_count,
                    estimated_duration, actual_duration, safety_status,
                    safety_reasons, hook_text, cta_text, checked_at
                ) VALUES ('task-hist-old', 'A história dos fósseis na Antártica', 'cross_platform', 'fact_context', 150, 65.0, 65.0, 'PASSED', '', 'Você sabia sobre os fósseis sob o gelo?', '', '2026-09-20T10:00:00Z');
                """
            )
            # A PRÓPRIA task atual já salva pelo safety gate
            conn.execute(
                """
                INSERT INTO monetization_safety (
                    task_id, topic, preset, narrative_structure, word_count,
                    estimated_duration, actual_duration, safety_status,
                    safety_reasons, hook_text, cta_text, checked_at
                ) VALUES (?, ?, 'cross_platform', 'explainer', 150, 65.0, 65.0, 'PASSED', '', ?, '', '2026-09-23T20:00:00Z');
                """,
                (current_task_id, current_topic, current_hook)
            )

        # A) Avaliar quality score com task_id da task atual
        # F) Com persist=True para validar persistência
        res_current = quality_score.evaluate_quality(
            topic=current_topic,
            hook_text=current_hook,
            task_id=current_task_id,
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=65.0,
            db_path=self.db_path,
            persist=True,
        )

        # C) Tópicos diferentes não recebem artificialmente originality=0 e repetition=40
        self.assertGreater(res_current["components"]["originality"], 50.0)
        self.assertGreater(res_current["components"]["repetition_risk"], 50.0)
        self.assertGreaterEqual(res_current["components"]["hook_strength"], 70.0)
        self.assertGreaterEqual(res_current["quality_score"], 70.0)
        self.assertIn(res_current["quality_label"], [quality_score.LABEL_GOOD, quality_score.LABEL_STRONG])

        # F) Confirmar persistência no SQLite
        self.assertIsNotNone(res_current["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM content_quality_scores WHERE task_id = ?;", (current_task_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["quality_score"], res_current["quality_score"])

        # B) Outra task com tópico/hook idêntico CONTINUA penalizada
        other_task_id = "task-v15c-other-duplicate"
        res_other = quality_score.evaluate_quality(
            topic=current_topic,
            hook_text=current_hook,
            task_id=other_task_id,
            preset="cross_platform",
            narrative_structure="explainer",
            estimated_duration=65.0,
            db_path=self.db_path,
            persist=False,
        )
        self.assertEqual(res_other["components"]["originality"], 0.0)
        self.assertEqual(res_other["components"]["repetition_risk"], 40.0)
        self.assertLessEqual(res_other["components"]["hook_strength"], 60.0)
        self.assertLess(res_other["quality_score"], 70.0)
        self.assertIn(res_other["quality_label"], [quality_score.LABEL_REVIEW, quality_score.LABEL_WEAK])

    def test_v15c2_quality_history_profile_and_channel_isolation(self):
        """V15-C.2: Valida isolamento estrito de histórico por perfil e canal no Quality Score."""
        from datetime import datetime, timezone
        import sqlite3
        from app.services import autonomous_production, profile_manager, scheduler

        # H) MIN_QUALITY_SCORE_FOR_AUTONOMOUS continua 70
        self.assertEqual(autonomous_production.MIN_QUALITY_SCORE_FOR_AUTONOMOUS, 70.0)

        # I) COMPONENT_WEIGHTS não mudaram
        expected_weights = {
            "hook_strength": 0.15,
            "originality": 0.15,
            "trend_strength": 0.10,
            "niche_relevance": 0.10,
            "source_confidence": 0.05,
            "repetition_risk": 0.10,
            "narrative_fit": 0.10,
            "duration_fit": 0.10,
            "historical_performance": 0.10,
            "visual_match": 0.05,
        }
        self.assertEqual(quality_score.COMPONENT_WEIGHTS, expected_weights)

        # Inicializa tabelas de profiles e scheduler
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)

        now_iso = datetime.now(timezone.utc).isoformat()

        # Configura Perfis e Canais
        prof_misterio = profile_manager.create_profile(
            name="Historias de Misterio",
            profile_id="historias-de-misterio-v15c2",
            slug="historias-de-misterio-v15c2",
            niche="historias_misterio",
            db_path=self.db_path,
        )
        prof_misterio_id = prof_misterio["id"]

        with sqlite3.connect(self.db_path) as conn:
            # Canais de publicação
            conn.execute(
                "INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at) "
                "VALUES ('channel-misterio-youtube', ?, 'youtube', 'Misterio YT', 1, ?, ?);",
                (prof_misterio_id, now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at) "
                "VALUES ('channel-default-youtube', 'default', 'youtube', 'Default YT', 1, ?, ?);",
                (now_iso, now_iso),
            )

        # Identidades de tarefas
        task_curr = "task-v15c2-curr"
        task_same_hist = "task-v15c2-same-channel"
        task_other_hist = "task-v15c2-other-channel"
        task_same_dup = "task-v15c2-same-duplicate"
        task_other_dup = "task-v15c2-other-duplicate"

        common_topic = "A verdade sobre o misterioso manuscrito Voynich"
        common_hook = "Você sabia que o manuscrito Voynich desafia os maiores criptógrafos?"

        # Vincula perfis às tarefas
        profile_manager.save_task_profile(task_curr, prof_misterio_id, db_path=self.db_path)
        profile_manager.save_task_profile(task_same_hist, prof_misterio_id, db_path=self.db_path)
        profile_manager.save_task_profile(task_same_dup, prof_misterio_id, db_path=self.db_path)
        profile_manager.save_task_profile(task_other_hist, "default", db_path=self.db_path)
        profile_manager.save_task_profile(task_other_dup, "default", db_path=self.db_path)

        # Salva Safety para task_same_hist (mesmo canal com tema diferente)
        safety_gate.save_safety_assessment(
            {
                "task_id": task_same_hist,
                "topic": "Como os computadores quanticos funcionam na pratica",
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "hook_text": "Voce sabia que a computacao quantica pode mudar tudo?",
                "narrative_structure": "explainer",
                "checked_at": "2026-09-24T00:01:00Z",
            },
            db_path=self.db_path,
        )

        # Salva Safety para task_other_hist (outro canal)
        safety_gate.save_safety_assessment(
            {
                "task_id": task_other_hist,
                "topic": "Curiosidades sobre o espaço e planetas",
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "hook_text": "Você sabia que um dia em Vênus dura mais que um ano?",
                "narrative_structure": "curiosity_hook",
                "checked_at": "2026-09-24T00:02:00Z",
            },
            db_path=self.db_path,
        )

        # A) Confirmação de que no cenário antigo não-isolado ambos entrariam no histórico
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            unisolated_rows = conn.execute(
                "SELECT task_id FROM monetization_safety WHERE task_id IS NULL OR task_id <> ? ORDER BY checked_at DESC;",
                (task_curr,),
            ).fetchall()
            unisolated_tids = [r["task_id"] for r in unisolated_rows]
            self.assertIn(task_same_hist, unisolated_tids)
            self.assertIn(task_other_hist, unisolated_tids)

        # B) e C) e G) Isolamento estrito de recent_topics, recent_hooks e recent_items
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            isolated_rows = quality_score._get_isolated_recent_safety_history(
                conn, task_id=task_curr, profile_id=prof_misterio_id, channel_id="channel-misterio-youtube"
            )
            isolated_tids = [r["task_id"] for r in isolated_rows]
            # B) Mesmo canal entra no histórico
            self.assertIn(task_same_hist, isolated_tids)
            # C) Outro canal NÃO entra no histórico
            self.assertNotIn(task_other_hist, isolated_tids)
            # D) Self task continua excluída
            self.assertNotIn(task_curr, isolated_tids)

        # Executa evaluate_quality para task_curr
        res_curr = quality_score.evaluate_quality(
            topic=common_topic,
            hook_text=common_hook,
            task_id=task_curr,
            profile_id=prof_misterio_id,
            channel_id="channel-misterio-youtube",
            db_path=self.db_path,
        )
        # Originalidade não é penalizada por conteúdos de outro canal
        self.assertGreaterEqual(res_curr["components"]["originality"], 80.0)
        self.assertGreaterEqual(res_curr["components"]["repetition_risk"], 80.0)

        # F) Duplicate em outro canal NÃO penaliza
        # Insere avaliação de safety para task_other_dup no canal 'default' com tópico idêntico
        safety_gate.save_safety_assessment(
            {
                "task_id": task_other_dup,
                "topic": common_topic,
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "hook_text": common_hook,
                "narrative_structure": "explainer",
                "checked_at": "2026-09-24T00:03:00Z",
            },
            db_path=self.db_path,
        )

        res_curr_after_other_dup = quality_score.evaluate_quality(
            topic=common_topic,
            hook_text=common_hook,
            task_id=task_curr,
            profile_id=prof_misterio_id,
            channel_id="channel-misterio-youtube",
            db_path=self.db_path,
        )
        # Tópico idêntico no canal default NÃO penaliza o canal misterio!
        self.assertEqual(res_curr_after_other_dup["components"]["originality"], res_curr["components"]["originality"])
        self.assertEqual(res_curr_after_other_dup["components"]["repetition_risk"], res_curr["components"]["repetition_risk"])
        self.assertGreaterEqual(res_curr_after_other_dup["components"]["originality"], 80.0)
        self.assertGreaterEqual(res_curr_after_other_dup["components"]["repetition_risk"], 80.0)

        # E) Duplicate de outra task no MESMO canal CONTINUA penalizada
        safety_gate.save_safety_assessment(
            {
                "task_id": task_same_dup,
                "topic": common_topic,
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "hook_text": common_hook,
                "narrative_structure": "explainer",
                "checked_at": "2026-09-24T00:04:00Z",
            },
            db_path=self.db_path,
        )

        res_curr_after_same_dup = quality_score.evaluate_quality(
            topic=common_topic,
            hook_text=common_hook,
            task_id=task_curr,
            profile_id=prof_misterio_id,
            channel_id="channel-misterio-youtube",
            db_path=self.db_path,
        )
        # Tópico idêntico no MESMO canal penaliza
        self.assertEqual(res_curr_after_same_dup["components"]["originality"], 0.0)
        self.assertEqual(res_curr_after_same_dup["components"]["repetition_risk"], 40.0)


if __name__ == "__main__":
    unittest.main()

