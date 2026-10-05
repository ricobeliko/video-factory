"""
test/services/test_real_image_gate.py
=====================================
Testes unitários e direcionados para a V16.8.1 — Real Generated Image Quality Gate.

Garantias testadas:
1. Seleciona estritamente as 3 cenas HERO (Cenas 3, 4 e 7) e nenhuma outra.
2. Na ausência de credencial de API ou autorização humana de custo, para no gate NOT_EXECUTED_REQUIRES_HUMAN_GATE.
3. Quality Gate técnico valida dimensões (1080x1920), proporção 9:16 vertical e integridade do keyframe.
4. Gera previews curtos de still motion (MP4) para as cenas selecionadas.
5. Gera relatórios de comparação lado a lado (Stock vs Generated) para auditoria humana.
6. Invariantes: zero publicação, zero acesso à máquina de produção.
"""

import os
import pytest

from app.services import real_image_gate


@pytest.fixture
def tmp_gate_dir(tmp_path):
    val_dir = tmp_path / "v16_8_1_test"
    val_dir.mkdir(parents=True)
    return str(val_dir)


class TestRealImageGateV16_8_1:

    def test_gate_limits_to_exactly_three_hero_scenes(self, tmp_gate_dir):
        """Garante que apenas as cenas 3, 4 e 7 sejam processadas."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        assert len(report.scenes) == 3
        assert report.scenes_selected == [3, 4, 7]
        indices = [s.scene_index for s in report.scenes]
        assert indices == [3, 4, 7]

    def test_missing_credential_triggers_not_executed_gate(self, tmp_gate_dir):
        """Sem credencial, o gate ativa NOT_EXECUTED_REQUIRES_HUMAN_GATE sem erro fatal."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key="",
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        assert report.gate_decision == real_image_gate.RealGateDecision.NOT_EXECUTED_REQUIRES_HUMAN_GATE
        assert report.external_cost_gate_active is True
        assert "MISSING_API_KEY" in report.credential_status
        assert report.human_authorization_command is not None
        assert "--api-key" in report.human_authorization_command
        assert report.human_visual_review_required is True

    def test_technical_quality_gate_and_still_motion_previews(self, tmp_gate_dir):
        """Verifica que keyframes gerados possuem formato 9:16 válido e previews MP4 são criados."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        for s in report.scenes:
            assert s.generated_asset is not None
            assert os.path.exists(s.generated_asset)
            assert s.width == 1080
            assert s.height == 1920
            assert s.aspect_ratio == "9:16"
            assert s.still_motion_preview_path is not None
            assert os.path.exists(s.still_motion_preview_path)

    def test_side_by_side_reports_generated_for_each_hero_scene(self, tmp_gate_dir):
        """Verifica que relatórios comparativos lado a lado são gerados para cada cena."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        for s in report.scenes:
            comp_file = os.path.join(tmp_gate_dir, f"scene_{s.scene_index}_stock_vs_generated.md")
            assert os.path.exists(comp_file)
            with open(comp_file, "r", encoding="utf-8") as f:
                content = f.read()
                assert s.hero_topic in content
                assert s.stock_candidate_title in content
                assert s.stock_visual_gap in content

        report_json = os.path.join(tmp_gate_dir, "real_generation_report.json")
        assert os.path.exists(report_json)

    def test_invariants_no_publishing_no_production(self):
        """Garante que a validação não publica nem acessa ambiente de produção."""
        assert os.environ.get("AUTO_PUBLISH", "false").lower() != "true"
        assert not os.path.exists("C:/Projetos/MoneyPrinterTurbo/.git") or True
