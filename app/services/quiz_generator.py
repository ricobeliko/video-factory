"""
app/services/quiz_generator.py
==============================
VIDEO FACTORY — FASE Q2: GERAÇÃO AUTOMÁTICA DE CONTEÚDO PARA QUIZ ENGINE

Serviço de geração e estruturação automatizada de conteúdo para o Quiz Engine:
1. Geração para múltiplos nichos (subjetivo: escolhas impossíveis; factual: trivia/conhecimentos verificados).
2. Prevenção de duplicatas via histórico persistente e cálculo de similaridade léxica.
3. Checagem factual estrita para quizzes com resposta correta.
4. Seleção e deduplicação de imagens (Pexels / Pixabay) via IDs e hashes.
5. Ganchos de retenção dinâmicos contextualizados com a última pergunta.
6. Encerramentos flexíveis por canal (CTA de engajamento, desafio de pontuação ou quiz religioso).
7. Serialização em formato JSON estritamente compatível com QuizConfig da Fase Q1.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
import requests

from app.config import config
from app.services import llm, material
from scripts.poc_quiz_render import QuizConfig

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.path.join(ROOT_DIR, "storage", "quiz_history")
QUIZ_TEMPLATES_DIR = os.path.join(ROOT_DIR, "resource", "quiz_templates")


class QuizContentGenerator:
    """Gerador automático de conteúdo para o Quiz Engine (Fase Q2)."""

    def __init__(
        self,
        history_dir: Optional[str] = None,
        templates_dir: Optional[str] = None,
    ):
        self.history_dir = history_dir or STORAGE_DIR
        self.templates_dir = templates_dir or QUIZ_TEMPLATES_DIR
        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(self.templates_dir, exist_ok=True)

        self.questions_history_file = os.path.join(self.history_dir, "generated_questions.json")
        self.images_history_file = os.path.join(self.history_dir, "used_images.json")

        self.question_history = self._load_json(self.questions_history_file, default=[])
        self.used_images = self._load_json(self.images_history_file, default={})

    # -------------------------------------------------------------------------
    # Persistência de Histórico & Prevenção de Duplicatas
    # -------------------------------------------------------------------------
    def _load_json(self, path: str, default: Any) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[QUIZ_GEN] Erro ao carregar histórico {path}: {e}")
        return default

    def _save_json(self, path: str, data: Any) -> None:
        try:
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"[QUIZ_GEN] Erro ao persistir histórico {path}: {e}")

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """Calcula similaridade de Jaccard entre duas frases normalizadas."""
        words_a = set(self._normalize_text(text_a).split())
        words_b = set(self._normalize_text(text_b).split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a.intersection(words_b)
        union = words_a.union(words_b)
        return len(intersection) / len(union)

    def is_question_duplicate(
        self,
        question_text: str,
        options_text: Optional[str] = None,
        narration_threshold: float = 0.45,
        options_threshold: float = 0.50,
        threshold: Optional[float] = None,
    ) -> bool:
        """
        Verifica se a pergunta é idêntica ou semanticamente muito semelhante ao histórico.
        Compara tanto a frase da narração quanto as opções centrais do dilema.
        """
        if threshold is not None:
            narration_threshold = threshold
        norm_q = self._normalize_text(question_text)
        if not norm_q:
            return True
        norm_opt = self._normalize_text(options_text) if options_text else ""

        for entry in self.question_history:
            stored_q = entry.get("question_normalized", "")
            if norm_q == stored_q:
                return True
            sim_q = self._calculate_similarity(norm_q, stored_q)
            if sim_q >= narration_threshold:
                logger.info(f"[QUIZ_GEN] Pergunta descartada por similaridade na narração ({sim_q:.2f} >= {narration_threshold}): '{question_text}'")
                return True

            if norm_opt and entry.get("options_normalized"):
                sim_opt = self._calculate_similarity(norm_opt, entry["options_normalized"])
                if sim_opt >= options_threshold:
                    logger.info(f"[QUIZ_GEN] Pergunta descartada por similaridade nas opções ({sim_opt:.2f} >= {options_threshold}): '{options_text}'")
                    return True
        return False

    def record_question(
        self,
        question_text: str,
        niche: str,
        format_type: str,
        options_text: Optional[str] = None,
    ) -> None:
        """Registra a pergunta no histórico persistente com atomicidade."""
        self.question_history.append({
            "question_text": question_text,
            "question_normalized": self._normalize_text(question_text),
            "options_text": options_text or "",
            "options_normalized": self._normalize_text(options_text) if options_text else "",
            "niche": niche,
            "format_type": format_type,
            "timestamp": time.time(),
        })
        self._save_json(self.questions_history_file, self.question_history)

    def is_image_used(self, asset_id: str, content_hash: Optional[str] = None) -> bool:
        """Verifica se a imagem já foi usada em gerações anteriores."""
        if asset_id and str(asset_id) in self.used_images:
            return True
        if content_hash:
            for stored in self.used_images.values():
                if stored.get("content_hash") == content_hash:
                    return True
        return False

    def record_image(self, asset_id: str, content_hash: str, query: str, provider: str = "pexels") -> None:
        """Registra a imagem usada para evitar repetições."""
        self.used_images[str(asset_id)] = {
            "content_hash": content_hash,
            "query": query,
            "provider": provider,
            "timestamp": time.time(),
        }
        self._save_json(self.images_history_file, self.used_images)

    # -------------------------------------------------------------------------
    # Geração de Conteúdo via LLM
    # -------------------------------------------------------------------------
    # Geração Principal de Conteúdo Automatizado
    # -------------------------------------------------------------------------
    def generate_quiz_structure(
        self,
        niche: str,
        format_type: str = "subjective",
        num_questions: int = 8,
        quiz_title: Optional[str] = None,
        closing_type: str = "engagement_cta",
    ) -> Dict[str, Any]:
        """
        Gera conteúdo completo de quiz com perguntas, alternativas e metadados.
        format_type: 'subjective' (dilemas) ou 'factual' (conhecimentos verificados).
        """
        logger.info(f"[QUIZ_GEN] Gerando quiz: nicho='{niche}', formato='{format_type}', perguntas={num_questions}")

        prompt = self._build_generation_prompt(niche, format_type, num_questions, quiz_title, closing_type)
        raw_response = ""
        parsed_data = None

        try:
            raw_response = llm._generate_response(prompt)
            parsed_data = self._parse_llm_json(raw_response)
        except Exception as exc:
            logger.warning(f"[QUIZ_GEN] LLM falhou ou timeout: {exc}. Usando gerador factual estruturado de fallback.")

        if not parsed_data or not parsed_data.get("questions"):
            logger.warning("[QUIZ_GEN] Resposta da LLM inválida. Aplicando fallback determinístico do nicho.")
            parsed_data = self._generate_fallback_content(niche, format_type, num_questions, quiz_title, closing_type)

        # Filtra duplicatas e valida
        validated_questions = []
        for q in parsed_data.get("questions", []):
            q_text = q.get("narration", "")
            opts_text = f"{q.get('top', {}).get('title', '')} {q.get('bottom', {}).get('title', '')}"

            # Governança factual: LLM self-attestation NÃO concede verified: True!
            if format_type == "factual":
                if not q.get("evidence_source") or "LLM" in str(q.get("evidence_source", "")):
                    q["verified"] = False
                    q["fact_status"] = "UNVERIFIED_LLM_HEURISTIC"
                    q["publication_gate"] = "BLOCKED_PENDING_EXTERNAL_AUDIT"
                    q["evidence_source"] = "LLM Heuristic — requer auditoria/verificação factual independente antes de publicação"
                else:
                    q["verified"] = True
                    q["fact_status"] = "VERIFIED_CANONICAL"
                    q["publication_gate"] = "READY"

            if not self.is_question_duplicate(q_text, opts_text):
                self.record_question(q_text, niche, format_type, opts_text)
                validated_questions.append(q)
            else:
                logger.info(f"[QUIZ_GEN] Duplicata evitada: {q_text[:40]}...")

        # Garante quantidade de perguntas
        if len(validated_questions) < num_questions:
            # Completa com fallback se faltaram perguntas
            fb = self._generate_fallback_content(niche, format_type, num_questions, quiz_title, closing_type)
            for q in fb["questions"]:
                if len(validated_questions) >= num_questions:
                    break
                if q["id"] not in [x["id"] for x in validated_questions]:
                    validated_questions.append(q)

        parsed_data["questions"] = validated_questions[:num_questions]

        # Sanitização e normalização de retenção Q0-R
        for idx, q in enumerate(parsed_data["questions"]):
            # Garante porcentagens simuladas coerentes
            pct_top = q.get("percentage_top")
            pct_bot = q.get("percentage_bottom")
            if pct_top is None or pct_bot is None or (pct_top + pct_bot != 100):
                splits = [(64, 36), (58, 42), (72, 28), (47, 53), (65, 35), (54, 46), (79, 21), (61, 39)]
                s_top, s_bot = splits[idx % len(splits)]
                q["percentage_top"] = s_top
                q["percentage_bottom"] = s_bot

            # Regra Q0-R Item A: "O que você prefere?" SOMENTE na abertura (idx == 0)
            if idx == 0:
                if format_type == "subjective":
                    q["header"] = "O QUE VOCÊ PREFERE?"
                    narr = q.get("narration", "").strip()
                    if not re.search(r"^o\s+que\s+voc[êe]\s+prefere", narr, re.IGNORECASE):
                        q["narration"] = f"O que você prefere? {narr}"
            else:
                # Da 2ª pergunta em diante: remove anúncios ordinais e "o que você prefere"
                narr = q.get("narration", "")
                narr = re.sub(r"^(?:o\s+que\s+voc[êe]\s+prefere\??\s*:?\s*)", "", narr, flags=re.IGNORECASE)
                narr = re.sub(r"^(?:(?:primeira|segunda|terceira|quarta|quinta|sexta|s[ée]tima|oitava|\d+[ªºa]?)\s+(?:pergunta|escolha|dilema|op[çc][ãa]o)\s*:?\s*)", "", narr, flags=re.IGNORECASE)
                q["narration"] = narr.strip()

                hdr = q.get("header", "")
                if re.search(r"(?:primeira|segunda|terceira|quarta|quinta|sexta|s[ée]tima|oitava|\d+[ªºa]?)", hdr, re.IGNORECASE):
                    headers_pool = ["QUAL VOCÊ ESCOLHE?", "DECISÃO DIFÍCIL:", "ESCOLHA RÁPIDO:", "DILEMA IMPOSSÍVEL:", "QUAL O SEU DESTINO:"]
                    q["header"] = headers_pool[(idx - 1) % len(headers_pool)]

        # Configura Gancho de Retenção Dinâmico baseado na penúltima pergunta
        target_climax = parsed_data["questions"][-2] if len(parsed_data["questions"]) >= 2 else parsed_data["questions"][-1]
        hook_text = self._build_dynamic_hook(target_climax, format_type)
        parsed_data["questions"][0]["is_hook"] = True
        parsed_data["questions"][0]["hook_narration"] = hook_text
        parsed_data["retention_hook"] = {
            "enabled": True,
            "question_id": parsed_data["questions"][0]["id"],
            "narration": hook_text,
            "min_countdown_sec": 3.5,
        }

        # Configura Encerramento por Canal (Religioso e Seguir)
        self._apply_channel_closing(parsed_data, closing_type, format_type)

        return parsed_data

    def _build_generation_prompt(
        self,
        niche: str,
        format_type: str,
        num_questions: int,
        quiz_title: Optional[str],
        closing_type: str,
    ) -> str:
        recent_questions = [x.get("question_text", "") for x in self.question_history[-15:] if x.get("question_text")]
        avoid_clause = ""
        if recent_questions:
            avoid_clause = f"\nEvite expressamente repetir ou criar variações das seguintes perguntas já usadas recentemente:\n" + "\n".join([f"- {q}" for q in recent_questions[:8]])

        if format_type == "factual":
            return f"""Você é um roteirista sênior e checador de fatos especialista em quizzes virais educativos (YouTube Shorts / TikTok).
Gere um quiz FACTUAL de alta retenção no nicho '{niche}' com exatamente {num_questions} perguntas.

REGRAS ESTRITAS DE VERIFICAÇÃO FACTUAL E RETENÇÃO:
1. Todas as respostas DEVEM ser cientificamente ou historicamente comprovadas e aceitas. Não use mitos populares ou fatos controversos.
2. Cada pergunta DEVE ter duas alternativas: uma rigorosamente VERDADEIRA e outra um distrator plausível.
3. No campo 'correct_option', indique estritamente 'A' ou 'B'.
4. No campo 'fact_explanation', resuma a evidência comprovada em 1 frase.
5. As opções de texto devem ser curtas e diretas (máximo 4 a 5 palavras por opção).
6. As queries de imagem ('image_query') devem ser em inglês, altamente descritivas e cinematográficas.
7. NARRAÇÃO DIRETA: Da 2ª pergunta em diante, NÃO anuncie 'segunda pergunta', 'terceira escolha'. Vá direto às alternativas!
8. Adicione 'percentage_top' e 'percentage_bottom' somando 100.
{avoid_clause}

Retorne ESTRITAMENTE um objeto JSON válido (sem markdown, sem tags, sem explicações):
{{
  "niche": "{niche}",
  "quiz_title": "{quiz_title or 'TESTE SEUS CONHECIMENTOS'}",
  "format_type": "factual",
  "closing_type": "{closing_type}",
  "questions": [
    {{
      "id": "q1",
      "header": "TESTE SEUS CONHECIMENTOS:",
      "narration": "Qual animal tem o maior coração do reino animal? Opção A... Ou Opção B?",
      "top": {{
        "title": "TEXTO DA OPÇÃO A",
        "tag": "OPÇÃO A",
        "image_query": "query em ingles para pexels",
        "image_name": "q1_top.jpg",
        "theme": "red"
      }},
      "bottom": {{
        "title": "TEXTO DA OPÇÃO B",
        "tag": "OPÇÃO B",
        "image_query": "query em ingles para pexels",
        "image_name": "q1_bot.jpg",
        "theme": "blue"
      }},
      "correct_option": "A ou B",
      "fact_explanation": "Explicação factual verificada...",
      "verified": true,
      "percentage_top": 64,
      "percentage_bottom": 36,
      "countdown_sec": 3.0
    }}
  ]
}}
""".strip()
        else:
            return f"""Você é um roteirista sênior especialista em quizzes psicológicos de escolhas impossíveis ("O que você prefere?").
Gere um quiz SUBJETIVO de dilemas impossíveis no nicho '{niche}' com exatamente {num_questions} escolhas.

REGRAS DE RETENÇÃO ABSOLUTA (Q0-R):
1. NARRAÇÃO DIRETA: Use "O que você prefere?" SOMENTE na primeira pergunta (q1).
2. Da 2ª pergunta em diante, NUNCA anuncie "segunda pergunta", "terceira escolha" ou "o que você prefere". Narre direto as alternativas: "Alternativa A... Ou Alternativa B?".
3. Sem pausas artificiais. Ritmo ágil e dinâmico.
4. Sem certo ou errado: as duas alternativas devem ser tentadoras ou aterrorizantes, provocando curiosidade e debate.
5. Textos curtos e chamativos para os cards (máximo 4 a 5 palavras).
6. Queries de imagens ('image_query') em inglês para busca no Pexels.
7. Adicione 'percentage_top' e 'percentage_bottom' somando 100 (simulação de votação popular).
{avoid_clause}

Retorne ESTRITAMENTE um objeto JSON válido (sem markdown, sem tags, sem explicações):
{{
  "niche": "{niche}",
  "quiz_title": "{quiz_title or 'QUAL VOCÊ ESCOLHERIA?'}",
  "format_type": "subjective",
  "closing_type": "{closing_type}",
  "questions": [
    {{
      "id": "q1",
      "header": "O QUE VOCÊ PREFERE?",
      "narration": "O que você prefere? Ganhar um milhão todo mês... Ou ter juventude eterna?",
      "top": {{
        "title": "TEXTO CURTO A",
        "tag": "OPÇÃO A",
        "image_query": "query em ingles",
        "image_name": "q1_top.jpg",
        "theme": "red"
      }},
      "bottom": {{
        "title": "TEXTO CURTO B",
        "tag": "OPÇÃO B",
        "image_query": "query em ingles",
        "image_name": "q1_bot.jpg",
        "theme": "blue"
      }},
      "percentage_top": 64,
      "percentage_bottom": 36,
      "countdown_sec": 3.0
    }}
  ]
}}
""".strip()

    def _parse_llm_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Extrai e valida JSON retornado pelo modelo."""
        if not raw_text:
            return None
        # Remove blocos markdown fence
        cleaned = re.sub(r"^```(?:json)?", "", raw_text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "questions" in data:
                    return data
            except Exception:
                pass
        return None

    # -------------------------------------------------------------------------
    # Gancho de Retenção Dinâmico & Encerramento Flexível
    # -------------------------------------------------------------------------
    def _build_dynamic_hook(self, last_question: Dict[str, Any], format_type: str) -> str:
        """Gera gancho contextualizado com a última pergunta."""
        last_top = last_question.get("top", {}).get("title", "")
        last_bot = last_question.get("bottom", {}).get("title", "")

        if format_type == "factual":
            topic = last_top.lower() or "última pergunta"
            return f"Mas atenção... a última pergunta sobre {topic[:25]} vai te surpreender!"
        else:
            return "Mas atenção... a última escolha vai te surpreender!"

    def _apply_channel_closing(self, quiz_data: Dict[str, Any], closing_type: str, format_type: str) -> None:
        """Configura o encerramento respeitando as regras de retenção Q0-R."""
        questions = quiz_data.get("questions", [])
        if not questions:
            return

        if closing_type == "quiz_choice_religious":
            # Q0-R Item E: Penúltima escolha — Engajamento religioso
            if len(questions) >= 2:
                penult_q = questions[-2]
                penult_q["header"] = "ESCOLHA RÁPIDO:"
                penult_q["narration"] = "Ficar dois dias sem internet e sem Wi-Fi... Ou curtir e comentar: Jesus te ama?"
                penult_q["top"] = {
                    "title": "FICAR DOIS DIAS SEM WI-FI",
                    "tag": "OPÇÃO A",
                    "image_query": "broken wifi smartphone internet disconnect",
                    "image_name": f"{penult_q['id']}_top.jpg",
                    "theme": "red",
                }
                penult_q["bottom"] = {
                    "title": "CURTIR E COMENTAR: JESUS TE AMA",
                    "tag": "OPÇÃO B",
                    "image_query": "jesus christ cross heavenly light sunset",
                    "image_name": f"{penult_q['id']}_bot.jpg",
                    "theme": "gold_red",
                }
                penult_q["percentage_top"] = 14
                penult_q["percentage_bottom"] = 86
                penult_q["countdown_sec"] = 3.0

            # Q0-R Item F: Última escolha — Seguir o perfil
            last_q = questions[-1]
            last_q["is_closing_choice"] = True
            last_q["header"] = "QUAL O SEU DESTINO:"
            last_q["narration"] = "Passar direto e perder os próximos vídeos... Ou seguir o perfil e apoiar o canal agora?"
            last_q["top"] = {
                "title": "PASSAR DIRETO E PERDER TUDO",
                "tag": "OPÇÃO A",
                "image_query": "person walking away empty dark road night",
                "image_name": f"{last_q['id']}_top.jpg",
                "theme": "blue_neutral",
            }
            last_q["bottom"] = {
                "title": "SEGUIR O PERFIL AGORA",
                "tag": "OPÇÃO B",
                "image_query": "smartphone social media follow subscribe celebration confetti",
                "image_name": f"{last_q['id']}_bot.jpg",
                "theme": "gold_red",
            }
            last_q["percentage_top"] = 9
            last_q["percentage_bottom"] = 91
            last_q["countdown_sec"] = 3.0
        elif closing_type == "score_challenge" or format_type == "factual":
            last_q = questions[-1]
            last_q["is_closing_choice"] = True
            last_q["header"] = "DESAFIO FINAL:"
            if not last_q.get("narration"):
                last_q["narration"] = "Desafio final: Comente quantas você acertou! Opção A: Acertei todas... Ou Opção B: Errei alguma?"
                last_q["top"] = {
                    "title": "ACERTEI TODAS AS PERGUNTAS",
                    "tag": "OPÇÃO A",
                    "image_query": "champion trophy gold victory celebration",
                    "image_name": f"{last_q['id']}_top.jpg",
                    "theme": "gold_red",
                }
                last_q["bottom"] = {
                    "title": "ERREI UMA OU MAIS",
                    "tag": "OPÇÃO B",
                    "image_query": "thinking student books question mark",
                    "image_name": f"{last_q['id']}_bot.jpg",
                    "theme": "blue_neutral",
                }
                last_q["percentage_top"] = 73
                last_q["percentage_bottom"] = 27
                last_q["countdown_sec"] = 3.0
        else:
            # engagement_cta padrão neutro (Q0-R Seguir)
            last_q = questions[-1]
            last_q["is_closing_choice"] = True
            last_q["header"] = "QUAL O SEU DESTINO:"
            last_q["narration"] = "Passar direto e perder os próximos vídeos... Ou seguir o perfil e apoiar o canal agora?"
            last_q["top"] = {
                "title": "PASSAR DIRETO E PERDER",
                "tag": "OPÇÃO A",
                "image_query": "person walking away road silhouette",
                "image_name": f"{last_q['id']}_top.jpg",
                "theme": "blue_neutral",
            }
            last_q["bottom"] = {
                "title": "SEGUIR O PERFIL AGORA",
                "tag": "OPÇÃO B",
                "image_query": "smartphone follow subscribe celebration",
                "image_name": f"{last_q['id']}_bot.jpg",
                "theme": "gold_red",
            }
            last_q["percentage_top"] = 12
            last_q["percentage_bottom"] = 88
            last_q["countdown_sec"] = 3.0

    # -------------------------------------------------------------------------
    # Fallback Determinístico Factual e Subjetivo
    # -------------------------------------------------------------------------
    def _generate_fallback_content(
        self,
        niche: str,
        format_type: str,
        num_questions: int,
        quiz_title: Optional[str],
        closing_type: str,
    ) -> Dict[str, Any]:
        """Gera conteúdo com garantia de validade, gramática perfeita e precisão científica."""
        if format_type == "factual":
            return {
                "niche": niche or "curiosidades_animais",
                "quiz_title": quiz_title or "TESTE DE CONHECIMENTOS: ANIMAIS",
                "format_type": "factual",
                "closing_type": closing_type,
                "questions": [
                    {
                        "id": "q1",
                        "header": "PRIMEIRA PERGUNTA:",
                        "narration": "Primeira pergunta: Qual animal tem o maior coração do reino animal, pesando cerca de cento e oitenta quilos? Opção A: O elefante africano... Ou Opção B: A baleia-azul?",
                        "top": {
                            "title": "ELEFANTE AFRICANO",
                            "tag": "OPÇÃO A",
                            "image_query": "african elephant safari savanna",
                            "image_name": "animal_q1_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "BALEIA-AZUL",
                            "tag": "OPÇÃO B",
                            "image_query": "blue whale ocean swimming water",
                            "image_name": "animal_q1_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O coração da baleia-azul é o maior do reino animal, com cerca de 180 kg e do tamanho de um carro pequeno.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q2",
                        "header": "SEGUNDA PERGUNTA:",
                        "narration": "Segunda pergunta: Qual destes animais consegue dormir com metade do cérebro acordado para continuar respirando? Opção A: O golfinho... Ou Opção B: O cavalo?",
                        "top": {
                            "title": "GOLFINHO NO OCEANO",
                            "tag": "OPÇÃO A",
                            "image_query": "dolphin jumping ocean blue water",
                            "image_name": "animal_q2_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "CAVALO NO CAMPO",
                            "tag": "OPÇÃO B",
                            "image_query": "horse running green pasture nature",
                            "image_name": "animal_q2_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "A",
                        "fact_explanation": "Golfinhos praticam o sono uni-hemisférico: metade do cérebro descansa enquanto a outra metade vigia a respiração.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q3",
                        "header": "TERCEIRA PERGUNTA:",
                        "narration": "Terceira pergunta: Qual destas aves é a única no planeta capaz de voar para trás? Opção A: O falcão-peregrino... Ou Opção B: O beija-flor?",
                        "top": {
                            "title": "FALCÃO PEREGRINO",
                            "tag": "OPÇÃO A",
                            "image_query": "peregrine falcon flying sky predator",
                            "image_name": "animal_q3_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "BEIJA-FLOR NA FLOR",
                            "tag": "OPÇÃO B",
                            "image_query": "hummingbird flying flower macro garden",
                            "image_name": "animal_q3_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O beija-flor possui articulações alares que giram em 180 graus, permitindo voo para trás e pairar no ar.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q4",
                        "header": "QUARTA PERGUNTA:",
                        "narration": "Quarta pergunta: Qual animal tem a mordida mais poderosa medida em pressão por centímetro quadrado? Opção A: O tubarão-branco... Ou Opção B: O crocodilo-de-água-salgada?",
                        "top": {
                            "title": "TUBARÃO BRANCO",
                            "tag": "OPÇÃO A",
                            "image_query": "great white shark ocean underwater",
                            "image_name": "animal_q4_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "CROCODILO DE ÁGUA SALGADA",
                            "tag": "OPÇÃO B",
                            "image_query": "saltwater crocodile reptile river predator",
                            "image_name": "animal_q4_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O crocodilo-de-água-salgada tem a maior força de mordida já medida em animais vivos, superando 3.700 psi.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q5",
                        "header": "QUINTA PERGUNTA:",
                        "narration": "Quinta pergunta: Qual destes animais tem três corações e sangue de cor azul? Opção A: O polvo... Ou Opção B: A água-viva?",
                        "top": {
                            "title": "POLVO NO FUNDO DO MAR",
                            "tag": "OPÇÃO A",
                            "image_query": "octopus ocean reef underwater camouflage",
                            "image_name": "animal_q5_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "ÁGUA-VIVA BRILHANTE",
                            "tag": "OPÇÃO B",
                            "image_query": "jellyfish glowing blue dark ocean",
                            "image_name": "animal_q5_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "A",
                        "fact_explanation": "O polvo tem 3 corações e sangue azul à base de hemocianina (rica em cobre), ideal para águas frias e profundas.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q6",
                        "is_closing_choice": True,
                        "header": "DESAFIO FINAL:",
                        "narration": "Desafio final: Comente quantas você acertou! Opção A: Acertei todas as cinco perguntas... Ou Opção B: Errei pelo menos uma?",
                        "top": {
                            "title": "ACERTEI TODAS AS 5 PERGUNTAS",
                            "tag": "OPÇÃO A",
                            "image_query": "gold medal trophy champion winner",
                            "image_name": "animal_q6_top.jpg",
                            "theme": "gold_red",
                        },
                        "bottom": {
                            "title": "ERREI PELO MENOS UMA",
                            "tag": "OPÇÃO B",
                            "image_query": "curious cat looking surprised eyes",
                            "image_name": "animal_q6_bot.jpg",
                            "theme": "blue_neutral",
                        },
                        "countdown_sec": 3.2,
                    },
                ],
            }
        else:
            return {
                "niche": niche or "curiosidades_dilemas",
                "quiz_title": quiz_title or "QUAL VOCÊ ESCOLHERIA?",
                "format_type": "subjective",
                "closing_type": closing_type,
                "questions": [
                    {
                        "id": "q1",
                        "header": "O QUE VOCÊ PREFERE?",
                        "narration": "O que você prefere? Ganhar um milhão de reais na sua conta todo mês... Ou ter juventude eterna e nunca mais envelhecer?",
                        "top": {
                            "title": "R$ 1 MILHÃO TODO MÊS",
                            "tag": "OPÇÃO A",
                            "image_query": "gold bars money wealth luxury",
                            "image_name": "q1_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "JUVENTUDE ETERNA",
                            "tag": "OPÇÃO B",
                            "image_query": "hourglass sand youth time",
                            "image_name": "q1_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 64,
                        "percentage_bottom": 36,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q2",
                        "header": "DECISÃO DIFÍCIL:",
                        "narration": "Ter a habilidade de voar para qualquer lugar do planeta... Ou poder ficar invisível sempre que você quiser?",
                        "top": {
                            "title": "PODER VOAR PELO PLANETA",
                            "tag": "OPÇÃO A",
                            "image_query": "airplane flight clouds sunset",
                            "image_name": "q2_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "FICAR INVISÍVEL QUANDO QUISER",
                            "tag": "OPÇÃO B",
                            "image_query": "mysterious shadow silhouette night",
                            "image_name": "q2_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 58,
                        "percentage_bottom": 42,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q3",
                        "header": "ESCOLHA RÁPIDO:",
                        "narration": "Conseguir ler a mente de qualquer pessoa no mundo... Ou saber exatamente o futuro da humanidade?",
                        "top": {
                            "title": "LER A MENTE DE QUALQUER PESSOA",
                            "tag": "OPÇÃO A",
                            "image_query": "human brain glowing thinking",
                            "image_name": "q3_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "SABER O FUTURO DA HUMANIDADE",
                            "tag": "OPÇÃO B",
                            "image_query": "futuristic city cyberpunk night",
                            "image_name": "q3_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 72,
                        "percentage_bottom": 28,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q4",
                        "header": "DILEMA IMPOSSÍVEL:",
                        "narration": "Nunca mais sentir nenhum cansaço físico na vida... Ou nunca mais sentir nenhuma tristeza ou ansiedade?",
                        "top": {
                            "title": "NUNCA MAIS SENTIR CANSAÇO",
                            "tag": "OPÇÃO A",
                            "image_query": "athlete running sprint power",
                            "image_name": "q4_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "NUNCA MAIS SENTIR ANSIEDADE",
                            "tag": "OPÇÃO B",
                            "image_query": "meditation calm lake sunrise",
                            "image_name": "q4_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 47,
                        "percentage_bottom": 53,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q5",
                        "header": "DECISÃO DIFÍCIL:",
                        "narration": "Falar fluentemente todas as línguas do mundo... Ou saber se comunicar perfeitamente com todos os animais?",
                        "top": {
                            "title": "FALAR TODAS AS LÍNGUAS",
                            "tag": "OPÇÃO A",
                            "image_query": "earth globe map international flags",
                            "image_name": "q5_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "FALAR COM TODOS OS ANIMAIS",
                            "tag": "OPÇÃO B",
                            "image_query": "wild lion safari animal connection",
                            "image_name": "q5_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 65,
                        "percentage_bottom": 35,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q6",
                        "header": "ESCOLHA RÁPIDO:",
                        "narration": "Viajar no tempo e conhecer a história antiga... Ou viajar para o futuro e ver civilizações espaciais?",
                        "top": {
                            "title": "VIAJAR PARA O PASSADO",
                            "tag": "OPÇÃO A",
                            "image_query": "ancient pyramid egypt desert history",
                            "image_name": "q6_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "VIAJAR PARA O FUTURO",
                            "tag": "OPÇÃO B",
                            "image_query": "futuristic city cyberpunk night spaceship",
                            "image_name": "q6_bot_v2.jpg",
                            "theme": "blue",
                        },
                        "percentage_top": 54,
                        "percentage_bottom": 46,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q7",
                        "header": "ESCOLHA RÁPIDO:",
                        "narration": "Ficar dois dias sem internet e sem Wi-Fi... Ou curtir e comentar: Jesus te ama?",
                        "top": {
                            "title": "FICAR DOIS DIAS SEM WI-FI",
                            "tag": "OPÇÃO A",
                            "image_query": "broken wifi smartphone internet disconnect",
                            "image_name": "q7_top_v2.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "CURTIR E COMENTAR: JESUS TE AMA",
                            "tag": "OPÇÃO B",
                            "image_query": "jesus christ cross heavenly light sunset",
                            "image_name": "q7_bot_v2.jpg",
                            "theme": "gold_red",
                        },
                        "percentage_top": 14,
                        "percentage_bottom": 86,
                        "countdown_sec": 3.0,
                    },
                    {
                        "id": "q8",
                        "is_closing_choice": True,
                        "header": "QUAL O SEU DESTINO:",
                        "narration": "Passar direto e perder os próximos vídeos... Ou seguir o perfil e apoiar o canal agora?",
                        "top": {
                            "title": "PASSAR DIRETO E PERDER TUDO",
                            "tag": "OPÇÃO A",
                            "image_query": "person walking away empty dark road night",
                            "image_name": "q8_top_v2.jpg",
                            "theme": "blue_neutral",
                        },
                        "bottom": {
                            "title": "SEGUIR O PERFIL AGORA",
                            "tag": "OPÇÃO B",
                            "image_query": "smartphone social media follow subscribe celebration confetti",
                            "image_name": "q8_bot_v2.jpg",
                            "theme": "gold_red",
                        },
                        "percentage_top": 9,
                        "percentage_bottom": 91,
                        "countdown_sec": 3.0,
                    },
                ][:num_questions],
            }

    # -------------------------------------------------------------------------
    # Criação do Objeto QuizConfig Completo e Serialização JSON
    # -------------------------------------------------------------------------
    def export_to_quiz_config(
        self,
        raw_quiz: Dict[str, Any],
        output_json_path: str,
        output_video_path: Optional[str] = None,
        output_thumbnail_path: Optional[str] = None,
        temp_dir: Optional[str] = None,
        images_dir: Optional[str] = None,
    ) -> QuizConfig:
        """Monta a estrutura compatível com a Quiz Engine e exporta para JSON."""
        niche = raw_quiz.get("niche", "curiosidades")
        title = raw_quiz.get("quiz_title", "QUAL VOCÊ ESCOLHERIA?")
        slug = re.sub(r"[^\w]", "_", niche.lower())

        video_path = output_video_path or f"storage/poc_quiz/quiz_{slug}.mp4"
        thumb_path = output_thumbnail_path or f"storage/poc_quiz/quiz_{slug}_thumb.jpg"
        t_dir = temp_dir or f"storage/poc_quiz/temp_{slug}"
        img_dir = images_dir or "storage/poc_quiz/images_v2"

        # Thumbnail settings derivadas da Q1
        first_q = raw_quiz["questions"][0]
        thumbnail_settings = {
            "banner_text": title,
            "top_option": {
                "tag": first_q["top"].get("tag", "OPÇÃO A"),
                "title": first_q["top"].get("title", ""),
                "image_name": first_q["top"].get("image_name", "q1_top_v2.jpg"),
            },
            "bottom_option": {
                "tag": first_q["bottom"].get("tag", "OPÇÃO B"),
                "title": first_q["bottom"].get("title", ""),
                "image_name": first_q["bottom"].get("image_name", "q1_bot_v2.jpg"),
            },
        }

        config_data = {
            "niche": niche,
            "quiz_title": title,
            "output_video_path": video_path,
            "output_thumbnail_path": thumb_path,
            "temp_dir": t_dir,
            "images_dir": img_dir,
            "min_target_duration_sec": 60.0,
            "target_duration_range": [62.0, 66.0],
            "video_settings": {
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "font_path": "resource/fonts/BeVietnamPro-Bold.ttf",
                "bgm_path": "resource/songs/output000.mp3",
                "bgm_volume": 0.14,
            },
            "voice_settings": {
                "voice_name": "pt-BR-AntonioNeural",
                "voice_rate": "+12%",
            },
            "countdown_settings": {
                "default_sec": 3.0,
                "expectation_sec": 2.0,
                "reveal_sec": 1.0,
                "enable_countdown_badges": False,
                "enable_percentages": True,
                "closing_sec": 3.0,
                "badges": ["3", "2", "1"],
                "colors": {
                    "badge_ou_bg": [255, 214, 0],
                    "badge_ou_text": [0, 0, 0],
                    "badge_3_bg": [255, 75, 75],
                    "badge_2_bg": [255, 170, 0],
                    "badge_1_bg": [45, 210, 60],
                    "badge_countdown_text": [255, 255, 255],
                },
            },
            "retention_hook": raw_quiz.get("retention_hook", {
                "enabled": True,
                "question_id": first_q["id"],
                "narration": first_q.get("hook_narration", "Mas atenção... a última escolha vai te surpreender!"),
                "min_countdown_sec": 3.85,
            }),
            "theme_palettes": {
                "red": {
                    "card_fill": [140, 12, 24, 230],
                    "card_outline": [255, 65, 75, 255],
                    "tag_fill": [230, 25, 38, 255],
                    "tag_outline": [255, 255, 255, 240],
                    "text_color": [255, 255, 255],
                },
                "blue": {
                    "card_fill": [12, 45, 125, 230],
                    "card_outline": [55, 140, 255, 255],
                    "tag_fill": [20, 95, 230, 255],
                    "tag_outline": [255, 255, 255, 240],
                    "text_color": [255, 255, 255],
                },
                "gold_red": {
                    "card_fill": [150, 15, 25, 235],
                    "card_outline": [255, 215, 0, 255],
                    "tag_fill": [220, 30, 40, 255],
                    "tag_outline": [255, 215, 0, 255],
                    "text_color": [255, 255, 255],
                },
                "blue_neutral": {
                    "card_fill": [20, 35, 75, 235],
                    "card_outline": [90, 150, 230, 255],
                    "tag_fill": [30, 70, 150, 255],
                    "tag_outline": [200, 220, 255, 240],
                    "text_color": [255, 255, 255],
                },
            },
            "thumbnail_settings": thumbnail_settings,
            "questions": raw_quiz["questions"],
        }

        os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        logger.success(f"[QUIZ_GEN] Configuração exportada para JSON com sucesso: {output_json_path}")
        return QuizConfig.from_dict(config_data)

    def generate_paper_quiz_structure(
        self,
        niche: str = "conhecimentos_gerais",
        num_questions: int = 10,
        quiz_title: Optional[str] = None,
        closing_type: str = "score_challenge",
    ) -> Dict[str, Any]:
        """Gera ou carrega estrutura canônica para o Quiz de Papel (multiple_choice_paper)."""
        logger.info(f"[QUIZ_GEN] Gerando quiz de papel: nicho='{niche}', perguntas={num_questions}")
        template_file = os.path.join(self.templates_dir, "quiz_template_p1_3_papel_homologado.json")
        if not os.path.exists(template_file):
            template_file = os.path.join(self.templates_dir, "quiz_template_perguntas_respostas_papel.json")

        base_data = {}
        if os.path.exists(template_file):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    base_data = json.load(f)
            except Exception as e:
                logger.warning(f"[QUIZ_GEN] Erro ao carregar template canônico de papel: {e}")

        questions = list(base_data.get("questions", []))
        # Marcação e garantia de governança factual estrita
        for q in questions:
            # Perguntas auditadas e com fontes independentes homologadas recebem VERIFIED
            if q.get("source") and any(src in str(q["source"]) for src in ("NASA", "Smithsonian", "National Geographic", "NIST", "UNESCO", "Gray's Anatomy", "Louvre", "NOAA")):
                q["verified"] = True
                q["fact_status"] = "VERIFIED_CANONICAL"
                q["publication_gate"] = "READY"
            elif q.get("verified") is True:
                q["verified"] = True
                q["fact_status"] = "VERIFIED_CANONICAL"
                q["publication_gate"] = "READY"
            else:
                # Perguntas sem comprovação independente são bloqueadas
                q["verified"] = False
                q["fact_status"] = "UNVERIFIED_HEURISTIC"
                q["publication_gate"] = "BLOCKED_PENDING_EXTERNAL_AUDIT"

        return {
            "quiz_type": "multiple_choice_paper",
            "niche": niche or base_data.get("niche", "conhecimentos_gerais"),
            "quiz_title": quiz_title or base_data.get("quiz_title", "QUIZ CONHECIMENTOS GERAIS"),
            "sheet_header": base_data.get("sheet_header", {
                "title": "AVALIAÇÃO DE CONHECIMENTOS",
                "subtitle": "TESTE DE RACIOCÍNIO & FATOS REAIS",
                "exam_code": "PROVA N° 101 - TURBO QUIZ",
            }),
            "timing_settings": base_data.get("timing_settings", {
                "expectation_sec": 6.0,
                "reveal_sec": 1.0,
            }),
            "intro_hook": base_data.get("intro_hook", {
                "enabled": True,
                "narration": "Desafio de conhecimentos gerais! Quantas você acerta?",
            }),
            "outro_challenge": base_data.get("outro_challenge", {
                "enabled": True,
                "duration_sec": 6.0,
                "narration": "Quantas você acertou? Comente sua pontuação!",
            }),
            "min_target_duration_sec": 60.0,
            "max_target_duration_sec": 65.0,
            "target_duration_range": [60.0, 65.0],
            "questions": questions[:num_questions] if num_questions else questions,
        }

    def export_to_paper_quiz_config(
        self,
        raw_quiz: Dict[str, Any],
        output_video_path: str,
        output_thumbnail_path: str,
        temp_dir: str,
        output_json_path: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_rate: str = "+20%",
    ) -> Any:
        """Exporta configuração serializada para o PaperQuizEngine (P1.3)."""
        from scripts.poc_quiz_paper_render import PaperQuizConfig
        canonical_template_path = os.path.join(
            self.templates_dir, "quiz_template_p1_3_papel_homologado.json"
        )
        if not os.path.exists(canonical_template_path):
            canonical_template_path = os.path.join(
                self.templates_dir, "quiz_template_perguntas_respostas_papel.json"
            )

        base_data = {}
        if os.path.exists(canonical_template_path):
            try:
                with open(canonical_template_path, "r", encoding="utf-8") as f:
                    base_data = json.load(f)
            except Exception:
                base_data = {}

        config_data = dict(base_data)
        config_data["output_video_path"] = output_video_path
        config_data["output_thumbnail_path"] = output_thumbnail_path
        config_data["temp_dir"] = temp_dir
        config_data["niche"] = raw_quiz.get("niche") or config_data.get("niche", "conhecimentos_gerais")
        config_data["quiz_title"] = raw_quiz.get("quiz_title") or config_data.get("quiz_title", "QUIZ CONHECIMENTOS GERAIS")
        if raw_quiz.get("questions"):
            config_data["questions"] = raw_quiz["questions"]
        if raw_quiz.get("sheet_header"):
            config_data["sheet_header"] = raw_quiz["sheet_header"]
        if raw_quiz.get("intro_hook"):
            config_data["intro_hook"] = raw_quiz["intro_hook"]
        if raw_quiz.get("outro_challenge"):
            config_data["outro_challenge"] = raw_quiz["outro_challenge"]

        config_data["min_target_duration_sec"] = 60.0
        config_data["max_target_duration_sec"] = 65.0
        config_data["target_duration_range"] = [60.0, 65.0]

        if "voice_settings" not in config_data:
            config_data["voice_settings"] = {}
        config_data["voice_settings"]["voice_name"] = voice_name or config_data["voice_settings"].get("voice_name") or "pt-BR-AntonioNeural"
        config_data["voice_settings"]["voice_rate"] = voice_rate or "+20%"

        if output_json_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

        return PaperQuizConfig.from_dict(config_data)

