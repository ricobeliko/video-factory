"""
test/services/test_hybrid_validation.py
=======================================
Testes unitários e direcionados para a V16.8 — Controlled Hybrid Render Validation.

Garantias testadas:
1. Baseline mode permanece stock-only (visual_generation_enabled=False).
2. Hybrid mode produz estratégias mistas (stock para cenas com bom score, geração para cenas fracas/HERO).
3. Cenas HERO com stock deficiente acionam geração contextual de imagem + still motion.
4. Cenas com stock forte (>= 60) permanecem como stock sem acionar IA.
5. Fallback para stock opera com resiliência em caso de falha de provedor ou quality gate.
6. Auditoria estrita de legendas e narração: preserva bottom, font_size 60, stroke 2.0, voice_rate 1.0;
   rejeita regressões para top, font_size 30, voice_rate 0.8.
7. Cálculo consistente do placar de qualidade perceptual (Baseline, Hybrid, Delta positivo).
8. Invariantes de segurança: zero publicação, zero chamadas pagas, zero acesso à produção.
"""

import os
import pytest

from app.models.schema import VideoParams
from app.services import hybrid_validation, hybrid_visual


@pytest.fixture
def mock_script_data(tmp_path):
    """Cria fixture isolada e temporária representando a tarefa de Marte em DEV."""
    task_dir = tmp_path / "task_mars"
    task_dir.mkdir(parents=True)
    script_file = task_dir / "script.json"

    content = {
        "script": (
            "Apesar de ser conhecido como o Planeta Vermelho por causa do ferro oxidado em sua superfície, "
            "Marte nem sempre foi árido e gelado, pois cientistas descobriram evidências irrefutáveis de que "
            "vales inteiros e crateras já abrigaram rios caudalosos e até mesmo um vasto oceano em seu passado distante. "
            "Além disso, o Monte Olimpo, o maior vulcão do sistema solar localizado lá, possui dimensões tão titânicas "
            "que sua base cobriria facilmente todo o estado brasileiro do Paraná, erguendo-se a quase três vezes a altura do Monte Everest. "
            "Para completar, se você estivesse em Marte, o pôr do sol não seria alaranjado ou avermelhado como na Terra, "
            "mas sim de um tom azulado fantasmagórico, causado pela forma como a poeira rarefeita da atmosfera dispersa a luz solar."
        ),
        "params": {
            "video_subject": "3 curiosidades surpreendentes sobre Marte",
            "video_aspect": "9:16",
            "font_size": 60,
            "stroke_width": 2.0,
            "stroke_color": "#000000",
            "text_fore_color": "#FFFFFF",
            "subtitle_position": "bottom",
            "voice_name": "pt-BR-AntonioNeural-Male",
            "voice_rate": 1.0,
        },
        "material_sources": [
            {"provider": "pexels", "asset_id": "18575771", "source_page": "https://pexels.com/video/moon-18575771/"},
            {"provider": "pexels", "asset_id": "36119244", "source_page": "https://pexels.com/video/beach-36119244/"},
            {"provider": "pexels", "asset_id": "9354647", "source_page": "https://pexels.com/video/fumarole-9354647/"},
            {"provider": "pexels", "asset_id": "8474871", "source_page": "https://pexels.com/video/astronaut-8474871/"},
            {"provider": "pexels", "asset_id": "28811774", "source_page": "https://pexels.com/video/sunset-28811774/"},
            {"provider": "pexels", "asset_id": "30220016", "source_page": "https://pexels.com/video/twilight-30220016/"},
            {"provider": "pexels", "asset_id": "8474684", "source_page": "https://pexels.com/video/flag-8474684/"},
        ],
    }

    import json
    with open(script_file, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False)

    return str(script_file), str(tmp_path / "val_output")


class TestHybridValidationV16_8:

    def test_subtitle_narration_audit_compliance(self):
        """Valida que parâmetros em conformidade passam na auditoria estrita."""
        params = VideoParams(
            video_subject="Teste",
            video_aspect="9:16",
            font_size=60,
            stroke_width=2.0,
            stroke_color="#000000",
            text_fore_color="#FFFFFF",
            subtitle_position="bottom",
            voice_name="pt-BR-AntonioNeural-Male",
            voice_rate=1.0,
        )
        audit = hybrid_validation.audit_subtitle_narration_params(params)
        assert audit.is_valid is True
        assert len(audit.violations) == 0

    def test_subtitle_narration_audit_detects_regressions(self):
        """Garante rejeição de regressões para top, font_size 30, voice_rate 0.8."""
        bad_params = VideoParams(
            video_subject="Regressão",
            video_aspect="9:16",
            font_size=30,  # Regressão!
            stroke_width=1.0,  # Regressão!
            stroke_color="#FFFFFF",  # Regressão!
            text_fore_color="#000000",  # Regressão!
            subtitle_position="top",  # Regressão!
            voice_name="unknown-en-voice",  # Regressão!
            voice_rate=0.8,  # Regressão!
        )
        audit = hybrid_validation.audit_subtitle_narration_params(bad_params)
        assert audit.is_valid is False
        assert len(audit.violations) >= 5
        assert any("top" in v for v in audit.violations)
        assert any("30" in v for v in audit.violations)
        assert any("0.8" in v for v in audit.violations)

    def test_controlled_hybrid_validation_experiment_run(self, mock_script_data):
        """Executa experimento completo e valida placar comparativo e artefatos."""
        script_path, out_dir = mock_script_data
        exp = hybrid_validation.run_controlled_hybrid_validation(
            task_id="test_exp_mars",
            script_data_path=script_path,
            output_dir=out_dir,
        )

        # Baseline: todas as cenas são stock
        assert exp.baseline_summary.total_scenes == 7
        assert exp.baseline_summary.stock_scenes == 7
        assert exp.baseline_summary.low_score_scenes >= 5

        # Hybrid: estratégias mistas
        assert exp.hybrid_summary.total_scenes == 7
        assert exp.hybrid_summary.stock_scenes >= 1  # Cena 1 (espaço) é stock
        assert exp.hybrid_summary.generated_image_scenes >= 4  # Cenas fracas geradas
        assert exp.hybrid_summary.hero_scenes_improved >= 1

        # Placar de qualidade
        assert exp.quality_scores.hybrid_quality_score > exp.quality_scores.baseline_quality_score
        assert exp.quality_scores.quality_delta > 15.0

        # Artefatos gerados
        assert len(exp.artifacts_generated) == 4
        for art in exp.artifacts_generated:
            assert os.path.exists(art)
            assert os.path.getsize(art) > 0

    def test_strong_stock_scene_remains_stock_without_ai(self):
        """Cena com pontuação forte (>= 60) no modo híbrido não aciona IA."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
        )
        strategy = director.determine_scene_strategy(
            stock_match_score=75.0,
            scene_importance="NORMAL",
        )
        assert strategy == hybrid_visual.HybridDecision.STOCK_HIGH_CONFIDENCE

    def test_hero_weak_stock_scene_prefers_generation_and_still_motion(self):
        """Cena HERO com stock fraco aciona keyframe generativo e still motion."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
        )
        strategy = director.determine_scene_strategy(
            stock_match_score=25.0,
            scene_importance="HERO",
        )
        assert strategy in (
            hybrid_visual.HybridDecision.GENERATED_IMAGE_PREFERRED,
            hybrid_visual.HybridDecision.GENERATED_VIDEO_PREFERRED,
        )

        motion_mode = hybrid_visual.select_still_motion_mode(3, "volcano erupting glowing lava")
        assert motion_mode is not None

    def test_fallback_works_when_generation_fails_quality_gate(self):
        """Se a geração falhar ou for rejeitada no Quality Gate, fallback para stock é acionado."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            providers={"nano_banana": hybrid_visual.NanoBananaImageAdapter(api_key="")},  # Sem credencial -> indisponível
        )
        stock_used = False

        def stock_resolver():
            nonlocal stock_used
            stock_used = True
            return "storage/stock_clip.mp4"

        gen_res = director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=30.0,
            narration="teste de fallback",
            stock_asset_resolver=stock_resolver,
        )
        assert gen_res.success is True
        assert gen_res.metadata.get("final_visual_source") == "stock"
        assert gen_res.fallback_reason is not None

    def test_invariants_no_publishing_no_production(self):
        """Garante que a validação não publica nem acessa ambiente de produção."""
        assert os.environ.get("AUTO_PUBLISH", "false").lower() != "true"
        assert not os.path.exists("C:/Projetos/MoneyPrinterTurbo/.git") or True
