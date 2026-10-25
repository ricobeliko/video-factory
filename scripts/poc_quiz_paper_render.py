"""
scripts/poc_quiz_paper_render.py
================================
VIDEO FACTORY — FASE P0: PROTÓTIPO QUIZ PERGUNTAS E RESPOSTAS (FOLHA DE PAPEL)
Ambiente: DEV — D:\\Projetos\\MoneyPrinterTurbo

Protótipo isolado para renderização de vídeos verticais no formato
"Quiz — Perguntas e Respostas" com estética de folha de prova/questionário impresso.

Requisitos atendidos:
- Formato vertical 1080x1920 a 30fps.
- Estética de folha de papel com margem, pauta suave e cabeçalho de exame.
- Pergunta em destaque de alto contraste e legibilidade mobile.
- 4 alternativas (A, B, C, D) por pergunta.
- Revelação imediata e clara da alternativa correta com marcação e badge.
- Efeito sonoro de acerto (chime harmônico procedural) sincronizado à revelação.
- Movimento sutil de câmera (Ken Burns via zoompan) evitando imagem estática.
- Janela de expectativa (~2s) e revelação (~1.2s) sem contagem regressiva repetitiva.
- Narração fluida e natural via Edge TTS (pt-BR).
- Duração total > 60 segundos com conteúdo 100% factual e fontes auditáveis.
- Geração de MP4 final, Thumbnail 9:16 independente e metadados JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils
from app.services.media_quality import probe_media


class DurationGateError(RuntimeError):
    """Lançada quando a duração estimada ou final do vídeo viola a faixa obrigatória."""
    pass


# =============================================================================
# Configuração do Protótipo (PaperQuizConfig)
# =============================================================================

@dataclass
class PaperQuizConfig:
    quiz_type: str = "multiple_choice_paper"
    niche: str = "conhecimentos_gerais"
    quiz_title: str = "QUIZ CONHECIMENTOS GERAIS"
    output_video_path: str = "storage/poc_quiz_papel/quiz_perguntas_respostas_papel.mp4"
    output_thumbnail_path: str = "storage/poc_quiz_papel/quiz_perguntas_respostas_thumbnail.jpg"
    temp_dir: str = "storage/poc_quiz_papel/temp"
    min_target_duration_sec: float = 60.0
    max_target_duration_sec: float = 65.0
    target_duration_range: Tuple[float, float] = (60.0, 65.0)

    sheet_header: Dict[str, Any] = field(default_factory=lambda: {
        "title": "AVALIAÇÃO DE CONHECIMENTOS",
        "subtitle": "TESTE DE RACIOCÍNIO & FATOS REAIS",
        "exam_code": "PROVA N° 101 - TURBO QUIZ",
    })

    video_settings: Dict[str, Any] = field(default_factory=lambda: {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "font_bold": "resource/fonts/BeVietnamPro-Bold.ttf",
        "font_medium": "resource/fonts/BeVietnamPro-Medium.ttf",
        "bgm_path": "",
        "bgm_volume": 0.12,
    })

    voice_settings: Dict[str, Any] = field(default_factory=lambda: {
        "voice_name": "pt-BR-AntonioNeural",
        "voice_rate": "+20%",
    })

    timing_settings: Dict[str, Any] = field(default_factory=lambda: {
        "expectation_sec": 6.0,
        "reveal_sec": 1.0,
    })

    intro_hook: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "narration": "Desafio de conhecimentos gerais! Será que você consegue acertar todas as perguntas? Vamos para a questão número um!",
    })

    outro_challenge: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "narration": "E aí, quantas você conseguiu acertar? Deixe sua pontuação nos comentários e siga para mais desafios diários!",
    })

    questions: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PaperQuizConfig:
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                if k == "target_duration_range" and isinstance(v, list):
                    setattr(cfg, k, tuple(v))
                else:
                    setattr(cfg, k, v)
        cfg.output_video_path = _resolve_path(cfg.output_video_path)
        cfg.output_thumbnail_path = _resolve_path(cfg.output_thumbnail_path)
        cfg.temp_dir = _resolve_path(cfg.temp_dir)
        cfg.video_settings["font_bold"] = _resolve_path(cfg.video_settings.get("font_bold", ""))
        cfg.video_settings["font_medium"] = _resolve_path(cfg.video_settings.get("font_medium", ""))
        cfg.video_settings["bgm_path"] = _resolve_path(cfg.video_settings.get("bgm_path", ""))
        return cfg

    @classmethod
    def from_json(cls, json_path: str | Path) -> PaperQuizConfig:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


def _resolve_path(p: str) -> str:
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(ROOT_DIR, p))


# =============================================================================
# Motor de Renderização de Quiz em Folha de Papel (PaperQuizEngine)
# =============================================================================

class PaperQuizEngine:
    """Motor dedicado para renderização de Quizzes no formato Folha de Papel / Questionário."""

    def __init__(self, config: PaperQuizConfig):
        self.config = config
        self.ffmpeg_bin = utils.get_ffmpeg_binary()
        os.makedirs(os.path.dirname(self.config.output_video_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.config.output_thumbnail_path), exist_ok=True)
        os.makedirs(self.config.temp_dir, exist_ok=True)

        self.font_bold_path = self.config.video_settings["font_bold"]
        self.font_med_path = self.config.video_settings["font_medium"]

    def _get_font(self, size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_file = self.font_bold_path if bold else self.font_med_path
        if font_file and os.path.exists(font_file):
            try:
                return ImageFont.truetype(font_file, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # -------------------------------------------------------------------------
    # 1. Desenho da Folha de Papel Base
    # -------------------------------------------------------------------------
    def _draw_paper_sheet(self) -> Image.Image:
        """Cria o fundo com estética realista e limpa de folha de exame sobre prancheta."""
        w = self.config.video_settings["width"]
        h = self.config.video_settings["height"]

        # 1. Fundo da prancheta / mesa de suporte
        img = Image.new("RGBA", (w, h), (18, 24, 38, 255))  # Deep navy/slate
        draw = ImageDraw.Draw(img)

        # 2. Sombra da folha de papel
        sheet_x1, sheet_y1 = 44, 44
        sheet_x2, sheet_y2 = w - 44, h - 44
        radius = 28

        for offset in range(6, 0, -1):
            alpha = int(24 * (1.0 - offset / 7.0))
            draw.rounded_rectangle(
                [sheet_x1 + offset, sheet_y1 + offset, sheet_x2 + offset, sheet_y2 + offset],
                radius=radius,
                fill=(0, 0, 0, alpha),
            )

        # 3. Folha de papel principal (marfim caloroso / off-white suave)
        paper_color = (252, 251, 247, 255)
        draw.rounded_rectangle(
            [sheet_x1, sheet_y1, sheet_x2, sheet_y2],
            radius=radius,
            fill=paper_color,
            outline=(220, 218, 208, 255),
            width=2,
        )

        # 4. Linhas pautadas discretas
        line_color = (235, 237, 230, 160)
        start_y = 360
        while start_y < sheet_y2 - 60:
            draw.line([(sheet_x1 + 30, start_y), (sheet_x2 - 30, start_y)], fill=line_color, width=1)
            start_y += 44

        # 5. Margem vermelha suave à esquerda
        margin_x = sheet_x1 + 86
        draw.line([(margin_x, sheet_y1 + 40), (margin_x, sheet_y2 - 40)], fill=(245, 192, 192, 180), width=2)

        # 6. Furos de fichário estilizados
        holes_y = [sheet_y1 + 180, (sheet_y1 + sheet_y2) // 2, sheet_y2 - 180]
        hole_x = sheet_x1 + 42
        for hy in holes_y:
            # Sombra interna do furo
            draw.ellipse([hole_x - 14, hy - 14, hole_x + 14, hy + 14], fill=(215, 215, 210, 255), outline=(195, 195, 190, 255), width=2)
            draw.ellipse([hole_x - 11, hy - 11, hole_x + 11, hy + 11], fill=(18, 24, 38, 255))

        # 7. Cabeçalho oficial de exame / prova
        hdr = self.config.sheet_header
        f_title = self._get_font(32, bold=True)
        f_sub = self._get_font(20, bold=False)
        f_code = self._get_font(18, bold=True)

        header_x = sheet_x1 + 120
        draw.text((header_x, sheet_y1 + 48), hdr.get("title", "AVALIAÇÃO DE CONHECIMENTOS"), font=f_title, fill=(20, 30, 50, 255))
        draw.text((header_x, sheet_y1 + 92), hdr.get("subtitle", "TESTE DE RACIOCÍNIO & FATOS REAIS"), font=f_sub, fill=(90, 100, 120, 255))

        # Badge do código da prova no topo direito
        code_text = hdr.get("exam_code", "PROVA TURBO 101")
        draw.rounded_rectangle([sheet_x2 - 290, sheet_y1 + 52, sheet_x2 - 40, sheet_y1 + 94], radius=10, fill=(240, 243, 248, 255), outline=(200, 210, 225, 255), width=1)
        draw.text((sheet_x2 - 275, sheet_y1 + 62), code_text, font=f_code, fill=(40, 60, 95, 255))

        # Linha de preenchimento do estudante
        f_std = self._get_font(20, bold=False)
        std_y = sheet_y1 + 138
        draw.text((header_x, std_y), "CANDIDATO: ____________________________", font=f_std, fill=(100, 110, 130, 255))
        draw.text((sheet_x2 - 250, std_y), f"NOTA: [  / {len(self.config.questions):02d} ]", font=f_std, fill=(100, 110, 130, 255))

        # Linha divisória dupla
        draw.line([(sheet_x1 + 110, std_y + 38), (sheet_x2 - 40, std_y + 38)], fill=(40, 60, 90, 255), width=2)
        draw.line([(sheet_x1 + 110, std_y + 42), (sheet_x2 - 40, std_y + 42)], fill=(180, 190, 205, 255), width=1)

        return img

    # -------------------------------------------------------------------------
    # 2. Renderização de Cenário de Pergunta (Normal e Revelado)
    # -------------------------------------------------------------------------
    def render_question_frame(
        self,
        item: Dict[str, Any],
        revealed: Optional[bool] = None,
        state: str = "options",
    ) -> Image.Image:
        """Desenha a tela da questão para os 3 estados da sequência:
        - 'question_only': enunciado em foco com narração; alternativas ainda não exibidas.
        - 'options': alternativas A/B/C/D visíveis para janela de raciocínio.
        - 'revealed': resposta correta destacada com borda/badge verde e marcação de caneta.
        """
        if revealed is not None:
            state = "revealed" if revealed else "options"

        base_img = self._draw_paper_sheet()
        draw = ImageDraw.Draw(base_img)

        w = self.config.video_settings["width"]
        margin_left = 160
        box_width = w - margin_left - 84
        box_right = margin_left + box_width

        # 1. Faixa da Questão: Categoria & Número
        curr_y = 265
        cat_text = str(item.get("category", "GERAL")).upper()
        num_val = item.get("number", 1)
        num_str = item.get("number_str") or f"QUESTÃO {num_val:02d} DE {len(self.config.questions):02d}"

        # Pill badge de categoria
        f_cat = self._get_font(20, bold=True)
        cat_w = draw.textlength(cat_text, font=f_cat) + 36
        draw.rounded_rectangle([margin_left, curr_y, margin_left + cat_w, curr_y + 38], radius=8, fill=(30, 58, 138, 255))
        draw.text((margin_left + 18, curr_y + 8), cat_text, font=f_cat, fill=(255, 255, 255, 255))

        # Número da questão à direita
        f_num = self._get_font(24, bold=True)
        num_w = draw.textlength(num_str, font=f_num)
        draw.text((box_right - num_w, curr_y + 6), num_str, font=f_num, fill=(15, 23, 42, 255))

        curr_y += 62

        # 2. Caixa da Pergunta (Statement Box)
        q_text = item.get("question", "")
        f_q = self._get_font(42, bold=True)

        # Word wrap da pergunta para caber perfeitamente
        wrapped_q_lines = self._wrap_text(q_text, f_q, box_width - 60)
        line_height = 56
        q_box_h = max(160, len(wrapped_q_lines) * line_height + 56)

        draw.rounded_rectangle(
            [margin_left, curr_y, box_right, curr_y + q_box_h],
            radius=18,
            fill=(255, 255, 255, 255),
            outline=(190, 202, 220, 255),
            width=2,
        )

        # Barra lateral azul na caixa da pergunta
        draw.rounded_rectangle(
            [margin_left, curr_y, margin_left + 12, curr_y + q_box_h],
            radius=4,
            fill=(37, 99, 235, 255),
        )

        ty = curr_y + 28
        for line in wrapped_q_lines:
            draw.text((margin_left + 34, ty), line, font=f_q, fill=(15, 23, 42, 255))
            ty += line_height

        curr_y += q_box_h + 40

        # 3. Caixa de Dica de Tempo / Status conforme o estado da cena
        f_timer = self._get_font(23, bold=True)
        bar_h = 64
        if state == "revealed":
            timer_bg = (209, 250, 229, 255)
            timer_outline = (16, 185, 129, 255)
            timer_text = "✓ RESPOSTA CORRETA!"
            timer_text_color = (6, 95, 70, 255)
            draw.rounded_rectangle([margin_left, curr_y, box_right, curr_y + bar_h], radius=14, fill=timer_bg, outline=timer_outline, width=2)
            tw = draw.textlength(timer_text, font=f_timer)
            draw.text((margin_left + (box_width - tw) / 2, curr_y + 19), timer_text, font=f_timer, fill=timer_text_color)
        elif state == "question_only":
            timer_bg = (241, 245, 249, 255)
            timer_outline = (148, 163, 184, 255)
            timer_text = "📝 OUÇA A QUESTÃO... (AS OPÇÕES VÃO SURGIR)"
            timer_text_color = (30, 41, 59, 255)
            draw.rounded_rectangle([margin_left, curr_y, box_right, curr_y + bar_h], radius=14, fill=timer_bg, outline=timer_outline, width=2)
            tw = draw.textlength(timer_text, font=f_timer)
            draw.text((margin_left + (box_width - tw) / 2, curr_y + 19), timer_text, font=f_timer, fill=timer_text_color)
        else:
            timer_bg = (254, 243, 199, 255)
            timer_outline = (245, 158, 11, 255)
            exp_display = int(round(float(self.config.timing_settings.get("expectation_sec", 6.0))))
            timer_text = f"⏱️ ESCOLHA SUA RESPOSTA: {exp_display} SEGUNDOS"
            timer_text_color = (146, 64, 14, 255)
            draw.rounded_rectangle([margin_left, curr_y, box_right, curr_y + bar_h], radius=14, fill=timer_bg, outline=timer_outline, width=2)
            draw.text((margin_left + 26, curr_y + 19), timer_text, font=f_timer, fill=timer_text_color)

        curr_y += bar_h + 30

        # Se for estado 'question_only', as alternativas ainda não surgiram na folha
        if state == "question_only":
            return base_img

        # 4. Alternativas (A, B, C, D) para os estados 'options' e 'revealed'
        options = item.get("options", [])
        correct_letter = str(item.get("correct_option", "A")).upper()
        f_opt = self._get_font(34, bold=True)
        f_letter = self._get_font(34, bold=True)
        opt_card_h = 138
        gap = 26

        for opt in options:
            letter = str(opt.get("letter", "")).upper()
            text = opt.get("text", "")
            is_correct = (letter == correct_letter)

            card_y1 = curr_y
            card_y2 = curr_y + opt_card_h

            if state == "revealed":
                if is_correct:
                    c_bg = (236, 253, 245, 255)       # Mint verde claro
                    c_border = (5, 150, 105, 255)      # Emerald vibrante
                    c_bwidth = 4
                    c_circle = (5, 150, 105, 255)
                    c_text = (6, 78, 59, 255)
                else:
                    c_bg = (248, 250, 252, 230)       # Muted
                    c_border = (226, 232, 240, 255)
                    c_bwidth = 1
                    c_circle = (148, 163, 184, 255)
                    c_text = (148, 163, 184, 255)
            else:
                c_bg = (255, 255, 255, 255)           # Branco puro
                c_border = (203, 213, 225, 255)       # Slate suave
                c_bwidth = 2
                c_circle = (30, 41, 59, 255)          # Navy dark
                c_text = (15, 23, 42, 255)

            # Card de fundo
            draw.rounded_rectangle([margin_left, card_y1, box_right, card_y2], radius=16, fill=c_bg, outline=c_border, width=c_bwidth)

            # Círculo da letra da alternativa
            circle_x = margin_left + 64
            circle_y = card_y1 + (opt_card_h // 2)
            cr = 30
            draw.ellipse([circle_x - cr, circle_y - cr, circle_x + cr, circle_y + cr], fill=c_circle)

            # Letra centralizada
            lw = draw.textlength(letter, font=f_letter)
            draw.text((circle_x - lw / 2, circle_y - 20), letter, font=f_letter, fill=(255, 255, 255, 255))

            # Se for a correta revelada, desenha uma marcação circular de caneta/marcador ao redor
            if state == "revealed" and is_correct:
                draw.ellipse([circle_x - cr - 6, circle_y - cr - 6, circle_x + cr + 6, circle_y + cr + 6], outline=(16, 185, 129, 255), width=3)
                draw.ellipse([circle_x - cr - 9, circle_y - cr - 9, circle_x + cr + 9, circle_y + cr + 9], outline=(5, 150, 105, 160), width=2)

            # Texto da alternativa
            draw.text((circle_x + 52, card_y1 + 48), text, font=f_opt, fill=c_text)

            # Se revelada e correta, adiciona carimbo de acerto "✓ CORRETA"
            if state == "revealed" and is_correct:
                f_chk = self._get_font(22, bold=True)
                chk_text = "✓ CORRETA"
                chkw = draw.textlength(chk_text, font=f_chk) + 32
                chk_x = box_right - chkw - 24
                chk_y = card_y1 + 44
                draw.rounded_rectangle([chk_x, chk_y, chk_x + chkw, chk_y + 48], radius=10, fill=(16, 185, 129, 255))
                draw.text((chk_x + 16, chk_y + 11), chk_text, font=f_chk, fill=(255, 255, 255, 255))

            curr_y += opt_card_h + gap

        # 5. Explicação e Fonte Factual no Rodapé da Prova (apenas na revelação)
        if state == "revealed" and item.get("explanation"):
            f_exp = self._get_font(20, bold=False)
            f_src = self._get_font(18, bold=True)
            exp_text = f"💡 Fato: {item['explanation']}"
            src_text = f"📚 Fonte Factual: {item.get('source', 'Enciclopédia & Fontes Oficiais')}"

            draw.text((margin_left, curr_y + 16), exp_text, font=f_exp, fill=(55, 65, 81, 255))
            draw.text((margin_left, curr_y + 50), src_text, font=f_src, fill=(100, 116, 139, 255))

        return base_img

    def get_question_timer_position(self, question_text: str) -> Tuple[int, int]:
        """Calcula as coordenadas (x, y) exatas no vídeo para o overlay do timer circular progressivo,
        alinhando perfeitamente ao slot na folha com compensação do leve movimento Ken Burns.
        """
        margin_left = 120
        box_width = 840
        box_right = margin_left + box_width  # 960
        curr_y = 330
        f_q = self._get_font(38, bold=True)
        wrapped_q_lines = self._wrap_text(question_text, f_q, box_width - 80)
        line_height = 50
        q_box_h = max(130, len(wrapped_q_lines) * line_height + 48)
        curr_y += q_box_h + 40

        bar_h = 64
        slot_cx = box_right - 44
        slot_cy = curr_y + (bar_h // 2)
        widget_size = 48
        raw_x = slot_cx - (widget_size // 2)
        raw_y = slot_cy - (widget_size // 2)

        # Ajuste de compensação da sutil escala Ken Burns (zoom=1.025 centrado em 540, 960)
        zoomed_x = int(round(540 + (raw_x - 540) * 1.025))
        zoomed_y = int(round(960 + (raw_y - 960) * 1.025))
        return (zoomed_x, zoomed_y)

    # -------------------------------------------------------------------------
    # 3. Telas Especiais: Abertura (Intro) e Encerramento (Outro)
    # -------------------------------------------------------------------------
    def render_intro_frame(self) -> Image.Image:
        """Renderiza a folha de capa do quiz com título e chamada instigante."""
        img = self._draw_paper_sheet()
        draw = ImageDraw.Draw(img)

        w = self.config.video_settings["width"]
        f_big = self._get_font(52, bold=True)
        f_sub = self._get_font(28, bold=False)
        f_pill = self._get_font(26, bold=True)

        center_y = 560
        draw.rounded_rectangle([200, center_y - 20, w - 200, center_y + 48], radius=14, fill=(37, 99, 235, 255))
        pill_txt = "★ TESTE DE CONHECIMENTOS GERAIS ★"
        pw = draw.textlength(pill_txt, font=f_pill)
        draw.text(((w - pw) / 2, center_y - 4), pill_txt, font=f_pill, fill=(255, 255, 255, 255))

        center_y += 110
        title_lines = ["SERÁ QUE VOCÊ", "CONSEGUE GABARITAR", "ESTE QUESTIONÁRIO?"]
        for line in title_lines:
            lw = draw.textlength(line, font=f_big)
            draw.text(((w - lw) / 2, center_y), line, font=f_big, fill=(15, 23, 42, 255))
            center_y += 72

        center_y += 40
        sub_lines = [
            "6 Perguntas Selecionadas de Ciência, História e Natureza.",
            "Você terá 2 segundos para pensar após cada pergunta.",
            "Atenção: a última questão quase ninguém acerta!"
        ]
        for s in sub_lines:
            sw = draw.textlength(s, font=f_sub)
            draw.text(((w - sw) / 2, center_y), s, font=f_sub, fill=(71, 85, 105, 255))
            center_y += 48

        # Selo de exame oficial
        stamp_y = center_y + 120
        draw.rounded_rectangle([w // 2 - 220, stamp_y, w // 2 + 220, stamp_y + 80], radius=16, fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), width=2)
        f_stamp = self._get_font(24, bold=True)
        st_txt = "📝 PROVA PRONTA • COMEÇANDO..."
        stw = draw.textlength(st_txt, font=f_stamp)
        draw.text(((w - stw) / 2, stamp_y + 24), st_txt, font=f_stamp, fill=(30, 41, 59, 255))

        return img

    def render_outro_frame(self) -> Image.Image:
        """Renderiza a folha de notas e encerramento do desafio (P1.3: 6s com incentivo aos comentários)."""
        img = self._draw_paper_sheet()
        draw = ImageDraw.Draw(img)

        w = self.config.video_settings["width"]
        f_big = self._get_font(48, bold=True)
        f_sub = self._get_font(32, bold=True)
        f_badge = self._get_font(24, bold=True)

        center_y = 500
        badge_txt = "RESULTADO FINAL"
        bw = draw.textlength(badge_txt, font=f_badge) + 40
        draw.rounded_rectangle([(w - bw) / 2, center_y, (w + bw) / 2, center_y + 44], radius=10, fill=(5, 150, 105, 255))
        draw.text(((w - bw) / 2 + 20, center_y + 8), badge_txt, font=f_badge, fill=(255, 255, 255, 255))

        center_y += 84
        t1 = "QUANTAS VOCÊ ACERTOU?"
        tw1 = draw.textlength(t1, font=f_big)
        draw.text(((w - tw1) / 2, center_y), t1, font=f_big, fill=(15, 23, 42, 255))

        center_y += 66
        t2 = "Comente sua pontuação!"
        tw2 = draw.textlength(t2, font=f_sub)
        draw.text(((w - tw2) / 2, center_y), t2, font=f_sub, fill=(37, 99, 235, 255))

        center_y += 90
        nq = len(self.config.questions)
        top_range = f"{max(1, nq - 1)} a {nq}" if nq > 4 else f"{nq} / {nq}"
        mid_range = f"{max(1, nq - 2)} a {max(1, nq - 1)}" if nq > 4 else f"{max(1, nq - 1)}"
        low_range = f"1 a {max(1, nq - 3)}" if nq > 4 else "1 ou menos"
        score_cards = [
            (f"{nq} / {nq}", "Gênio Supremo! Gabaritou!"),
            (mid_range, "Muito bom! Quase perfeito!"),
            (low_range, "Valeu a tentativa! Treine mais!"),
        ]
        f_sc = self._get_font(26, bold=True)
        f_desc = self._get_font(24, bold=False)
        for sc, desc in score_cards:
            draw.rounded_rectangle([180, center_y, w - 180, center_y + 70], radius=12, fill=(255, 255, 255, 255), outline=(203, 213, 225, 255), width=2)
            draw.text((210, center_y + 18), sc, font=f_sc, fill=(37, 99, 235, 255))
            draw.text((340, center_y + 20), desc, font=f_desc, fill=(30, 41, 59, 255))
            center_y += 94

        center_y += 50
        cta_text = "👇 DEIXE SUA PONTUAÇÃO NOS COMENTÁRIOS! 👇"
        f_cta = self._get_font(26, bold=True)
        ctaw = draw.textlength(cta_text, font=f_cta)
        draw.text(((w - ctaw) / 2, center_y), cta_text, font=f_cta, fill=(220, 38, 38, 255))

        return img

    # -------------------------------------------------------------------------
    # 4. Geração de Thumbnail Independente (9:16)
    # -------------------------------------------------------------------------
    def generate_thumbnail(self) -> str:
        """Gera uma thumbnail independente vertical 1080x1920 de alto contraste."""
        img = self._draw_paper_sheet()
        draw = ImageDraw.Draw(img)
        w = self.config.video_settings["width"]

        # Banner impactante no topo
        draw.rounded_rectangle([120, 320, w - 120, 420], radius=16, fill=(220, 38, 38, 255))
        f_top = self._get_font(36, bold=True)
        t_top = "TESTE DE CONHECIMENTOS GERAIS"
        tw = draw.textlength(t_top, font=f_top)
        draw.text(((w - tw) / 2, 348), t_top, font=f_top, fill=(255, 255, 255, 255))

        # Pergunta clássica intrigante em destaque
        f_q = self._get_font(52, bold=True)
        q_lines = ["QUANTOS CORAÇÕES", "TEM UM POLVO?"]
        qy = 500
        for ql in q_lines:
            qw = draw.textlength(ql, font=f_q)
            draw.text(((w - qw) / 2, qy), ql, font=f_q, fill=(15, 23, 42, 255))
            qy += 74

        # 4 cards de alternativas para preview visual
        opts = [
            ("A", "1 CORAÇÃO"),
            ("B", "2 CORAÇÕES"),
            ("C", "3 CORAÇÕES"),
            ("D", "4 CORAÇÕES"),
        ]
        f_opt = self._get_font(36, bold=True)
        f_let = self._get_font(34, bold=True)
        card_y = 740

        for letter, text in opts:
            draw.rounded_rectangle([160, card_y, w - 160, card_y + 110], radius=16, fill=(255, 255, 255, 255), outline=(203, 213, 225, 255), width=2)
            draw.ellipse([210, card_y + 25, 270, card_y + 85], fill=(30, 41, 59, 255))
            lw = draw.textlength(letter, font=f_let)
            draw.text((240 - lw / 2, card_y + 36), letter, font=f_let, fill=(255, 255, 255, 255))
            draw.text((310, card_y + 34), text, font=f_opt, fill=(15, 23, 42, 255))
            card_y += 136

        # Sticker chamativo "99% ERRAM A ÚLTIMA!"
        draw.rounded_rectangle([140, card_y + 40, w - 140, card_y + 140], radius=18, fill=(254, 240, 138, 255), outline=(234, 179, 8, 255), width=3)
        f_stk = self._get_font(38, bold=True)
        stk_txt = "🔥 DUVIDO VOCÊ ACERTAR TODAS!"
        stkw = draw.textlength(stk_txt, font=f_stk)
        draw.text(((w - stkw) / 2, card_y + 66), stk_txt, font=f_stk, fill=(133, 77, 14, 255))

        out_thumb = self.config.output_thumbnail_path
        img.convert("RGB").save(out_thumb, "JPEG", quality=95)
        logger.info(f"[THUMBNAIL] Gerada com sucesso: {out_thumb}")
        return out_thumb

    # -------------------------------------------------------------------------
    # 5. Efeito Sonoro Procedural de Acerto (Chime Harmônico)
    # -------------------------------------------------------------------------
    def generate_correct_ding_sfx(self) -> str:
        """Sintetiza proceduralmente um som de sino/ding de acerto límpido e agradável."""
        out_wav = os.path.join(self.config.temp_dir, "sfx_correct_ding.wav")
        if os.path.exists(out_wav) and os.path.getsize(out_wav) > 500:
            return out_wav

        sample_rate = 44100
        duration = 0.55  # 550ms
        num_samples = int(sample_rate * duration)

        # Tríade harmônica límpida (C6: 1046.5Hz, E6: 1318.5Hz, G6: 1567.9Hz)
        freqs = [1046.5, 1318.5, 1567.9]
        weights = [0.55, 0.35, 0.20]

        samples: List[int] = []
        for n in range(num_samples):
            t = n / sample_rate
            # Ataque ultra rápido de 4ms
            attack = min(1.0, t / 0.004)
            # Decaimento suave exponencial
            decay = math.exp(-t * 6.5)
            envelope = attack * decay

            val = 0.0
            for freq, weight in zip(freqs, weights):
                val += weight * math.sin(2.0 * math.pi * freq * t)

            sample_int = int(val * envelope * 28000)
            sample_int = max(-32768, min(32767, sample_int))
            samples.append(sample_int)

        with wave.open(out_wav, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            raw_data = struct.pack(f"<{len(samples)}h", *samples)
            wf.writeframes(raw_data)

        logger.info(f"[SFX] Chime de acerto sintetizado com sucesso: {out_wav}")
        return out_wav

    def generate_thinking_ticks_sfx(self, duration: float = 6.0) -> str:
        """Sintetiza proceduralmente tique-taques curtos, ritmados e discretos (~1 por segundo)."""
        out_wav = os.path.join(self.config.temp_dir, f"sfx_thinking_ticks_{int(duration)}s.wav")
        if os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000:
            return out_wav

        sample_rate = 44100
        total_samples = int(sample_rate * duration)
        samples = [0] * total_samples

        # Tiques distribuídos uniformemente a cada 1.0s (t = 0.5s, 1.5s, 2.5s, 3.5s, 4.5s, 5.5s para 6s)
        num_ticks = int(duration)
        tick_offsets = [0.5 + i * 1.0 for i in range(num_ticks) if (0.5 + i * 1.0) < duration]
        tick_duration = 0.025
        tick_samples_len = int(sample_rate * tick_duration)

        for offset_sec in tick_offsets:
            start_idx = int(offset_sec * sample_rate)
            for i in range(tick_samples_len):
                if start_idx + i >= total_samples:
                    break
                t = i / sample_rate
                attack = min(1.0, t / 0.0008)
                decay = math.exp(-t * 140.0)
                env = attack * decay
                val = 0.65 * math.sin(2.0 * math.pi * 1600.0 * t) + 0.35 * math.sin(2.0 * math.pi * 2400.0 * t)
                sample_val = int(val * env * 14000)
                samples[start_idx + i] = max(-32768, min(32767, sample_val))

        with wave.open(out_wav, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            raw_data = struct.pack(f"<{len(samples)}h", *samples)
            wf.writeframes(raw_data)

        logger.info(f"[SFX] Tique-taque de expectativa ({duration:.1f}s) sintetizado com sucesso: {out_wav}")
        return out_wav

    def generate_circular_timer_frames(self, duration: float = 6.0, fps: int = 30) -> Tuple[str, Tuple[int, int]]:
        """Sintetiza os frames transparentes do indicador circular progressivo que se preenche
        no sentido horário de 0% a 100% exatamente durante a janela de expectativa de 6 segundos.
        """
        timer_dir = os.path.join(self.config.temp_dir, "timer_frames")
        os.makedirs(timer_dir, exist_ok=True)
        total_frames = int(round(duration * fps))

        size = 48
        cx = size // 2
        cy = size // 2
        radius = 18
        stroke_width = 4

        first_frame = os.path.join(timer_dir, "timer_000.png")
        last_frame = os.path.join(timer_dir, f"timer_{total_frames - 1:03d}.png")
        if os.path.exists(first_frame) and os.path.exists(last_frame) and os.path.getsize(last_frame) > 100:
            pattern = os.path.join(timer_dir, "timer_%03d.png").replace("\\", "/")
            return pattern, (size, size)

        for i in range(total_frames):
            frame_path = os.path.join(timer_dir, f"timer_{i:03d}.png")
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # 1. Base circular com fundo branco e contorno sutil
            draw.ellipse([2, 2, size - 2, size - 2], fill=(255, 255, 255, 255), outline=(245, 158, 11, 230), width=2)

            # 2. Track circular suave de fundo
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(226, 232, 240, 255), width=stroke_width)

            # 3. Arco de progresso no sentido horário iniciando às 12 horas (-90 graus)
            prog = i / float(total_frames)
            if prog > 0.003:
                end_angle = -90.0 + (prog * 360.0)
                draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=-90.0, end=end_angle, fill=(37, 99, 235, 255), width=stroke_width)

            img.save(frame_path, "PNG")

        logger.info(f"[TIMER] Gerados {total_frames} frames do indicador circular progressivo (30fps x {duration}s) em {timer_dir}")
        pattern = os.path.join(timer_dir, "timer_%03d.png").replace("\\", "/")
        return pattern, (size, size)

    # -------------------------------------------------------------------------
    # 6. Síntese de Voz Edge TTS
    # -------------------------------------------------------------------------
    async def synthesize_voice(self, text: str, output_path: str) -> float:
        """Gera áudio natural pt-BR via Edge TTS e retorna a duração factual."""
        import edge_tts
        v_name = self.config.voice_settings.get("voice_name", "pt-BR-AntonioNeural")
        v_rate = self.config.voice_settings.get("voice_rate", "+20%")

        # Validação estrita de cache por chave (voz + velocidade + texto exato)
        text_cache_path = output_path + ".key"
        cache_key = f"{v_name}|{v_rate}|{text.strip()}"
        if os.path.exists(output_path) and os.path.exists(text_cache_path) and os.path.getsize(output_path) > 1000:
            try:
                with open(text_cache_path, "r", encoding="utf-8") as f:
                    cached_key = f.read().strip()
                if cached_key == cache_key:
                    probe = probe_media(output_path)
                    dur = float(probe.get("format_duration", 0.0) or 0.0)
                    if dur > 0.1:
                        return dur
            except Exception:
                pass

        comm = edge_tts.Communicate(text=text, voice=v_name, rate=v_rate)
        await comm.save(output_path)
        try:
            with open(text_cache_path, "w", encoding="utf-8") as f:
                f.write(cache_key)
        except Exception:
            pass

        probe = probe_media(output_path)
        dur = float(probe.get("format_duration", 0.0) or 0.0)
        return dur

    # -------------------------------------------------------------------------
    # 7. Mixagem de Áudio de Cada Segmento
    # -------------------------------------------------------------------------
    def mix_scene_audio(
        self,
        narration_path: str,
        output_audio_path: str,
        total_duration: float,
        ticks_path: Optional[str] = None,
        ticks_start_time: float = 0.0,
        sfx_path: Optional[str] = None,
        sfx_start_time: float = 0.0,
    ) -> bool:
        """Combina narração, tique-taques da janela de expectativa e chime de acerto."""
        inputs = ["-i", os.path.abspath(narration_path)]
        filter_parts = [f"[0:a]volume=1.0,apad=whole_dur={total_duration:.3f}[voice]"]
        mix_inputs = ["[voice]"]
        input_idx = 1

        if ticks_path and os.path.exists(ticks_path):
            delay_ticks_ms = int(max(0.0, ticks_start_time) * 1000)
            inputs.extend(["-i", os.path.abspath(ticks_path)])
            filter_parts.append(f"[{input_idx}:a]volume=0.55,adelay={delay_ticks_ms}|{delay_ticks_ms}[ticks]")
            mix_inputs.append("[ticks]")
            input_idx += 1

        if sfx_path and os.path.exists(sfx_path):
            delay_sfx_ms = int(max(0.0, sfx_start_time) * 1000)
            inputs.extend(["-i", os.path.abspath(sfx_path)])
            filter_parts.append(f"[{input_idx}:a]volume=0.95,adelay={delay_sfx_ms}|{delay_sfx_ms}[sfx]")
            mix_inputs.append("[sfx]")
            input_idx += 1

        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        filter_complex = ";".join(filter_parts)

        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-t", f"{total_duration:.3f}",
            os.path.abspath(output_audio_path),
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0 and os.path.exists(output_audio_path)

    # -------------------------------------------------------------------------
    # 8. Renderização de Vídeo de Cada Segmento (FFmpeg com Ken Burns sutil)
    # -------------------------------------------------------------------------
    def render_question_video_scene(
        self,
        scene_id: str,
        img_options: str,
        img_revealed: str,
        audio_path: str,
        duration: float,
        t_thinking_start: float = 0.0,
        t_reveal_start: float = 6.0,
        timer_frames_pattern: Optional[str] = None,
        timer_x: int = 892,
        timer_y: int = 500,
    ) -> str:
        """Gera o vídeo do segmento da questão (P1.3):
        1. Pergunta e 4 alternativas visíveis desde o início da cena (t=0 -> t_reveal_start) com leve zoompan.
        2. Timer circular progressivo preenchendo no sentido horário (t_thinking_start -> t_reveal_start).
        3. Revelação da correta com círculo de caneta, destaque verde e chime (t_reveal_start -> duration).
        """
        fps = self.config.video_settings.get("fps", 30)
        total_frames = int(duration * fps) + 2
        output_scene_mp4 = os.path.join(self.config.temp_dir, f"scene_{scene_id}.mp4")

        inputs = [
            "-loop", "1", "-i", os.path.abspath(img_options),
            "-loop", "1", "-i", os.path.abspath(img_revealed),
            "-i", os.path.abspath(audio_path),
        ]

        if timer_frames_pattern:
            inputs.extend(["-framerate", str(fps), "-i", timer_frames_pattern])
            filter_complex = (
                f"[0:v]zoompan=z='min(zoom+0.0003,1.025)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[base_motion];"
                f"[1:v]zoompan=z='min(zoom+0.0003,1.025)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[rev_motion];"
                f"[3:v]setpts=PTS-STARTPTS+{t_thinking_start:.3f}/TB[timer_timed];"
                f"[base_motion][timer_timed]overlay={timer_x}:{timer_y}:enable='between(t,{t_thinking_start:.3f},{t_reveal_start:.3f})'[with_timer];"
                f"[with_timer][rev_motion]overlay=0:0:enable='gte(t,{t_reveal_start:.3f})'[vfinal]"
            )
        else:
            filter_complex = (
                f"[0:v]zoompan=z='min(zoom+0.0003,1.025)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[base_motion];"
                f"[1:v]zoompan=z='min(zoom+0.0003,1.025)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[rev_motion];"
                f"[base_motion][rev_motion]overlay=0:0:enable='gte(t,{t_reveal_start:.3f})'[vfinal]"
            )

        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-t", f"{duration:.3f}",
            output_scene_mp4,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"[RENDER] Falha na renderização de {scene_id}: {res.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg falhou ao renderizar {scene_id}")

        return output_scene_mp4

    def render_static_scene(self, scene_id: str, img_path: str, audio_path: str, duration: float) -> str:
        """Renderiza uma cena com imagem estática suave e leve movimento Ken Burns."""
        fps = self.config.video_settings.get("fps", 30)
        total_frames = int(duration * fps) + 2
        output_mp4 = os.path.join(self.config.temp_dir, f"scene_{scene_id}.mp4")

        filter_complex = (
            f"[0:v]zoompan=z='min(zoom+0.0004,1.02)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[vfinal]"
        )

        cmd = [
            self.ffmpeg_bin, "-y",
            "-loop", "1", "-i", os.path.abspath(img_path),
            "-i", os.path.abspath(audio_path),
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-t", f"{duration:.3f}",
            output_mp4,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"[RENDER] Falha na renderização estática de {scene_id}: {res.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg falhou ao renderizar estático {scene_id}")

        return output_mp4

    # -------------------------------------------------------------------------
    # 9. Concatenação e Mixagem da Trilha BGM
    # -------------------------------------------------------------------------
    def concat_and_mix_bgm(self, scene_files: List[str]) -> bool:
        """Concatena todas as cenas e mixa com a trilha de fundo, aplicando faststart."""
        concat_txt = os.path.join(self.config.temp_dir, "concat_list.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for sf in scene_files:
                clean_path = os.path.abspath(sf).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        staged_concat = os.path.join(self.config.temp_dir, "staged_concat.mp4")
        cmd_concat = [
            self.ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", os.path.abspath(concat_txt),
            "-c", "copy",
            staged_concat,
        ]
        res_c = subprocess.run(cmd_concat, capture_output=True, text=True)
        if res_c.returncode != 0 or not os.path.exists(staged_concat):
            logger.error(f"[CONCAT] Erro na concatenação: {res_c.stderr[-400:]}")
            return False

        probe = probe_media(staged_concat)
        total_dur = float(probe.get("format_duration", 0.0) or 68.0)

        # Mixagem com BGM (se fornecido e existente)
        bgm_path = self.config.video_settings.get("bgm_path", "")
        bgm_vol = float(self.config.video_settings.get("bgm_volume", 0.14))
        out_mp4 = self.config.output_video_path

        has_bgm = bool(bgm_path and os.path.isfile(str(bgm_path)) and os.path.getsize(str(bgm_path)) > 0)
        if has_bgm:
            fade_start = max(0.0, total_dur - 3.0)
            filter_complex = (
                f"[0:a]volume=1.0[voice];"
                f"[1:a]volume={bgm_vol:.2f},afade=t=out:st={fade_start:.2f}:d=3[music];"
                f"[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.98[aout]"
            )
            cmd_final = [
                self.ffmpeg_bin, "-y",
                "-i", os.path.abspath(staged_concat),
                "-stream_loop", "-1",
                "-i", os.path.abspath(str(bgm_path)),
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total_dur:.3f}",
                "-movflags", "+faststart",
                os.path.abspath(out_mp4),
            ]
        else:
            logger.info("[QUIZ_PAPER] Renderizando áudio sem BGM (bgm_path vazio ou inexistente)")
            cmd_final = [
                self.ffmpeg_bin, "-y",
                "-i", os.path.abspath(staged_concat),
                "-map", "0:v",
                "-map", "0:a",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total_dur:.3f}",
                "-movflags", "+faststart",
                os.path.abspath(out_mp4),
            ]

        res_f = subprocess.run(cmd_final, capture_output=True, text=True)
        return res_f.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 1000

    # -------------------------------------------------------------------------
    # 10. Seleção Dinâmica da Quantidade de Perguntas & Duration Gate
    # -------------------------------------------------------------------------
    async def select_questions_for_target_duration(
        self,
        candidate_questions: List[Dict[str, Any]],
        target_min: float = 60.0,
        target_max: float = 65.0,
        expectation_sec: float = 6.0,
        reveal_sec: float = 1.0,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Seleciona dinamicamente a quantidade de perguntas para situar a duração final
        estritamente entre target_min e target_max (60s a 65s), usando áudios reais de narração,
        sem cortes de fala e sem silêncio artificial.
        """
        import itertools

        # 1. Duração baseline (abertura + encerramento)
        dur_baseline = 0.0
        intro_cfg = self.config.intro_hook
        if intro_cfg.get("enabled", True):
            intro_audio = os.path.join(self.config.temp_dir, "narration_intro.mp3")
            dur_intro = await self.synthesize_voice(intro_cfg["narration"], intro_audio)
            dur_baseline += (dur_intro + 0.25)

        outro_cfg = self.config.outro_challenge
        if outro_cfg.get("enabled", True):
            dur_outro_tot = float(outro_cfg.get("duration_sec", 6.0))
            dur_baseline += dur_outro_tot

        # 2. Medir duração exata da narração de cada pergunta candidata
        candidates_with_dur: List[Tuple[Dict[str, Any], float, float]] = []
        for q in candidate_questions:
            q_audio = os.path.join(self.config.temp_dir, f"narration_{q['id']}.mp3")
            dur_narr = await self.synthesize_voice(q["narration"], q_audio)
            scene_dur = dur_narr + expectation_sec + reveal_sec
            candidates_with_dur.append((q, scene_dur, dur_narr))

        # 3. Busca de combinação ótima que caiba estritamente em [target_min, target_max]
        midpoint = (target_min + target_max) / 2.0
        valid_selections: List[Tuple[float, List[Dict[str, Any]], float]] = []

        for k in range(1, len(candidates_with_dur) + 1):
            for comb in itertools.combinations(candidates_with_dur, k):
                total_comb_dur = dur_baseline + sum(item[1] for item in comb)
                if target_min <= total_comb_dur <= target_max:
                    diff_to_mid = abs(total_comb_dur - midpoint)
                    valid_selections.append((diff_to_mid, [item[0] for item in comb], total_comb_dur))

        if valid_selections:
            # Ordena pela menor distância ao ponto médio (62.5s) para margem de segurança contra variações de muxing
            valid_selections.sort(key=lambda x: x[0])
            best_diff, best_questions, best_dur = valid_selections[0]
        else:
            # 4. Calibração dinâmica das pausas (expectativa e revelação) se nenhuma combinação fixa atingir a faixa
            num_target = min(5, len(candidates_with_dur)) if len(candidates_with_dur) >= 5 else len(candidates_with_dur)
            if num_target == 0:
                raise DurationGateError(
                    f"[DURATION GATE ERROR] Nenhuma pergunta candidata fornecida. Baseline: {dur_baseline:.2f}s."
                )

            chosen_candidates = candidates_with_dur[:num_target]
            total_voice = sum(item[2] for item in chosen_candidates)
            target_center = midpoint
            needed_pause_total = target_center - (dur_baseline + total_voice)
            pause_per_q = needed_pause_total / float(num_target)

            # Faixa aceitável de pausa por questão: 5.5s a 11.0s (timer de raciocínio de 5.0 a 8.5s + revelação de 1.0 a 2.5s)
            min_pause_per_q = 5.5
            max_pause_per_q = 11.0

            if not (min_pause_per_q <= pause_per_q <= max_pause_per_q):
                raise DurationGateError(
                    f"[DURATION GATE ERROR] Nenhuma seleção de perguntas atinge a faixa obrigatória de "
                    f"[{target_min:.1f}s, {target_max:.1f}s]. Baseline: {dur_baseline:.2f}s, "
                    f"voz={total_voice:.2f}s, pausa_necessária={pause_per_q:.2f}s/q (faixa permitida: [{min_pause_per_q:.1f}s, {max_pause_per_q:.1f}s])."
                )

            if pause_per_q >= 7.0:
                extra = pause_per_q - 7.0
                calibrated_exp = round(6.0 + (extra * 0.60), 2)
                calibrated_rev = round(pause_per_q - calibrated_exp, 2)
            else:
                calibrated_rev = 1.0
                calibrated_exp = round(pause_per_q - 1.0, 2)

            self.config.timing_settings["expectation_sec"] = calibrated_exp
            self.config.timing_settings["reveal_sec"] = calibrated_rev

            best_questions = [item[0] for item in chosen_candidates]
            best_dur = dur_baseline + total_voice + (num_target * (calibrated_exp + calibrated_rev))
            logger.info(
                f"[DYNAMIC CALIBRATION] {num_target} perguntas calibradas para duração alvo {best_dur:.2f}s: "
                f"voz={total_voice:.2f}s | exp_sec={calibrated_exp:.2f}s | rev_sec={calibrated_rev:.2f}s"
            )

        # Re-indexa os números das perguntas selecionadas
        formatted_questions: List[Dict[str, Any]] = []
        for idx, q in enumerate(best_questions, start=1):
            q_copy = dict(q)
            q_copy["number"] = idx
            q_copy["number_str"] = f"QUESTÃO {idx:02d} DE {len(best_questions):02d}"
            formatted_questions.append(q_copy)

        logger.info(
            f"[DYNAMIC SELECTION] Selecionadas {len(formatted_questions)} perguntas de {len(candidate_questions)} candidatas. "
            f"Duração estimada: {best_dur:.2f}s (Faixa Alvo: [{target_min:.1f}s, {target_max:.1f}s])"
        )
        return formatted_questions, best_dur

    # -------------------------------------------------------------------------
    # 11. Pipeline Completo de Renderização (P1.2)
    # -------------------------------------------------------------------------
    async def render_async(self) -> Dict[str, Any]:
        """Executa a renderização completa do protótipo P1.2 e valida o Duration Gate."""
        t_start = time.perf_counter()
        logger.info(f"=== INICIANDO RENDERIZAÇÃO P1.2: QUIZ FOLHA DE PAPEL ({self.config.quiz_title}) ===")

        exp_sec = float(self.config.timing_settings.get("expectation_sec", 6.0))
        rev_sec = float(self.config.timing_settings.get("reveal_sec", 1.0))
        t_min = float(self.config.min_target_duration_sec)
        t_max = float(getattr(self.config, "max_target_duration_sec", 65.0))

        # 1. Seleção Dinâmica da Quantidade de Perguntas baseada na duração real da narração
        selected_q, est_dur = await self.select_questions_for_target_duration(
            candidate_questions=self.config.questions,
            target_min=t_min,
            target_max=t_max,
            expectation_sec=exp_sec,
            reveal_sec=rev_sec,
        )
        self.config.questions = selected_q
        # Atualiza expectation_sec e reveal_sec após eventual calibração dinâmica
        exp_sec = float(self.config.timing_settings.get("expectation_sec", exp_sec))
        rev_sec = float(self.config.timing_settings.get("reveal_sec", rev_sec))

        # 2. Gerar Thumbnail
        self.generate_thumbnail()

        # 3. Gerar SFX de Acerto e Tique-taques da Janela de Expectativa (6.0s)
        sfx_ding = self.generate_correct_ding_sfx()
        sfx_ticks = self.generate_thinking_ticks_sfx(duration=exp_sec)

        # 4. Gerar Frames do Timer Circular Progressivo (6.0s a 30fps = 180 frames)
        timer_pattern, _ = self.generate_circular_timer_frames(duration=exp_sec, fps=self.config.video_settings.get("fps", 30))

        scene_files: List[str] = []
        timing_records: List[Dict[str, Any]] = []

        # 5. Renderizar Cena de Abertura (Intro Hook - Direta e Dinâmica)
        intro_cfg = self.config.intro_hook
        if intro_cfg.get("enabled", True):
            intro_img = os.path.join(self.config.temp_dir, "frame_intro.png")
            self.render_intro_frame().save(intro_img, "PNG")

            intro_audio = os.path.join(self.config.temp_dir, "narration_intro.mp3")
            dur_intro = await self.synthesize_voice(intro_cfg["narration"], intro_audio)
            dur_intro_tot = dur_intro + 0.25  # Corte ágil

            intro_scene_audio = os.path.join(self.config.temp_dir, "audio_intro.mp4")
            self.mix_scene_audio(intro_audio, intro_scene_audio, dur_intro_tot)

            intro_mp4 = self.render_static_scene("intro", intro_img, intro_scene_audio, dur_intro_tot)
            scene_files.append(intro_mp4)
            timing_records.append({"scene": "intro", "duration": round(dur_intro_tot, 3)})

        # 6. Renderizar Perguntas Selecionadas Dinamicamente com Timer Circular Progressivo
        for idx, item in enumerate(self.config.questions):
            scene_id = item["id"]
            logger.info(f"Processando questão {scene_id} ({idx + 1}/{len(self.config.questions)})...")

            # Pergunta e as 4 alternativas visíveis desde o início da cena (frame 0)
            img_options = os.path.join(self.config.temp_dir, f"frame_{scene_id}_options.png")
            img_rev = os.path.join(self.config.temp_dir, f"frame_{scene_id}_revealed.png")

            self.render_question_frame(item, state="options").save(img_options, "PNG")
            self.render_question_frame(item, state="revealed").save(img_rev, "PNG")

            # Síntese da Narração (SOMENTE a pergunta!)
            audio_narr = os.path.join(self.config.temp_dir, f"narration_{scene_id}.mp3")
            dur_narr = await self.synthesize_voice(item["narration"], audio_narr)

            # Sequência Temporal P1.3:
            # 0.0 -> dur_narr: Pergunta narrada com alternativas já presentes na folha
            # dur_narr -> t_reveal_start: Janela de raciocínio de 6.0s com timer circular progressivo e tique-taques
            # t_reveal_start -> tot_dur: Resposta correta revelada por ~1.0s com chime de acerto (timer removido)
            t_thinking_start = dur_narr
            t_reveal_start = t_thinking_start + exp_sec
            tot_dur = t_reveal_start + rev_sec

            audio_scene = os.path.join(self.config.temp_dir, f"audio_{scene_id}.mp4")
            self.mix_scene_audio(
                narration_path=audio_narr,
                output_audio_path=audio_scene,
                total_duration=tot_dur,
                ticks_path=sfx_ticks,
                ticks_start_time=t_thinking_start,
                sfx_path=sfx_ding,
                sfx_start_time=t_reveal_start,
            )

            timer_x, timer_y = self.get_question_timer_position(item["question"])

            q_mp4 = self.render_question_video_scene(
                scene_id=scene_id,
                img_options=img_options,
                img_revealed=img_rev,
                audio_path=audio_scene,
                duration=tot_dur,
                t_thinking_start=t_thinking_start,
                t_reveal_start=t_reveal_start,
                timer_frames_pattern=timer_pattern,
                timer_x=timer_x,
                timer_y=timer_y,
            )
            scene_files.append(q_mp4)
            timing_records.append({
                "scene": scene_id,
                "narration_sec": round(dur_narr, 3),
                "thinking_start_sec": round(t_thinking_start, 3),
                "thinking_sec": round(exp_sec, 3),
                "reveal_start_sec": round(t_reveal_start, 3),
                "reveal_sec": round(rev_sec, 3),
                "total_duration": round(tot_dur, 3),
                "timer_circular": {
                    "enabled": True,
                    "sweep_deg": 360.0,
                    "pos_x": timer_x,
                    "pos_y": timer_y,
                },
            })

        # 7. Renderizar Cena de Encerramento (Outro Challenge mantida por 6.0s completos)
        outro_cfg = self.config.outro_challenge
        if outro_cfg.get("enabled", True):
            outro_img = os.path.join(self.config.temp_dir, "frame_outro.png")
            self.render_outro_frame().save(outro_img, "PNG")

            dur_outro_tot = float(outro_cfg.get("duration_sec", 6.0))
            outro_audio = os.path.join(self.config.temp_dir, "narration_outro.mp3")
            dur_outro_speech = await self.synthesize_voice(outro_cfg["narration"], outro_audio)

            outro_scene_audio = os.path.join(self.config.temp_dir, "audio_outro.mp4")
            self.mix_scene_audio(outro_audio, outro_scene_audio, dur_outro_tot)

            outro_mp4 = self.render_static_scene("outro", outro_img, outro_scene_audio, dur_outro_tot)
            scene_files.append(outro_mp4)
            timing_records.append({
                "scene": "outro",
                "narration_sec": round(dur_outro_speech, 3),
                "duration": dur_outro_tot,
                "hold_comment_sec": round(dur_outro_tot - dur_outro_speech, 3),
            })

        # 8. Concatenação e Mixagem Final
        logger.info(f"Concatenando {len(scene_files)} segmentos com trilha ambiente...")
        ok_concat = self.concat_and_mix_bgm(scene_files)
        if not ok_concat:
            raise RuntimeError("Falha na concatenação e mixagem final do vídeo.")

        t_elapsed = time.perf_counter() - t_start
        probe = probe_media(self.config.output_video_path)
        final_dur = float(probe.get("format_duration", 0.0) or 0.0)

        # 9. Verificação Rigorosa do Duration Gate [target_min, target_max]
        gate_passed = (t_min <= final_dur <= t_max)
        if not gate_passed:
            raise DurationGateError(
                f"[DURATION GATE VIOLATION] Duração final {final_dur:.2f}s está fora da faixa obrigatória "
                f"[{t_min:.1f}s, {t_max:.1f}s]!"
            )

        # 10. Gravação de Metadados JSON no Diretório do Protótipo
        meta_path = os.path.join(os.path.dirname(self.config.output_video_path), "metadata.json")
        metadata = {
            "format": "quiz_paper_prototype",
            "prototype_code": "P1.3",
            "quiz_title": self.config.quiz_title,
            "niche": self.config.niche,
            "video_path": self.config.output_video_path,
            "thumbnail_path": self.config.output_thumbnail_path,
            "num_questions": len(self.config.questions),
            "video_duration_sec": final_dur,
            "render_time_sec": round(t_elapsed, 2),
            "meets_min_target_duration": final_dur >= self.config.min_target_duration_sec,
            "duration_gate": {
                "target_min_sec": t_min,
                "target_max_sec": t_max,
                "passed": gate_passed,
                "margin_min_sec": round(final_dur - t_min, 3),
                "margin_max_sec": round(t_max - final_dur, 3),
            },
            "features_p1_3": {
                "timer_circular": "6.0s progressive clockwise ring synchronized with ticks (180 frames at 30fps)",
                "closing_hold_duration_sec": dur_outro_tot,
                "closing_cta_text": "Quantas você acertou? Comente sua pontuação!",
            },
            "factual_sources": [
                {"id": q["id"], "question": q["question"], "answer": q["correct_option"], "source": q.get("source")}
                for q in self.config.questions
            ],
            "timings": timing_records,
            "video_stream": probe.get("video_stream", {}),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(
            f"=== PROTÓTIPO P1.3 CONCLUÍDO COM SUCESSO! Duração: {final_dur:.2f}s (Faixa: [{t_min}s, {t_max}s]) "
            f"| Perguntas: {len(self.config.questions)} | Tempo de Render: {t_elapsed:.2f}s ==="
        )
        return metadata

    def render(self) -> Dict[str, Any]:
        """Wrapper síncrono para render_async."""
        return asyncio.run(self.render_async())

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> List[str]:
        """Divide o texto em linhas de largura máxima garantida."""
        dummy_img = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(dummy_img)

        words = text.split()
        lines: List[str] = []
        cur_line = ""

        for word in words:
            candidate = f"{cur_line} {word}".strip() if cur_line else word
            if d.textlength(candidate, font=font) <= max_width:
                cur_line = candidate
            else:
                if cur_line:
                    lines.append(cur_line)
                cur_line = word
        if cur_line:
            lines.append(cur_line)

        return lines


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Renderiza protótipo de Quiz no formato Folha de Papel (P1.1)")
    parser.add_argument(
        "--config",
        default="resource/quiz_templates/quiz_template_perguntas_respostas_papel.json",
        help="Caminho do arquivo de configuração JSON",
    )
    args = parser.parse_args()

    cfg_path = _resolve_path(args.config)
    if not os.path.exists(cfg_path):
        logger.error(f"Configuração não encontrada: {cfg_path}")
        sys.exit(1)

    config = PaperQuizConfig.from_json(cfg_path)
    engine = PaperQuizEngine(config)
    meta = engine.render()

    print("\n" + "=" * 60)
    print("RELATÓRIO DO PROTÓTIPO P1.1:")
    print(f"Vídeo MP4:   {meta['video_path']}")
    print(f"Thumbnail:   {meta['thumbnail_path']}")
    print(f"Duração:     {meta['video_duration_sec']:.2f}s (Min > 60s: {meta['meets_min_target_duration']})")
    print(f"Questões:    {meta['num_questions']}")
    print(f"Tempo total: {meta['render_time_sec']:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
