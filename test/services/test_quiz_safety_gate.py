"""
test/services/test_quiz_safety_gate.py
======================================
VIDEO FACTORY — TESTES DIRECIONADOS DO QUIZ SAFETY GATE

Testa:
1. Quiz diferente: aceitação de abertura padrão, CTA padrão e estrutura repetida sem falso positivo.
2. Quiz duplicado: bloqueio para overlap de dilemas (>= 70%) e aviso de review para overlap moderado.
3. Sequência de dilemas: detecção de sequência idêntica repetida.
4. Duplicidade interna: bloqueio de dilema repetido no mesmo vídeo.
5. Roteiro inválido: bloqueio para roteiro vazio ou sem dilemas.
6. Isolamento por perfil/canal: tarefas idênticas em canais diferentes não colidem nem bloqueiam.
7. Duração pós-render: conformidade com YouTube Shorts e faixa editorial de Quiz.
8. Regressão tradicional: preservação estrita do Safety Gate tradicional para vídeos tradicionais.
9. Roteamento: is_quiz_dilemma identifica estritamente quiz_dilemma.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    profile_manager,
    quiz_safety_gate,
    safety_gate,
    task as tm,
)


class TestQuizSafetyGate(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        profile_manager.init_profile_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quiz_safety_gate.init_quiz_safety_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _build_quiz_data(self, dilemma_tuples, closing=True):
        questions = []
        for i, (top_title, bot_title, narr) in enumerate(dilemma_tuples, 1):
            questions.append({
                "id": f"q{i}",
                "header": "O QUE VOCÊ PREFERE?" if i == 1 else "PRÓXIMO DILEMA",
                "narration": narr,
                "top": {"title": top_title, "tag": f"TAG_{i}A", "image_query": "query top"},
                "bottom": {"title": bot_title, "tag": f"TAG_{i}B", "image_query": "query bot"},
                "is_closing_choice": False,
            })
        if closing:
            questions.append({
                "id": f"q{len(dilemma_tuples) + 1}",
                "header": "QUAL VOCÊ ESCOLHE?",
                "narration": "Qual você escolhe? Deixe sua resposta nos comentários e se inscreva no canal!",
                "top": {"title": "Opção A", "tag": "A"},
                "bottom": {"title": "Opção B", "tag": "B"},
                "is_closing_choice": True,
            })
        return {"questions": questions}

    def _build_script_text(self, quiz_data):
        return "\n\n".join(
            f"[{q['id']}] {q['header']} {q['narration']}"
            for q in quiz_data["questions"]
        )

    def test_different_quiz_passes_with_standard_hook_and_cta(self):
        """1. Quizzes com dilemas diferentes passam com PASS mesmo com abertura, CTA e estrutura idênticas."""
        dilemmas_1 = [
            ("Silêncio absoluto", "Gritar sempre", "O que você prefere? Viver em silêncio absoluto... Ou só conseguir falar gritando?"),
            ("Viajar no tempo", "Teletransporte", "Conhecer o passado distante... Ou se teletransportar para qualquer lugar do planeta?"),
            ("Nunca dormir", "Nunca comer", "Nunca mais precisar dormir... Ou nunca mais sentir fome na vida inteira?"),
            ("Voar alto", "Respirar no mar", "Ter o poder de voar nas nuvens... Ou respirar normalmente no fundo do oceano?"),
            ("Frio eterno", "Calor constante", "Viver congelando no Alasca... Ou suar o dia todo no deserto escaldante?"),
            ("Invisibilidade", "Ler pensamentos", "Ficar invisível quando quiser... Ou saber exatamente o que todos estão pensando?"),
        ]
        qdata_1 = self._build_quiz_data(dilemmas_1)
        script_1 = self._build_script_text(qdata_1)

        res_1 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_01",
            topic="Dilemas Impossíveis",
            script=script_1,
            quiz_data=qdata_1,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_1["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(res_1["safety_reasons"], [])

        # Segundo quiz para o mesmo canal: abertura idêntica ("O que você prefere?"), mesmo CTA, mesma estrutura
        # mas com dilemas inteiramente diferentes
        dilemmas_2 = [
            ("Super força", "Super velocidade", "O que você prefere? Ter uma força esmagadora... Ou ser mais veloz que a luz?"),
            ("Riqueza solitária", "Pobreza com amigos", "Ter bilhões mas viver isolado... Ou viver humilde cercado de verdadeiros amigos?"),
            ("Saber o futuro", "Mudar o passado", "Ver tudo o que vai acontecer... Ou consertar todos os erros do passado?"),
            ("Falar com animais", "Falar todos idiomas", "Conversar com qualquer animal... Ou ser fluente em todas as línguas do mundo?"),
            ("Viver 500 anos", "Juventude eterna", "Viver cinco séculos envelhecendo... Ou viver sessenta anos com corpo jovem?"),
            ("Controlar o tempo", "Controlar mentes", "Pausar o relógio mundial... Ou influenciar a mente de qualquer pessoa?"),
        ]
        qdata_2 = self._build_quiz_data(dilemmas_2)
        script_2 = self._build_script_text(qdata_2)

        res_2 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_02",
            topic="Dilemas Impossíveis",
            script=script_2,
            quiz_data=qdata_2,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_2["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(res_2["safety_reasons"], [])

    def test_duplicate_quiz_blocked(self):
        """2. Quizzes com overlap alto (>= 70%) de dilemas em relação a vídeo anterior são bloqueados com BLOCK."""
        dilemmas_base = [
            ("Silêncio absoluto", "Gritar sempre", "O que você prefere? Viver em silêncio absoluto... Ou só conseguir falar gritando?"),
            ("Viajar no tempo", "Teletransporte", "Conhecer o passado distante... Ou se teletransportar para qualquer lugar do planeta?"),
            ("Nunca dormir", "Nunca comer", "Nunca mais precisar dormir... Ou nunca mais sentir fome na vida inteira?"),
            ("Voar alto", "Respirar no mar", "Ter o poder de voar nas nuvens... Ou respirar normalmente no fundo do oceano?"),
            ("Frio eterno", "Calor constante", "Viver congelando no Alasca... Ou suar o dia todo no deserto escaldante?"),
            ("Invisibilidade", "Ler pensamentos", "Ficar invisível quando quiser... Ou saber exatamente o que todos estão pensando?"),
        ]
        qdata_1 = self._build_quiz_data(dilemmas_base)
        script_1 = self._build_script_text(qdata_1)

        quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_base",
            topic="Dilemas da Vida",
            script=script_1,
            quiz_data=qdata_1,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )

        # Repete 5 dos 6 dilemas (83% overlap)
        dilemmas_dup = [
            dilemmas_base[0],
            dilemmas_base[1],
            dilemmas_base[2],
            dilemmas_base[3],
            dilemmas_base[4],
            ("Dilema novo", "Outro novo", "Um dilema completamente novo para tentar mascarar a duplicidade do conteúdo."),
        ]
        qdata_dup = self._build_quiz_data(dilemmas_dup)
        script_dup = self._build_script_text(qdata_dup)

        res_dup = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_dup",
            topic="Dilemas da Vida",
            script=script_dup,
            quiz_data=qdata_dup,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_dup["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("duplicado" in r.lower() for r in res_dup["safety_reasons"]))

    def test_moderate_similarity_quiz_review(self):
        """3. Quizzes com repetição moderada de dilemas (entre 40% e 69%) geram status REVIEW."""
        dilemmas_base = [
            ("Opção 1", "Opção 2", "Dilema número um com escolhas difíceis para reflexão profunda."),
            ("Opção 3", "Opção 4", "Dilema número dois com contrapontos morais intensos."),
            ("Opção 5", "Opção 6", "Dilema número três com consequências desafiadoras."),
            ("Opção 7", "Opção 8", "Dilema número quatro com perdas irreparáveis."),
            ("Opção 9", "Opção 10", "Dilema número cinco com decisões extremas."),
            ("Opção 11", "Opção 12", "Dilema número seis com futuro incerto."),
        ]
        qdata_1 = self._build_quiz_data(dilemmas_base)
        script_1 = self._build_script_text(qdata_1)

        quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_mod_base",
            topic="Escolhas Moderadas",
            script=script_1,
            quiz_data=qdata_1,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )

        # Repete exatamente 3 de 6 dilemas (50% de overlap) em posições não-consecutivas
        dilemmas_mod = [
            dilemmas_base[0],
            ("Novo A", "Novo B", "Novo dilema A sobre exploração espacial e isolamento."),
            dilemmas_base[2],
            ("Novo C", "Novo D", "Novo dilema B sobre sobrevivência em ilha deserta."),
            dilemmas_base[4],
            ("Novo E", "Novo F", "Novo dilema C sobre inteligência artificial avançada."),
        ]
        qdata_mod = self._build_quiz_data(dilemmas_mod)
        script_mod = self._build_script_text(qdata_mod)

        res_mod = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_quiz_mod_target",
            topic="Escolhas Moderadas",
            script=script_mod,
            quiz_data=qdata_mod,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_mod["safety_status"], const.SAFETY_STATUS_REVIEW)
        self.assertTrue(any("similaridade moderada" in r.lower() for r in res_mod["safety_reasons"]))

    def test_internal_duplicate_dilemma_blocked(self):
        """4. Dilema repetido internamente dentro do próprio vídeo gera BLOCK imediato."""
        repeated_dilemma = ("Voar", "Invisibilidade", "Você prefere ter o dom de voar... Ou o dom da invisibilidade completa?")
        dilemmas = [
            repeated_dilemma,
            ("Fogo", "Gelo", "Controlar o elemento fogo com as mãos... Ou congelar tudo ao seu redor com gelo?"),
            repeated_dilemma,  # Repetição interna na posição 3
            ("Dia", "Noite", "Viver para sempre sob a luz do dia... Ou na escuridão permanente da noite?"),
        ]
        qdata = self._build_quiz_data(dilemmas)
        script = self._build_script_text(qdata)

        res = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_internal_dup",
            topic="Super Poderes",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("repetido internamente" in r.lower() for r in res["safety_reasons"]))

    def test_invalid_and_empty_script_blocked(self):
        """5. Roteiro vazio ou sem dilemas válidos é bloqueado."""
        res_empty = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_empty",
            topic="Dilemas",
            script="",
            quiz_data=None,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_empty["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("vazio" in r.lower() for r in res_empty["safety_reasons"]))

        res_no_dilemmas = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_no_dilemmas",
            topic="Dilemas",
            script="Um roteiro curto que tem algumas palavras faladas mas nenhum dilema válido de quiz.",
            quiz_data={"questions": []},
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_no_dilemmas["safety_status"], const.SAFETY_STATUS_BLOCK)

    def test_channel_profile_isolation(self):
        """6. Tarefas idênticas em canais/perfis diferentes NÃO colidem nem se bloqueiam mutuamente."""
        dilemmas = [
            ("Silêncio absoluto", "Gritar sempre", "O que você prefere? Viver em silêncio absoluto... Ou só conseguir falar gritando?"),
            ("Viajar no tempo", "Teletransporte", "Conhecer o passado distante... Ou se teletransportar para qualquer lugar do planeta?"),
            ("Nunca dormir", "Nunca comer", "Nunca mais precisar dormir... Ou nunca mais sentir fome na vida inteira?"),
            ("Voar alto", "Respirar no mar", "Ter o poder de voar nas nuvens... Ou respirar normalmente no fundo do oceano?"),
        ]
        qdata = self._build_quiz_data(dilemmas)
        script = self._build_script_text(qdata)

        # Canal A (Dose Diária de Escolhas)
        res_a = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_chan_a",
            topic="Dilemas",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_a["safety_status"], const.SAFETY_STATUS_PASS)

        # Canal B (Outro canal, ex: profile-historias-misterio ou profile-b) com o mesmo roteiro
        res_b = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_chan_b",
            topic="Dilemas",
            script=script,
            quiz_data=qdata,
            profile_id="profile-historias-misterio",
            db_path=self.db_path,
        )
        # Por pertencer a perfil diferente, NÃO deve ser bloqueado pelo histórico de profile-escolhas
        self.assertEqual(res_b["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(res_b["safety_reasons"], [])

    def test_duration_safety_evaluation(self):
        """7. Validação de duração pós-render para Quiz respeita limites técnicos e editoriais."""
        # Duração válida no alvo [60.0s, 65.0s]
        res_pass = quiz_safety_gate.evaluate_quiz_duration_safety(
            task_id="task_dur_pass",
            actual_duration=63.2,
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(res_pass["safety_status"], const.SAFETY_STATUS_PASS)

        # Duração curta demais para YouTube Shorts (< 15s)
        res_block_short = quiz_safety_gate.evaluate_quiz_duration_safety(
            task_id="task_dur_short",
            actual_duration=12.0,
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(res_block_short["safety_status"], const.SAFETY_STATUS_BLOCK)

        # Duração longa demais para YouTube Shorts (> 180s)
        res_block_long = quiz_safety_gate.evaluate_quiz_duration_safety(
            task_id="task_dur_long",
            actual_duration=195.0,
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(res_block_long["safety_status"], const.SAFETY_STATUS_BLOCK)

        # Duração válida tecnicamente no Shorts (ex: 55s) mas fora da faixa editorial ideal de quiz [60-65s]
        res_review = quiz_safety_gate.evaluate_quiz_duration_safety(
            task_id="task_dur_review",
            actual_duration=55.0,
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(res_review["safety_status"], const.SAFETY_STATUS_REVIEW)

    def test_traditional_safety_gate_regression_preserved(self):
        """8. O Safety Gate tradicional permanece 100% intacto para vídeos tradicionais."""
        trad_script_1 = (
            "Você não vai acreditar neste fato histórico fascinante sobre a construção das pirâmides antigas do Egito. "
            "Pesquisadores descobriram novos hieróglifos que comprovam técnicas avançadas de engenharia e logística. "
            "Os trabalhadores eram altamente remunerados com cerveja e carne de qualidade. "
            "Isso transforma completamente a nossa visão sobre o mundo antigo e o trabalho cooperativo da humanidade. "
            "Deixe seu comentário e se inscreva para mais curiosidades históricas como esta!"
        )
        trad_script_2 = (
            "Você não vai acreditar neste fato histórico fascinante sobre os guerreiros samurais do Japão feudal. "
            "Eles seguiam um código rígido de honra conhecido como Bushido em todas as suas batalhas lendárias. "
            "A espada katana era considerada a própria alma do guerreiro e tratada com reverência sagrada. "
            "A coragem diante do perigo definia toda a sua trajetória desde a infância até a morte gloriosa. "
            "Deixe seu comentário e se inscreva para mais curiosidades históricas como esta!"
        )

        res_trad_1 = safety_gate.evaluate_script_safety(
            task_id="task_trad_01",
            topic="Pirâmides do Egito",
            script=trad_script_1,
            narrative_structure=const.STRUCTURE_FACT_CONTEXT,
            db_path=self.db_path,
        )
        # Primeiro vídeo passa
        self.assertIn(res_trad_1["safety_status"], (const.SAFETY_STATUS_PASS, const.SAFETY_STATUS_REVIEW))

        # Segundo vídeo com hook idêntico ("Você não vai acreditar...") e CTA idêntico
        res_trad_2 = safety_gate.evaluate_script_safety(
            task_id="task_trad_02",
            topic="Guerreiros Samurais",
            script=trad_script_2,
            narrative_structure=const.STRUCTURE_FACT_CONTEXT,
            db_path=self.db_path,
        )
        # O Safety Gate tradicional DEVE bloquear ou colocar em review por repetição de abertura/CTA
        self.assertTrue(
            res_trad_2["safety_status"] in (const.SAFETY_STATUS_BLOCK, const.SAFETY_STATUS_REVIEW),
            "Safety Gate tradicional deve continuar flagrando hooks repetitivos em vídeos tradicionais",
        )
        self.assertTrue(
            any("hook" in r.lower() or "abertura" in r.lower() for r in res_trad_2["safety_reasons"]),
            "Safety Gate tradicional deve acusar abertura semelhante",
        )

    def test_quiz_dilemma_identification_helper(self):
        """9. is_quiz_dilemma identifica estritamente tarefas do formato quiz_dilemma."""
        params_dilemma = VideoParams(video_subject="Escolhas", narrative_structure="quiz_dilemma")
        params_paper = VideoParams(video_subject="Trivia", narrative_structure="quiz_paper")
        params_trad = VideoParams(video_subject="História", narrative_structure="fact_context")
        params_empty = VideoParams(video_subject="Geral")

        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(params=params_dilemma))
        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(narrative_structure="quiz_dilemma"))
        self.assertFalse(quiz_safety_gate.is_quiz_dilemma(params=params_paper))
        self.assertFalse(quiz_safety_gate.is_quiz_dilemma(params=params_trad))
        self.assertFalse(quiz_safety_gate.is_quiz_dilemma(params=params_empty))

    def test_blocked_attempts_do_not_pollute_history_for_subsequent_tasks(self):
        """10. Tentativas rejeitadas (BLOCK) não são salvas como histórico aprovado nem bloqueiam tentativas futuras."""
        dilemmas = [
            ("Opção X", "Opção Y", "Você prefere X ou Y?"),
            ("Opção X", "Opção Y", "Você prefere X ou Y?"),  # Duplicação interna forçando BLOCK
        ]
        qdata_bad = self._build_quiz_data(dilemmas)
        script_bad = self._build_script_text(qdata_bad)

        res_bad = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_bad_attempt",
            topic="Tentativa Ruim",
            script=script_bad,
            quiz_data=qdata_bad,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_bad["safety_status"], const.SAFETY_STATUS_BLOCK)

        # Agora uma nova tentativa corrigida gera dilemas válidos incluindo uma das opções da tentativa rejeitada
        dilemmas_good = [
            ("Opção X", "Opção Y", "Você prefere a opção X ou a opção Y com contexto expandido?"),
            ("Opção W", "Opção Z", "Você prefere a opção W ou a opção Z em um novo cenário?"),
            ("Opção J", "Opção K", "Você prefere a opção J ou a opção K com consequências sérias?"),
            ("Opção M", "Opção N", "Você prefere a opção M ou a opção N para o futuro?"),
        ]
        qdata_good = self._build_quiz_data(dilemmas_good)
        script_good = self._build_script_text(qdata_good)

        res_good = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_good_subsequent",
            topic="Tentativa Boa",
            script=script_good,
            quiz_data=qdata_good,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        # A tentativa boa NÃO deve ser bloqueada pela tentativa rejeitada anterior
        self.assertEqual(res_good["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(res_good["safety_reasons"], [])

    def test_persistence_across_connection_close_and_reopen(self):
        """11. A persistência no SQLite e verificação de duplicidade funcionam após fechamento e reabertura da conexão."""
        fresh_db_path = os.path.join(self.test_dir, "reopen_test.db")
        dilemmas = [
            ("Dilema Alpha", "Dilema Beta", "O que você prefere? Viver no topo da montanha... Ou nas profundezas do vale?"),
            ("Dilema Gamma", "Dilema Delta", "Saber todos os segredos do universo... Ou viver em paz sem nenhuma preocupação?"),
            ("Dilema Epsilon", "Dilema Zeta", "Ter visão raio-X permanente... Ou audição ultra-sônica ininterrupta?"),
            ("Dilema Eta", "Dilema Theta", "Viver sempre no ano 3000... Ou viajar de volta para a era medieval?"),
        ]
        qdata = self._build_quiz_data(dilemmas)
        script = self._build_script_text(qdata)

        # 1. Avalia e grava no banco
        res_1 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_persist_01",
            topic="Dilemas Persistidos",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=fresh_db_path,
        )
        self.assertEqual(res_1["safety_status"], const.SAFETY_STATUS_PASS)

        # 2. Simula encerramento e nova conexão: consulta diretamente o histórico isolado
        fresh_history = quiz_safety_gate.get_isolated_quiz_history(
            profile_id="profile-escolhas",
            db_path=fresh_db_path,
        )
        self.assertEqual(len(fresh_history), 1)
        self.assertEqual(fresh_history[0]["task_id"], "task_persist_01")
        self.assertEqual(len(fresh_history[0]["dilemmas"]), 5)  # 4 dilemas + 1 closing

        # 3. Nova tarefa enviada com os mesmos dilemas deve ser barrada por duplicidade
        res_dup = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_persist_02",
            topic="Dilemas Persistidos",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=fresh_db_path,
        )
        self.assertEqual(res_dup["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("duplicado" in r.lower() for r in res_dup["safety_reasons"]))

    def test_quiz_safety_blocks_when_profile_id_missing_or_default(self):
        """12. Se profile_id obrigatório estiver ausente ou for default, avaliação bloqueia de forma segura."""
        dilemmas = [
            ("A1", "B1", "O que você prefere? A1... Ou B1?"),
            ("A2", "B2", "O que você prefere? A2... Ou B2?"),
            ("A3", "B3", "O que você prefere? A3... Ou B3?"),
            ("A4", "B4", "O que você prefere? A4... Ou B4?"),
        ]
        qdata = self._build_quiz_data(dilemmas)
        script = self._build_script_text(qdata)

        # Sem profile_id (None)
        res_none = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_no_prof",
            topic="Dilemas Sem Perfil",
            script=script,
            quiz_data=qdata,
            profile_id=None,
            db_path=self.db_path,
        )
        self.assertEqual(res_none["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("perfil" in r.lower() for r in res_none["safety_reasons"]))

        # Com profile_id "default" (não permitido para quiz)
        res_def = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_default_prof",
            topic="Dilemas Default",
            script=script,
            quiz_data=qdata,
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertEqual(res_def["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("perfil" in r.lower() for r in res_def["safety_reasons"]))

        # Garante que nenhum histórico foi salvo sob 'default'
        def_history = quiz_safety_gate.get_isolated_quiz_history(
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertEqual(def_history, [])

    def test_failed_quiz_task_does_not_block_subsequent_generations(self):
        """13. Tarefa com PASS que posteriormente falha antes do estoque não impede novas gerações com mesmos dilemas."""
        dilemmas = [
            ("Dilema Alpha", "Dilema Beta", "O que você prefere? Alpha... Ou Beta?"),
            ("Dilema Gama", "Dilema Delta", "O que você prefere? Gama... Ou Delta?"),
            ("Dilema Epsilon", "Dilema Zeta", "O que você prefere? Epsilon... Ou Zeta?"),
            ("Dilema Eta", "Dilema Teta", "O que você prefere? Eta... Ou Teta?"),
        ]
        qdata = self._build_quiz_data(dilemmas)
        script = self._build_script_text(qdata)

        # 1. Tarefa 1 passa na avaliação prévia de roteiro
        res_1 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_fail_01",
            topic="Dilemas Gregos",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_1["safety_status"], const.SAFETY_STATUS_PASS)

        # 2. Tarefa 1 falha na renderização de vídeo antes de chegar ao estoque
        quiz_safety_gate.invalidate_quiz_safety_record(
            task_id="task_fail_01",
            stage="video",
            error="MoviePy Render out-of-memory",
            db_path=self.db_path,
        )

        # 3. Histórico ativo não deve listar task_fail_01
        active_hist = quiz_safety_gate.get_isolated_quiz_history(
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(len(active_hist), 0)

        # 4. Nova geração (Tarefa 2) com os mesmos dilemas NÃO é bloqueada como duplicata
        res_2 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task_success_02",
            topic="Dilemas Gregos",
            script=script,
            quiz_data=qdata,
            profile_id="profile-escolhas",
            db_path=self.db_path,
        )
        self.assertEqual(res_2["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(res_2["safety_reasons"], [])


if __name__ == "__main__":
    unittest.main()


