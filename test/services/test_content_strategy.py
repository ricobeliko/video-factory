import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import content_strategy, quality_score, safety_gate


class TestContentStrategy(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_strategy.db")
        content_strategy.init_strategy_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. strategy_score determinístico
    def test_strategy_score_deterministic(self):
        score1, label1, comps1 = content_strategy.calculate_strategy_score(
            quality_score=80.0,
            trend_opportunity_score=75.0,
            historical_performance_score=70.0,
            diversity_score=85.0,
            relevance_score=80.0,
            source_confidence_score=70.0,
        )
        score2, label2, comps2 = content_strategy.calculate_strategy_score(
            quality_score=80.0,
            trend_opportunity_score=75.0,
            historical_performance_score=70.0,
            diversity_score=85.0,
            relevance_score=80.0,
            source_confidence_score=70.0,
        )
        self.assertEqual(score1, score2)
        self.assertEqual(label1, label2)
        self.assertEqual(comps1, comps2)

    # 2. ausência de componente redistribui peso
    def test_missing_component_redistributes_weight(self):
        # Somente quality (0.30) e diversity (0.15) fornecidos.
        # available_weight = 0.45
        # weighted_sum = 80*0.30 + 50*0.15 = 24.0 + 7.5 = 31.5
        # final = 31.5 / 0.45 = 70.0
        score, label, comps = content_strategy.calculate_strategy_score(
            quality_score=80.0,
            trend_opportunity_score=None,
            historical_performance_score=None,
            diversity_score=50.0,
            relevance_score=None,
            source_confidence_score=None,
        )
        self.assertAlmostEqual(score, 70.0, places=1)
        self.assertEqual(label, content_strategy.LABEL_PROMISING)

    # 3. quality alto aumenta strategy
    def test_high_quality_increases_strategy(self):
        low_q, _, _ = content_strategy.calculate_strategy_score(
            quality_score=40.0,
            trend_opportunity_score=60.0,
            historical_performance_score=60.0,
            diversity_score=60.0,
            relevance_score=60.0,
            source_confidence_score=60.0,
        )
        high_q, _, _ = content_strategy.calculate_strategy_score(
            quality_score=95.0,
            trend_opportunity_score=60.0,
            historical_performance_score=60.0,
            diversity_score=60.0,
            relevance_score=60.0,
            source_confidence_score=60.0,
        )
        self.assertGreater(high_q, low_q)

    # 4. trend alto aumenta strategy
    def test_high_trend_increases_strategy(self):
        low_t, _, _ = content_strategy.calculate_strategy_score(
            quality_score=70.0,
            trend_opportunity_score=20.0,
            historical_performance_score=60.0,
            diversity_score=60.0,
            relevance_score=60.0,
            source_confidence_score=60.0,
        )
        high_t, _, _ = content_strategy.calculate_strategy_score(
            quality_score=70.0,
            trend_opportunity_score=95.0,
            historical_performance_score=60.0,
            diversity_score=60.0,
            relevance_score=60.0,
            source_confidence_score=60.0,
        )
        self.assertGreater(high_t, low_t)

    # 5. histórico insuficiente não cria winner
    def test_insufficient_history_never_creates_proven_winner(self):
        bucket, reason = content_strategy.classify_strategy_bucket(
            topic="Mistérios dos Oceanos",
            strategy_score=88.0,
            quality_score=85.0,
            trend_opportunity_score=60.0,
            historical_performance_score=90.0,
            diversity_score=80.0,
            relevance_score=70.0,
            has_sufficient_history=False,  # < 5 vídeos reais
        )
        self.assertNotEqual(bucket, content_strategy.BUCKET_PROVEN_WINNER)

    # 6. histórico suficiente permite proven winner
    def test_sufficient_history_allows_proven_winner(self):
        bucket, reason = content_strategy.classify_strategy_bucket(
            topic="Mistérios dos Oceanos",
            strategy_score=88.0,
            quality_score=85.0,
            trend_opportunity_score=60.0,
            historical_performance_score=85.0,
            diversity_score=75.0,
            relevance_score=70.0,
            has_sufficient_history=True,  # >= 5 vídeos reais
        )
        self.assertEqual(bucket, content_strategy.BUCKET_PROVEN_WINNER)

    # 7. diversity score cai com cluster repetido
    def test_diversity_score_drops_on_repeated_cluster(self):
        recent_history = [
            {"topic": "O Segredo dos Oceanos Profundos", "topic_cluster": "oceanos"},
            {"topic": "Peixes Abissais e Mares Frios", "topic_cluster": "oceanos"},
        ]
        score, reasons = content_strategy.calculate_diversity_score(
            topic="Águas Salgadas e Tubarões",
            topic_cluster="oceanos",
            recent_history=recent_history,
        )
        self.assertLess(score, 75.0)
        self.assertTrue(any("Cluster 'oceanos' utilizado" in r or "Cluster 'oceanos' saturado" in r for r in reasons))

    # 8. cluster novo recebe diversity maior
    def test_new_cluster_receives_higher_diversity(self):
        recent_history = [
            {"topic": "O Segredo dos Oceanos Profundos", "topic_cluster": "oceanos"},
            {"topic": "Peixes Abissais e Mares Frios", "topic_cluster": "oceanos"},
        ]
        score_new, reasons_new = content_strategy.calculate_diversity_score(
            topic="Buracos Negros e o Espaço Interestelar",
            topic_cluster="astronomia",
            recent_history=recent_history,
        )
        score_repeated, _ = content_strategy.calculate_diversity_score(
            topic="Tubarões nos Mares Salgados",
            topic_cluster="oceanos",
            recent_history=recent_history,
        )
        self.assertGreater(score_new, score_repeated)
        self.assertGreaterEqual(score_new, 90.0)

    # 9. recommendation respeita narrative fit
    def test_recommendation_respects_narrative_fit(self):
        struct_listicle, _ = content_strategy.recommend_narrative_structure(
            topic="7 curiosidades surpreendentes sobre o cérebro",
            niche="Curiosidades",
        )
        self.assertEqual(struct_listicle, "fact_context")

        struct_myth, _ = content_strategy.recommend_narrative_structure(
            topic="Mito ou verdade: açúcar dá energia imediata?",
            niche="Saúde",
        )
        self.assertEqual(struct_myth, "myth_vs_reality")

    # 10. estrutura consecutiva igual é evitada
    def test_consecutive_identical_structure_avoided(self):
        # Para um tópico de curiosidades que normalmente escolheria fact_context:
        struct, reasons = content_strategy.recommend_narrative_structure(
            topic="5 fatos chocantes sobre o oceano",
            last_used_structure="fact_context",
        )
        self.assertNotEqual(struct, "fact_context")
        self.assertTrue(any("evitar repetição consecutiva" in r for r in reasons))

    # 11. build_strategy_batch respeita mix
    def test_build_strategy_batch_respects_mix(self):
        # 15 ideias simuladas em múltiplos buckets
        ideas = [
            {"topic": f"Winner {i}", "strategy_score": 90 - i, "strategy_bucket": content_strategy.BUCKET_PROVEN_WINNER, "topic_cluster": f"c_{i}"}
            for i in range(5)
        ] + [
            {"topic": f"Trend {i}", "strategy_score": 85 - i, "strategy_bucket": content_strategy.BUCKET_TREND_OPPORTUNITY, "topic_cluster": f"t_{i}"}
            for i in range(4)
        ] + [
            {"topic": f"Evergreen {i}", "strategy_score": 80 - i, "strategy_bucket": content_strategy.BUCKET_EVERGREEN, "topic_cluster": f"e_{i}"}
            for i in range(3)
        ] + [
            {"topic": f"Experiment {i}", "strategy_score": 70 - i, "strategy_bucket": content_strategy.BUCKET_EXPERIMENT, "topic_cluster": f"ex_{i}"}
            for i in range(3)
        ]
        batch = content_strategy.build_strategy_batch(ideas, target_count=10, has_sufficient_history=True)
        self.assertEqual(len(batch), 10)
        buckets_in_batch = {it["strategy_bucket"] for it in batch}
        self.assertIn(content_strategy.BUCKET_PROVEN_WINNER, buckets_in_batch)
        self.assertIn(content_strategy.BUCKET_TREND_OPPORTUNITY, buckets_in_batch)
        self.assertIn(content_strategy.BUCKET_EVERGREEN, buckets_in_batch)

    # 12. build_strategy_batch evita clusters duplicados consecutivos
    def test_build_strategy_batch_avoids_duplicate_consecutive_clusters(self):
        ideas = [
            {"topic": "Oceano 1", "strategy_score": 95, "topic_cluster": "oceanos", "recommended_structure": "explainer", "strategy_bucket": content_strategy.BUCKET_TREND_OPPORTUNITY},
            {"topic": "Oceano 2", "strategy_score": 92, "topic_cluster": "oceanos", "recommended_structure": "short_story", "strategy_bucket": content_strategy.BUCKET_TREND_OPPORTUNITY},
            {"topic": "Espaço 1", "strategy_score": 88, "topic_cluster": "astronomia", "recommended_structure": "investigative_mystery", "strategy_bucket": content_strategy.BUCKET_EVERGREEN},
            {"topic": "Espaço 2", "strategy_score": 86, "topic_cluster": "astronomia", "recommended_structure": "explainer", "strategy_bucket": content_strategy.BUCKET_EVERGREEN},
        ]
        batch = content_strategy.build_strategy_batch(ideas, target_count=4)
        self.assertEqual(len(batch), 4)
        for i in range(len(batch) - 1):
            # Clusters consecutivos não devem ser iguais quando há alternativa disponível
            self.assertNotEqual(batch[i]["topic_cluster"], batch[i+1]["topic_cluster"])

    # 13. idea sem trend continua válida
    def test_idea_without_trend_remains_valid(self):
        res = content_strategy.evaluate_strategy(
            topic="Por que o céu é azul?",
            niche="Curiosidades",
            trend_data=None,
            db_path=self.db_path,
        )
        self.assertIsNotNone(res["strategy_score"])
        self.assertIn(res["strategy_label"], [content_strategy.LABEL_PRIORITY, content_strategy.LABEL_PROMISING, content_strategy.LABEL_EXPERIMENT, content_strategy.LABEL_LOW])
        self.assertIsNotNone(res["strategy_bucket"])
        self.assertGreater(res["strategy_score"], 0)

    # 14. idea sem analytics continua válida
    def test_idea_without_analytics_remains_valid(self):
        # DB vazio, sem analytics
        res = content_strategy.evaluate_strategy(
            topic="Segredos da Roma Antiga",
            niche="História",
            db_path=self.db_path,
        )
        self.assertIsNotNone(res["strategy_score"])
        self.assertIsNone(res["historical_performance_score"])
        self.assertIn(res["strategy_bucket"], [content_strategy.BUCKET_EVERGREEN, content_strategy.BUCKET_EXPERIMENT, content_strategy.BUCKET_TREND_OPPORTUNITY, content_strategy.BUCKET_DIVERSITY])

    # 15. labels corretos
    def test_labels_thresholds(self):
        self.assertEqual(content_strategy.determine_strategy_label(85.0), content_strategy.LABEL_PRIORITY)
        self.assertEqual(content_strategy.determine_strategy_label(84.9), content_strategy.LABEL_PROMISING)
        self.assertEqual(content_strategy.determine_strategy_label(70.0), content_strategy.LABEL_PROMISING)
        self.assertEqual(content_strategy.determine_strategy_label(69.9), content_strategy.LABEL_EXPERIMENT)
        self.assertEqual(content_strategy.determine_strategy_label(55.0), content_strategy.LABEL_EXPERIMENT)
        self.assertEqual(content_strategy.determine_strategy_label(54.9), content_strategy.LABEL_LOW)
        self.assertEqual(content_strategy.determine_strategy_label(0.0), content_strategy.LABEL_LOW)

    # 16. persistência
    def test_persistence_and_retrieval(self):
        res = content_strategy.evaluate_strategy(
            topic="O que há no fundo da Fossa das Marianas?",
            niche="Curiosidades",
            task_id="test-task-123",
            persist=True,
            db_path=self.db_path,
        )
        self.assertIsNotNone(res["id"])
        recent = content_strategy.get_recent_strategy_scores(limit=10, db_path=self.db_path)
        self.assertEqual(len(recent), 1)
        item = recent[0]
        self.assertEqual(item["topic"], "O que há no fundo da Fossa das Marianas?")
        self.assertEqual(item["task_id"], "test-task-123")
        self.assertEqual(item["topic_cluster"], "oceanos")
        self.assertEqual(item["strategy_score"], res["strategy_score"])
        self.assertEqual(item["strategy_bucket"], res["strategy_bucket"])
        self.assertTrue(len(item["reasons"]) > 0)

    # 17. reasons explicáveis e limitados
    def test_reasons_format_and_limit(self):
        res = content_strategy.evaluate_strategy(
            topic="Descubra por que aviões não voam em linha reta",
            niche="Curiosidades",
            db_path=self.db_path,
        )
        reasons = res["reasons"]
        self.assertIsInstance(reasons, list)
        self.assertLessEqual(len(reasons), 5)
        self.assertGreater(len(reasons), 0)
        # Cada razão deve ser uma string não vazia
        for r in reasons:
            self.assertIsInstance(r, str)
            self.assertTrue(len(r.strip()) > 0)

    # 18. Quality/Safety não são alterados
    def test_quality_and_safety_remain_unaltered(self):
        # Testa chamada pura do Quality Score
        q_res = quality_score.evaluate_quality(
            topic="Fatos sobre o Espaço",
            niche="Curiosidades",
            db_path=self.db_path,
        )
        self.assertIn("quality_score", q_res)
        self.assertIn("quality_label", q_res)
        self.assertNotIn("strategy_score", q_res)  # Strategy não polui quality

        # Testa chamada pura do Safety Gate
        s_res = safety_gate.evaluate_script_safety(
            task_id="safety-test-id",
            topic="Fatos sobre o Espaço",
            script="O universo observável contém mais de duas trilhões de galáxias catalogadas. Cada uma abriga bilhões de estrelas e planetas com dinâmicas fascinantes e mistérios sem fim a serem compreendidos pelos cientistas.",
            narrative_structure="explainer",
            db_path=self.db_path,
        )
        self.assertIn("safety_status", s_res)
        self.assertNotIn("strategy_score", s_res)  # Safety continua intocado

    # -----------------------------------------------------------------------
    # Novos Testes de Consistência e Contratos Oficiais
    # -----------------------------------------------------------------------

    # 19. recommended_structure sempre pertence às 5 estruturas oficiais
    def test_recommended_structure_always_belongs_to_official_5(self):
        from app.models import const
        official = set(const.NARRATIVE_STRUCTURES)
        test_topics = [
            "Mito ou verdade sobre o café",
            "O mistério do Triângulo das Bermudas",
            "Como funciona a gravidade quântica",
            "A incrível história de Nikola Tesla",
            "10 fatos curiosos sobre o Antigo Egito",
            "O que acontece se você não dormir por 3 dias?",
            "Tema aleatório sem padrões conhecidos",
        ]
        for top in test_topics:
            struct, _ = content_strategy.recommend_narrative_structure(top)
            self.assertIn(struct, official, f"Estrutura '{struct}' para '{top}' não pertence às 5 oficiais!")

    # 20. mito retorna myth_vs_reality
    def test_myth_topic_returns_myth_vs_reality(self):
        struct, _ = content_strategy.recommend_narrative_structure(
            topic="Mito ou verdade: açúcar causa hiperatividade em crianças?"
        )
        self.assertEqual(struct, "myth_vs_reality")

    # 21. explicação científica retorna explainer
    def test_scientific_explanation_returns_explainer(self):
        struct, _ = content_strategy.recommend_narrative_structure(
            topic="Como funciona a fusão nuclear e a ciência por trás das estrelas"
        )
        self.assertEqual(struct, "explainer")

    # 22. mistério retorna investigative_mystery
    def test_mystery_returns_investigative_mystery(self):
        struct, _ = content_strategy.recommend_narrative_structure(
            topic="O mistério não resolvido do manuscrito Voynich e seus enigmas"
        )
        self.assertEqual(struct, "investigative_mystery")

    # 23. Quality 82 preserva label GOOD
    def test_quality_82_preserves_label_good(self):
        self.assertEqual(quality_score.determine_quality_label(82.0), quality_score.LABEL_GOOD)
        self.assertNotEqual(quality_score.determine_quality_label(82.0), quality_score.LABEL_STRONG)

    # 24. V7 não recalcula quality_label
    def test_v7_does_not_recalculate_quality_label(self):
        # V7 deve consumir quality_label diretamente da V6 sem modificá-lo
        mock_quality = {
            "quality_score": 82.0,
            "quality_label": "GOOD",
            "components": {},
        }
        res = content_strategy.evaluate_strategy(
            topic="Mistérios dos Oceanos",
            quality_data=mock_quality,
            db_path=self.db_path,
        )
        self.assertEqual(res["quality_score"], 82.0)
        self.assertEqual(res["quality_label"], "GOOD")

    # 25. youtube_shorts_original usa faixa oficial quando não há Analytics suficiente
    def test_youtube_shorts_original_official_fallback_without_analytics(self):
        dur_min, dur_max, dur_str = content_strategy.recommend_duration(
            preset="youtube_shorts_original",
            has_sufficient_history=False,
        )
        self.assertEqual(dur_min, 45.0)
        self.assertEqual(dur_max, 90.0)
        self.assertEqual(dur_str, "45–90s")

    # 26. cross_platform usa 62–75s sem histórico suficiente
    def test_cross_platform_and_tiktok_use_62_75s_without_analytics(self):
        d_min_cp, d_max_cp, d_str_cp = content_strategy.recommend_duration(
            preset="cross_platform",
            has_sufficient_history=False,
        )
        self.assertEqual(d_min_cp, 62.0)
        self.assertEqual(d_max_cp, 75.0)
        self.assertEqual(d_str_cp, "62–75s")

        d_min_tt, d_max_tt, d_str_tt = content_strategy.recommend_duration(
            preset="tiktok_rewards",
            has_sufficient_history=False,
        )
        self.assertEqual(d_min_tt, 62.0)
        self.assertEqual(d_max_tt, 75.0)
        self.assertEqual(d_str_tt, "62–75s")

    # 27. nenhum identifier legado/inventado aparece
    def test_no_legacy_or_invented_identifiers(self):
        from app.models import const
        forbidden_structures = {
            "listicle_countdown",
            "myth_buster",
            "curiosity_gap",
            "storytelling_hook",
            "problem_agitation_solution",
        }
        for topic in [
            "10 curiosidades sobre gatos",
            "Mito ou verdade sobre o leite",
            "Descubra o segredo do sucesso",
            "A história de Alexandre o Grande",
        ]:
            struct, _ = content_strategy.recommend_narrative_structure(topic)
            self.assertNotIn(struct, forbidden_structures)
            self.assertIn(struct, const.NARRATIVE_STRUCTURES)

        # presets legados / durações inventadas
        _, _, dur_yt = content_strategy.recommend_duration("youtube_shorts_original", has_sufficient_history=False)
        self.assertNotEqual(dur_yt, "50–60s")
        self.assertEqual(dur_yt, "45–90s")

    # 28. restauração de avaliações usa a mais recente quando há duplicatas históricas
    def test_stale_quality_restoration_uses_most_recent(self):
        trend_id = "test_trend_stale_123"
        topic = "Tema Teste Stale Score"

        quality_score.init_quality_db(self.db_path)

        # 1. Inserir avaliação antiga: 69.0 REVIEW
        with quality_score.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    trend_id, topic, quality_score, quality_label,
                    relevance_score, source_confidence_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (trend_id, topic, 69.0, "REVIEW", 50.0, 100.0, "2026-09-17T05:00:00Z"),
            )
            # 2. Inserir avaliação nova: 39.7 WEAK
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    trend_id, topic, quality_score, quality_label,
                    relevance_score, source_confidence_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (trend_id, topic, 39.7, "WEAK", 20.0, 70.0, "2026-09-17T06:00:00Z"),
            )

        # Confirmar que restore (get_recent_quality_scores) retorna a mais recente (39.7)
        recent_evals = quality_score.get_recent_quality_scores(limit=10, db_path=self.db_path)
        matching = [e for e in recent_evals if e.get("trend_id") == trend_id]
        self.assertEqual(len(matching), 1)
        restored_idea = matching[0]
        self.assertAlmostEqual(restored_idea["quality_score"], 39.7, places=1)
        self.assertEqual(restored_idea["quality_label"], "WEAK")

        # Confirmar que Strategy consome 39.7
        strat_eval = content_strategy.evaluate_strategy(
            topic=topic,
            quality_data=restored_idea,
            trend_data={"trend_id": trend_id, "relevance_score": 20.0, "source_confidence": 70.0},
            db_path=self.db_path,
        )
        self.assertAlmostEqual(strat_eval["quality_score"], 39.7, places=1)
        self.assertEqual(strat_eval["quality_label"], "WEAK")
        self.assertAlmostEqual(strat_eval["components"]["quality_signal"], 39.7, places=1)
        self.assertLess(strat_eval["strategy_score"], 55.0)
        self.assertEqual(strat_eval["strategy_label"], content_strategy.LABEL_LOW)


if __name__ == "__main__":
    unittest.main()

