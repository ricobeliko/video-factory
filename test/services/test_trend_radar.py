import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import trend_radar
from app.services.trends.base import (
    BaseTrendProvider,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_REJECTED,
    STATUS_USED,
    TrendSignal,
    VERIFICATION_MULTI,
    VERIFICATION_SINGLE,
)


class TestTrendRadar(unittest.TestCase):

    def setUp(self):
        # Create a temporary SQLite database for test isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_trend_radar.db")
        # Point trend_radar to the isolated db
        self.original_db_path = trend_radar.DB_PATH
        trend_radar.DB_PATH = self.db_path
        trend_radar.init_trend_tables()
        trend_radar.clear_cache()

    def tearDown(self):
        trend_radar.DB_PATH = self.original_db_path
        trend_radar.clear_cache()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_normalization(self):
        # Regras: trim, lowercase, remover acentos, remover pontuações
        raw_1 = "  O Mistério do Triângulo das Bermudas!  "
        norm_1 = trend_radar.normalize_trend_title(raw_1)
        self.assertEqual(norm_1, "misterio do triangulo das bermudas")

        raw_2 = "Segredos do triângulo das bermudas..."
        norm_2 = trend_radar.normalize_trend_title(raw_2)
        self.assertEqual(norm_2, "segredos do triangulo das bermudas")

        # Verifica limpeza de acentos e múltiplos espaços
        raw_3 = "CURIOSIDADES    SOBRE   O   ESPAÇO & ALIENÍGENAS???"
        norm_3 = trend_radar.normalize_trend_title(raw_3)
        self.assertEqual(norm_3, "curiosidades sobre o espaco alienigenas")

    def test_02_deduplication(self):
        # Dois sinais com o mesmo tema essencial devem ser consolidados
        sig1 = TrendSignal(
            source="google_trends",
            title="O mistério do Triângulo das Bermudas",
            normalized_topic="misterio do triangulo das bermudas",
            raw_score=80.0,
            source_confidence=CONFIDENCE_HIGH,
            language="pt-BR",
            region="BR",
        )
        sig2 = TrendSignal(
            source="reddit",
            title="Misterio do Triangulo das Bermudas!",
            normalized_topic="misterio do triangulo das bermudas",
            raw_score=60.0,
            source_confidence=CONFIDENCE_MEDIUM,
            language="pt-BR",
            region="BR",
        )

        merged = trend_radar.deduplicate_and_merge_signals([sig1, sig2])
        self.assertEqual(len(merged), 1)
        item = merged[0]
        self.assertEqual(item.source_count, 2)
        self.assertEqual(item.verification, VERIFICATION_MULTI)
        self.assertEqual(item.source_confidence, CONFIDENCE_HIGH)

    def test_03_deterministic_scoring(self):
        trend_score = trend_radar.calculate_trend_score(
            raw_source_score=75.0,
            source_count=2,
            source_confidence=CONFIDENCE_HIGH,
            is_recent=True,
        )
        novelty_score = trend_radar.calculate_novelty_score(
            topic="mistérios do oceano profundo",
            history_topics=["o que acontece no espaço"],
        )
        relevance_score = trend_radar.calculate_relevance_score(
            topic="mistérios do oceano profundo",
            niche="Curiosidades e Mistérios",
        )
        opp_score = trend_radar.calculate_opportunity_score(
            trend_score=trend_score,
            novelty_score=novelty_score,
            relevance_score=relevance_score,
            source_confidence=CONFIDENCE_HIGH,
            repetition_risk=0,
        )

        # Determinismo e limites de 0 a 100
        self.assertGreaterEqual(trend_score, 0)
        self.assertLessEqual(trend_score, 100)
        self.assertGreaterEqual(novelty_score, 0)
        self.assertLessEqual(novelty_score, 100)
        self.assertGreaterEqual(relevance_score, 0)
        self.assertLessEqual(relevance_score, 100)
        self.assertGreaterEqual(opp_score, 0)
        self.assertLessEqual(opp_score, 100)

        # Execução repetida deve ser idêntica
        opp_score_2 = trend_radar.calculate_opportunity_score(
            trend_score=trend_score,
            novelty_score=novelty_score,
            relevance_score=relevance_score,
            source_confidence=CONFIDENCE_HIGH,
            repetition_risk=0,
        )
        self.assertEqual(opp_score, opp_score_2)

    def test_04_confidence_assignment(self):
        # Multi-source -> HIGH
        conf_multi = trend_radar.determine_source_confidence(
            source="reddit", source_count=2, provider_conf=CONFIDENCE_MEDIUM
        )
        self.assertEqual(conf_multi, CONFIDENCE_HIGH)

        # Google trends oficial -> HIGH
        conf_gt = trend_radar.determine_source_confidence(
            source="google_trends", source_count=1, provider_conf=CONFIDENCE_HIGH
        )
        self.assertEqual(conf_gt, CONFIDENCE_HIGH)

        # Reddit com sinal isolado -> MEDIUM
        conf_reddit = trend_radar.determine_source_confidence(
            source="reddit", source_count=1, provider_conf=CONFIDENCE_MEDIUM
        )
        self.assertEqual(conf_reddit, CONFIDENCE_MEDIUM)

        # Fonte genérica frágil -> LOW
        conf_low = trend_radar.determine_source_confidence(
            source="unknown", source_count=1, provider_conf=CONFIDENCE_LOW
        )
        self.assertEqual(conf_low, CONFIDENCE_LOW)

    def test_05_single_source_verification(self):
        sig = TrendSignal(
            source="rss",
            title="Descoberta arqueológica no Egito",
            normalized_topic="descoberta arqueologica no egito",
            source_count=1,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        merged = trend_radar.deduplicate_and_merge_signals([sig])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_count, 1)
        self.assertEqual(merged[0].verification, VERIFICATION_SINGLE)

    def test_06_multi_source_verification(self):
        sig1 = TrendSignal(
            source="google_trends",
            title="Telescópio James Webb faz nova descoberta",
            normalized_topic="telescopio james webb faz nova descoberta",
            source_count=1,
        )
        sig2 = TrendSignal(
            source="rss",
            title="James Webb descobre galáxia mais antiga",
            normalized_topic="telescopio james webb descobre galaxia mais antiga",
            source_count=1,
        )
        # Fuzzy match deve reconhecer como o mesmo tema
        merged = trend_radar.deduplicate_and_merge_signals([sig1, sig2])
        self.assertEqual(len(merged), 1)
        self.assertGreaterEqual(merged[0].source_count, 2)
        self.assertEqual(merged[0].verification, VERIFICATION_MULTI)

    def test_07_history_reduces_novelty(self):
        topic = "por que o céu é azul durante o dia"
        
        # Sem histórico anterior
        novelty_fresh = trend_radar.calculate_novelty_score(
            topic=topic, history_topics=[]
        )
        self.assertEqual(novelty_fresh, 100)

        # Com histórico contendo tema praticamente idêntico
        history = ["por que o ceu e azul de dia"]
        novelty_stale = trend_radar.calculate_novelty_score(
            topic=topic, history_topics=history
        )
        self.assertLess(novelty_stale, novelty_fresh)
        self.assertLessEqual(novelty_stale, 30)

    def test_08_approved_item_can_send_to_autopilot(self):
        # Insere um item com APPROVED
        sig = TrendSignal(
            source="google_trends",
            title="Mistérios da Fossa das Marianas",
            normalized_topic="misterios da fossa das marianas",
            language="pt-BR",
            region="BR",
            trend_score=85,
            opportunity_score=90,
            status=STATUS_APPROVED,
        )
        item_id = trend_radar.upsert_trend_item(sig)
        self.assertIsNotNone(item_id)

        # Envia para Autopilot
        sent_items = trend_radar.send_trends_to_autopilot([item_id])
        self.assertEqual(len(sent_items), 1)
        self.assertEqual(sent_items[0]["topic"], "Mistérios da Fossa das Marianas")
        self.assertEqual(sent_items[0]["trend_id"], item_id)
        self.assertTrue(sent_items[0]["selected"])

        # O item deve ter seu status atualizado para USED no banco
        stored_items = trend_radar.get_trend_items(status=STATUS_USED)
        self.assertTrue(any(it["id"] == item_id for it in stored_items))

    def test_09_rejected_item_cannot_send_to_autopilot(self):
        sig = TrendSignal(
            source="reddit",
            title="Tópico irrelevante ou spam",
            normalized_topic="topico irrelevante ou spam",
            status=STATUS_REJECTED,
        )
        item_id = trend_radar.upsert_trend_item(sig)

        sent_items = trend_radar.send_trends_to_autopilot([item_id])
        self.assertEqual(len(sent_items), 0)

        # Também não envia se status for NEW
        trend_radar.update_trend_item_status(item_id, STATUS_NEW)
        sent_items_new = trend_radar.send_trends_to_autopilot([item_id])
        self.assertEqual(len(sent_items_new), 0)

    def test_10_provider_failure_resilience(self):
        class FailingProvider(BaseTrendProvider):
            def __init__(self):
                super().__init__()
                self.name = "failing_provider"

            def fetch_trends(self, niche="", language="pt-BR", region="BR", limit=10):
                raise RuntimeError("API timeout or connection refused")

        class HealthyProvider(BaseTrendProvider):
            def __init__(self):
                super().__init__()
                self.name = "healthy_provider"

            def fetch_trends(self, niche="", language="pt-BR", region="BR", limit=10):
                return [
                    TrendSignal(
                        source="healthy_provider",
                        title="Descoberta científica válida",
                        normalized_topic="descoberta cientifica valida",
                        raw_score=70.0,
                    )
                ]

        with patch.object(
            trend_radar,
            "get_active_providers",
            return_value=[FailingProvider(), HealthyProvider()],
        ):
            # Não deve lançar exceção mesmo com FailingProvider quebrando
            items = trend_radar.refresh_trend_radar(
                niche="Ciência", force_refresh=True
            )
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Descoberta científica válida")

    def test_11_cache_respected(self):
        mock_provider = MagicMock(spec=BaseTrendProvider)
        mock_provider.name = "mock_provider"
        mock_provider.fetch_trends.return_value = [
            TrendSignal(
                source="mock_provider",
                title="Tendência de Teste",
                normalized_topic="tendencia de teste",
            )
        ]

        with patch.object(
            trend_radar, "get_active_providers", return_value=[mock_provider]
        ):
            # 1ª chamada: consulta provider
            res1 = trend_radar.refresh_trend_radar(
                niche="TestCache", force_refresh=False
            )
            self.assertEqual(mock_provider.fetch_trends.call_count, 1)
            self.assertEqual(len(res1), 1)

            # 2ª chamada imediata: deve usar cache e NÃO chamar fetch_trends de novo
            res2 = trend_radar.refresh_trend_radar(
                niche="TestCache", force_refresh=False
            )
            self.assertEqual(mock_provider.fetch_trends.call_count, 1)
            self.assertEqual(len(res2), 1)

            # 3ª chamada com force_refresh=True: deve chamar novamente
            trend_radar.refresh_trend_radar(
                niche="TestCache", force_refresh=True
            )
            self.assertEqual(mock_provider.fetch_trends.call_count, 2)

    def test_12_persistence_and_restart(self):
        sig = TrendSignal(
            source="google_trends",
            title="Curiosidades sobre Buracos Negros",
            normalized_topic="curiosidades sobre buracos negros",
            language="pt-BR",
            region="BR",
            trend_score=95,
            opportunity_score=88,
            source_confidence=CONFIDENCE_HIGH,
            source_count=2,
            verification=VERIFICATION_MULTI,
            status=STATUS_APPROVED,
        )
        item_id = trend_radar.upsert_trend_item(sig)

        # Simula restart: limpa cache em memória e reabre conexão SQLite
        trend_radar.clear_cache()
        reloaded_items = trend_radar.get_trend_items(status=STATUS_APPROVED)
        matched = [it for it in reloaded_items if it["id"] == item_id]

        self.assertEqual(len(matched), 1)
        retrieved = matched[0]
        self.assertEqual(retrieved["title"], "Curiosidades sobre Buracos Negros")
        self.assertEqual(retrieved["trend_score"], 95)
        self.assertEqual(retrieved["opportunity_score"], 88)
        self.assertEqual(retrieved["verification"], VERIFICATION_MULTI)
        self.assertEqual(retrieved["source_confidence"], CONFIDENCE_HIGH)

    def test_13_political_item_in_curiosities_penalized(self):
        # Item com termos políticos em nicho Curiosidades deve ser fortemente penalizado
        political_title = "Cármen Lúcia: 7 curiosidades sobre a ministra do STF"
        rel_political = trend_radar.calculate_relevance_score(
            topic=political_title,
            niche="Curiosidades",
            description="Ministra do tribunal fala sobre eleições e governo",
        )
        self.assertLessEqual(rel_political, 25.0)

        # Se o usuário explicitamente pedir política, a relevância não é penalizada
        rel_in_politics = trend_radar.calculate_relevance_score(
            topic=political_title,
            niche="Política e Notícias",
        )
        self.assertGreater(rel_in_politics, 60.0)

    def test_14_genuine_curiosity_item_high_relevance(self):
        # Item genuinamente alinhado a fatos/mistérios/ciência recebe relevância alta
        genuine_title = "Mistérios e descobertas incríveis sobre o oceano profundo"
        rel_genuine = trend_radar.calculate_relevance_score(
            topic=genuine_title,
            niche="Curiosidades",
        )
        self.assertGreaterEqual(rel_genuine, 75.0)

        political_title = "Presidenciável em campanha eleitoral para o governo"
        rel_political = trend_radar.calculate_relevance_score(
            topic=political_title,
            niche="Curiosidades",
        )
        # Relevância genuína deve ser claramente superior à do item político
        self.assertGreater(rel_genuine, rel_political + 40.0)

    def test_15_rss_single_source_not_high(self):
        # Single source RSS nunca deve receber HIGH automaticamente
        conf_rss = trend_radar.determine_source_confidence(
            source="rss", source_count=1, provider_conf=CONFIDENCE_HIGH
        )
        self.assertEqual(conf_rss, CONFIDENCE_MEDIUM)

        # Multi-source deve continuar HIGH
        conf_multi = trend_radar.determine_source_confidence(
            source="rss", source_count=2, provider_conf=CONFIDENCE_MEDIUM
        )
        self.assertEqual(conf_multi, CONFIDENCE_HIGH)

    def test_16_opportunity_score_drops_with_relevance(self):
        # Opportunity score deve refletir a queda de relevância
        high_rel = 85.0
        low_rel = 15.0

        opp_high = trend_radar.calculate_opportunity_score(
            trend_score=70.0,
            novelty_score=90.0,
            relevance_score=high_rel,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        opp_low = trend_radar.calculate_opportunity_score(
            trend_score=70.0,
            novelty_score=90.0,
            relevance_score=low_rel,
            source_confidence=CONFIDENCE_MEDIUM,
        )

        self.assertGreater(opp_high, opp_low)
        # Diferença esperada: 0.20 * (85 - 15) = 14 pontos
        self.assertGreaterEqual(opp_high - opp_low, 13.0)

    def test_17_high_trend_low_rel_loses_to_moderate_trend_high_rel(self):
        # 1. Trend muito alto + relevance baixa perde para trend moderado + relevance alta
        # Ex: "maisa" (trend 90, rel 42, conf HIGH) vs "oceanos salgados" (trend 55, rel 90, conf MEDIUM)
        opp_generic = trend_radar.calculate_opportunity_score(
            trend_score=90.0,
            novelty_score=95.0,
            relevance_score=42.0,
            source_confidence=CONFIDENCE_HIGH,
        )
        opp_niche = trend_radar.calculate_opportunity_score(
            trend_score=55.0,
            novelty_score=95.0,
            relevance_score=90.0,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        self.assertGreater(opp_niche, opp_generic)

    def test_18_confidence_high_cannot_neutralize_low_relevance(self):
        # 2. Confidence HIGH não neutraliza baixa relevance
        opp_high_conf_low_rel = trend_radar.calculate_opportunity_score(
            trend_score=75.0,
            novelty_score=95.0,
            relevance_score=45.0,
            source_confidence=CONFIDENCE_HIGH,
        )
        opp_med_conf_high_rel = trend_radar.calculate_opportunity_score(
            trend_score=60.0,
            novelty_score=95.0,
            relevance_score=80.0,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        self.assertGreater(opp_med_conf_high_rel, opp_high_conf_low_rel)

    def test_19_relevance_above_60_remains_fully_eligible(self):
        # 3. Relevance >= 60 permanece elegível integralmente (sem corte de gate)
        opp_eligible = trend_radar.calculate_opportunity_score(
            trend_score=70.0,
            novelty_score=90.0,
            relevance_score=75.0,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        # Base matemática direta sem penalidade:
        # 0.35*70 + 0.35*90 + 0.20*75 + 0.10*75 = 24.5 + 31.5 + 15.0 + 7.5 = 78.5
        self.assertEqual(opp_eligible, 78.5)

    def test_20_item_below_threshold_remains_persisted(self):
        # 4. Item abaixo do threshold continua persistido no SQLite normalmente
        sig_low = TrendSignal(
            source="rss",
            title="Matéria Política Eleitoral com Ministra do STF",
            normalized_topic="materia politica eleitoral com ministra do stf",
            description="Tribunal julga processo de campanha e votos",
            raw_score=70.0,
        )
        # Processa e persiste com nicho Curiosidades
        items = trend_radar.deduplicate_and_rank_signals([sig_low], niche="Curiosidades")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertLess(item["relevance_score"], 40.0)

        # Salva no SQLite com nicho
        trend_id = trend_radar.upsert_trend_item(sig_low, niche="Curiosidades")
        stored = trend_radar.get_trend_items(niche="Curiosidades")
        self.assertTrue(any(it["trend_id"] == trend_id or it["title"] == sig_low.title for it in stored))

    def test_21_ranking_respects_niche_adherence(self):
        # 5. Ranking respeita aderência ao nicho: temas qualificados (rel >= 60) no topo
        sig_generic = TrendSignal(
            source="google_trends",
            title="maisa",
            normalized_topic="maisa",
            raw_score=95.0,
            source_confidence=CONFIDENCE_HIGH,
        )
        sig_curiosity = TrendSignal(
            source="rss",
            title="Mistérios fascinantes sobre a formação dos oceanos",
            normalized_topic="misterios fascinantes sobre a formacao dos oceanos",
            raw_score=60.0,
            source_confidence=CONFIDENCE_MEDIUM,
        )
        ranked = trend_radar.deduplicate_and_rank_signals(
            [sig_generic, sig_curiosity], niche="Curiosidades"
        )
        self.assertEqual(len(ranked), 2)
        # O tema de curiosidade deve ser #1
        self.assertEqual(ranked[0]["title"], sig_curiosity.title)
        self.assertGreater(ranked[0]["opportunity_score"], ranked[1]["opportunity_score"])


if __name__ == "__main__":
    unittest.main()
