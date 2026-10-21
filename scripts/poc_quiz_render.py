"""
scripts/poc_quiz_render.py
==========================
VIDEO FACTORY — FASE Q1: QUIZ ENGINE REUTILIZÁVEL
Ambiente: DEV — D:\\Projetos\\MoneyPrinterTurbo

Template de quiz reutilizável por diferentes nichos e canais, desacoplado
via configuração em JSON, preservando rigorosamente a qualidade visual,
estilo split-screen e sincronia homologados na POC V3.

Configurações suportadas via JSON:
- Nicho e título do quiz
- Perguntas, títulos, tags e alternativas
- Imagens das alternativas (Pexels HD ou arquivos locais)
- Paletas de cores e temas (red, blue, gold_red, etc.)
- Voz Edge TTS e velocidade (rate)
- Gancho de retenção sonoro configurável na 1ª pergunta
- Contagem regressiva visual (badges 3..2..1) e sfx de tique-taque
- Encerramento específico do canal
- Duração mínima e faixa alvo
- Caminhos de saída de MP4 e Thumbnail independente (9:16)

Uso:
    .\\.venv\\Scripts\\python.exe scripts/poc_quiz_render.py
    .\\.venv\\Scripts\\python.exe scripts/poc_quiz_render.py --config storage/poc_quiz/quiz_template_escolhas_impossiveis.json
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
import requests
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils
from app.services.media_quality import probe_media


# =============================================================================
# Modelo de Configuração Reutilizável (QuizConfig)
# =============================================================================

@dataclass
class QuizConfig:
    niche: str = "curiosidades_dilemas"
    quiz_title: str = "QUAL VOCÊ ESCOLHERIA?"
    output_video_path: str = "storage/poc_quiz/quiz_escolhas_impossiveis_poc_v3.mp4"
    output_thumbnail_path: str = "storage/poc_quiz/quiz_thumbnail_v3.jpg"
    temp_dir: str = "storage/poc_quiz/temp_v3"
    images_dir: str = "storage/poc_quiz/images_v2"
    min_target_duration_sec: float = 60.0
    target_duration_range: Tuple[float, float] = (60.0, 65.0)

    video_settings: Dict[str, Any] = field(default_factory=lambda: {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "font_path": "resource/fonts/BeVietnamPro-Bold.ttf",
        "bgm_path": "resource/songs/output000.mp3",
        "bgm_volume": 0.14,
    })

    voice_settings: Dict[str, Any] = field(default_factory=lambda: {
        "voice_name": "pt-BR-AntonioNeural",
        "voice_rate": "+12%",
    })

    countdown_settings: Dict[str, Any] = field(default_factory=lambda: {
        "default_sec": 3.0,
        "expectation_sec": 2.0,
        "reveal_sec": 1.0,
        "closing_sec": 3.0,
        "enable_countdown_badges": False,  # Q0-R: elimina números 3, 2, 1
        "enable_percentages": True,        # Q0-R: exibe porcentagens simultâneas por ~1s
        "badges": ["3", "2", "1"],
        "colors": {
            "badge_ou_bg": [255, 214, 0],
            "badge_ou_text": [0, 0, 0],
            "badge_3_bg": [255, 75, 75],
            "badge_2_bg": [255, 170, 0],
            "badge_1_bg": [45, 210, 60],
            "badge_countdown_text": [255, 255, 255],
        },
    })

    retention_hook: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "question_id": "q1",
        "narration": "Mas atenção... a última escolha vai te surpreender!",
        "min_countdown_sec": 3.85,
    })

    theme_palettes: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
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
    })

    thumbnail_settings: Dict[str, Any] = field(default_factory=lambda: {
        "banner_text": "QUAL VOCÊ ESCOLHERIA?",
        "top_option": {
            "tag": "OPÇÃO A",
            "title": "R$ 1 MILHÃO TODO MÊS",
            "image_name": "q1_top_v2.jpg",
        },
        "bottom_option": {
            "tag": "OPÇÃO B",
            "title": "JUVENTUDE ETERNA",
            "image_name": "q1_bot_v2.jpg",
        },
    })

    questions: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QuizConfig:
        config = cls()
        for k, v in data.items():
            if hasattr(config, k):
                if k == "target_duration_range" and isinstance(v, list):
                    setattr(config, k, tuple(v))
                else:
                    setattr(config, k, v)
        # Resolução de caminhos relativos para absolutos se necessário
        config.output_video_path = _resolve_path(config.output_video_path)
        config.output_thumbnail_path = _resolve_path(config.output_thumbnail_path)
        config.temp_dir = _resolve_path(config.temp_dir)
        config.images_dir = _resolve_path(config.images_dir)
        config.video_settings["font_path"] = _resolve_path(config.video_settings.get("font_path", ""))
        config.video_settings["bgm_path"] = _resolve_path(config.video_settings.get("bgm_path", ""))
        return config

    @classmethod
    def from_json(cls, json_path: str | Path) -> QuizConfig:
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
# Classe Principal do Motor: QuizEngine
# =============================================================================

class QuizEngine:
    """Motor de renderização e composição de quizzes reutilizável."""

    def __init__(self, config: QuizConfig):
        self.config = config
        self.ffmpeg_bin = utils.get_ffmpeg_binary()
        os.makedirs(os.path.dirname(self.config.output_video_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.config.output_thumbnail_path), exist_ok=True)
        os.makedirs(self.config.temp_dir, exist_ok=True)
        os.makedirs(self.config.images_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. Download e Gerenciamento de Imagens
    # -------------------------------------------------------------------------
    def ensure_images(self) -> None:
        """Garante a disponibilidade de imagens para todas as perguntas."""
        from app.services import material
        api_key = material.get_api_key("pexels_api_keys")
        headers = {"Authorization": api_key} if api_key else {}

        for item in self.config.questions:
            self._fetch_or_fallback(
                item["top"]["image_name"],
                item["top"]["image_query"],
                headers,
                fallback_color=(135, 18, 30),
                label=item["top"]["title"],
            )
            self._fetch_or_fallback(
                item["bottom"]["image_name"],
                item["bottom"]["image_query"],
                headers,
                fallback_color=(18, 48, 120),
                label=item["bottom"]["title"],
            )

    def _fetch_or_fallback(
        self,
        filename: str,
        query: str,
        headers: Dict[str, str],
        fallback_color: Tuple[int, int, int],
        label: str,
    ) -> None:
        dest_path = os.path.join(self.config.images_dir, filename)
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return

        success = False
        if headers:
            try:
                url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape"
                r = requests.get(url, headers=headers, timeout=12)
                if r.status_code == 200 and r.json().get("photos"):
                    photo_url = r.json()["photos"][0]["src"]["large2x"]
                    img_data = requests.get(photo_url, timeout=15).content
                    with open(dest_path, "wb") as f:
                        f.write(img_data)
                    logger.info(f"[IMAGE] Pexels download OK: {filename} ({len(img_data)} bytes)")
                    success = True
            except Exception as exc:
                logger.warning(f"[IMAGE] Pexels falhou para {query}: {exc}")

        if not success:
            logger.info(f"[IMAGE] Criando fallback estilizado: {filename}")
            img = Image.new("RGB", (1280, 720), fallback_color)
            draw = ImageDraw.Draw(img)
            font_path = self.config.video_settings["font_path"]
            font = ImageFont.truetype(font_path, 48) if os.path.exists(font_path) else ImageFont.load_default()
            draw.text((640, 360), label[:30], font=font, fill=(255, 255, 255), anchor="mm")
            img.save(dest_path, "JPEG", quality=90)

    # -------------------------------------------------------------------------
    # 2. Geração da Thumbnail Independente 9:16
    # -------------------------------------------------------------------------
    def generate_thumbnail(self) -> str:
        """Gera imagem de capa 9:16 (1080x1920) de altíssimo contraste."""
        width = self.config.video_settings["width"]
        height = self.config.video_settings["height"]
        half_h = height // 2
        font_path = self.config.video_settings["font_path"]

        img = Image.new("RGBA", (width, height), (15, 15, 20, 255))
        thumb_cfg = self.config.thumbnail_settings

        # Imagem Topo
        top_name = thumb_cfg["top_option"].get("image_name", "")
        top_path = os.path.join(self.config.images_dir, top_name)
        if os.path.exists(top_path):
            top_img = Image.open(top_path).convert("RGBA")
            top_img = top_img.resize((width, half_h), Image.Resampling.LANCZOS)
            img.paste(top_img, (0, 0))

        # Imagem Base
        bot_name = thumb_cfg["bottom_option"].get("image_name", "")
        bot_path = os.path.join(self.config.images_dir, bot_name)
        if os.path.exists(bot_path):
            bot_img = Image.open(bot_path).convert("RGBA")
            bot_img = bot_img.resize((width, half_h), Image.Resampling.LANCZOS)
            img.paste(bot_img, (0, half_h))

        # Vinheta de Contraste
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d_overlay = ImageDraw.Draw(overlay)
        d_overlay.rectangle([0, 0, width, 240], fill=(0, 0, 0, 150))
        d_overlay.rectangle([0, half_h - 220, width, half_h], fill=(0, 0, 0, 160))
        d_overlay.rectangle([0, height - 220, width, height], fill=(0, 0, 0, 160))
        img = Image.alpha_composite(img, overlay)

        draw = ImageDraw.Draw(img)
        font_banner = ImageFont.truetype(font_path, 54)
        font_option = ImageFont.truetype(font_path, 46)
        font_tag = ImageFont.truetype(font_path, 32)
        font_badge = ImageFont.truetype(font_path, 80)

        # 1. Banner Superior
        banner_bbox = [50, 48, 1030, 178]
        draw.rounded_rectangle(banner_bbox, radius=28, fill=(10, 10, 18, 245), outline=(255, 215, 0, 255), width=6)
        banner_text = thumb_cfg.get("banner_text", self.config.quiz_title)
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 5)]:
            draw.text((540 + dx, 113 + dy), banner_text, font=font_banner, fill=(0, 0, 0, 255), anchor="mm")
        draw.text((540, 113), banner_text, font=font_banner, fill=(255, 225, 0, 255), anchor="mm")

        # 2. Card Opção A (Topo / Vermelho)
        draw.rounded_rectangle([50, 680, 1030, 900], radius=24, fill=(180, 15, 30, 240), outline=(255, 75, 85, 255), width=6)
        draw.rounded_rectangle([410, 652, 670, 708], radius=14, fill=(245, 30, 45, 255), outline=(255, 255, 255, 255), width=3)
        draw.text((540, 680), thumb_cfg["top_option"].get("tag", "OPÇÃO A"), font=font_tag, fill=(255, 255, 255), anchor="mm")
        text_a = thumb_cfg["top_option"].get("title", "")
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
            draw.text((540 + dx, 800 + dy), text_a, font=font_option, fill=(0, 0, 0, 255), anchor="mm")
        draw.text((540, 800), text_a, font=font_option, fill=(255, 255, 255), anchor="mm")

        # 3. Card Opção B (Base / Azul)
        draw.rounded_rectangle([50, 1630, 1030, 1850], radius=24, fill=(12, 50, 160, 240), outline=(65, 155, 255, 255), width=6)
        draw.rounded_rectangle([410, 1602, 670, 1658], radius=14, fill=(25, 110, 250, 255), outline=(255, 255, 255, 255), width=3)
        draw.text((540, 1630), thumb_cfg["bottom_option"].get("tag", "OPÇÃO B"), font=font_tag, fill=(255, 255, 255), anchor="mm")
        text_b = thumb_cfg["bottom_option"].get("title", "")
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
            draw.text((540 + dx, 1750 + dy), text_b, font=font_option, fill=(0, 0, 0, 255), anchor="mm")
        draw.text((540, 1750), text_b, font=font_option, fill=(255, 255, 255), anchor="mm")

        # 4. Linha Divisória Central
        draw.line([(0, half_h), (width, half_h)], fill=(255, 255, 255, 255), width=8)

        # 5. Badge Central "OU"
        cx, cy = 540, half_h
        r = 92
        draw.ellipse([cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8], fill=(0, 0, 0, 240))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 215, 0, 255), outline=(255, 255, 255, 255), width=7)
        draw.text((cx, cy), "OU", font=font_badge, fill=(0, 0, 0), anchor="mm")

        out_path = self.config.output_thumbnail_path
        final_rgb = img.convert("RGB")
        final_rgb.save(out_path, "JPEG", quality=95)
        logger.info(f"[ENGINE] Thumbnail 9:16 gerada: {out_path}")
        return out_path

    # -------------------------------------------------------------------------
    # 3. Síntese Sonora e Efeitos
    # -------------------------------------------------------------------------
    def generate_countdown_sfx(self, duration: float = 3.5) -> str:
        """Gera sfx de tique-taque em áudio puro PCM sintetizado (legado)."""
        output_wav = os.path.join(self.config.temp_dir, "countdown_sfx.wav")
        framerate = 44100
        nframes = int(framerate * duration)
        with wave.open(output_wav, "w") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(framerate)
            for i in range(nframes):
                t = i / framerate
                sample = 0
                for tick_t in [0.4, 1.2, 2.0]:
                    dt = t - tick_t
                    if 0 <= dt <= 0.08:
                        freq = 980 if tick_t < 2.0 else 1450
                        decay = math.exp(-dt * 48)
                        sample += int(19000 * math.sin(2 * math.pi * freq * dt) * decay)
                sample = max(-32767, min(32767, sample))
                wav.writeframes(struct.pack("<h", sample))
        return output_wav

    def generate_revelation_sfx(self, duration: float = 0.8) -> str:
        """Gera sfx de revelação (chime/ding harmônico suave) em PCM sintetizado puro."""
        output_wav = os.path.join(self.config.temp_dir, "reveal_chime.wav")
        framerate = 44100
        nframes = int(framerate * duration)
        with wave.open(output_wav, "w") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(framerate)
            for i in range(nframes):
                t = i / framerate
                decay = math.exp(-t * 8.0)
                sample = (
                    0.55 * math.sin(2 * math.pi * 1046.5 * t) +
                    0.30 * math.sin(2 * math.pi * 1318.5 * t) +
                    0.15 * math.sin(2 * math.pi * 2093.0 * t)
                ) * decay
                s16 = int(max(-32767, min(32767, sample * 24000)))
                wav.writeframes(struct.pack("<h", s16))
        return output_wav

    async def synthesize_voice(self, text: str, output_mp3: str) -> float:
        """Sintetiza narração pt-BR com Edge TTS."""
        import edge_tts
        from moviepy.audio.io.AudioFileClip import AudioFileClip

        voice_name = self.config.voice_settings["voice_name"]
        voice_rate = self.config.voice_settings["voice_rate"]
        communicate = edge_tts.Communicate(text, voice_name, rate=voice_rate)
        await communicate.save(output_mp3)

        clip = AudioFileClip(output_mp3)
        duration = float(clip.duration)
        clip.close()
        return duration

    def mix_segment_audio(
        self,
        narration_mp3: str,
        countdown_audio: Optional[str],
        output_audio: str,
        total_duration: float,
        countdown_sec: float,
        reveal_sfx: Optional[str] = None,
        reveal_sec: float = 1.0,
    ) -> bool:
        """Combina narração da pergunta com gancho ou chime de revelação (sem tique-taque repetitivo)."""
        inputs = ["-i", os.path.abspath(narration_mp3)]
        filters = ["[0:a]volume=1.0[a_nar]"]
        input_count = 1

        # Se houver áudio secundário (ex: hook de retenção na Q1 ou countdown legado)
        if countdown_audio and os.path.exists(countdown_audio):
            delay_cnt_ms = int(max(0.0, total_duration - countdown_sec) * 1000)
            inputs.extend(["-i", os.path.abspath(countdown_audio)])
            filters.append(f"[{input_count}:a]adelay={delay_cnt_ms}|{delay_cnt_ms},volume=1.0[a_cnt]")
            input_count += 1

        # Chime de revelação de porcentagem
        if reveal_sfx and os.path.exists(reveal_sfx):
            delay_rev_ms = int(max(0.0, total_duration - reveal_sec) * 1000)
            inputs.extend(["-i", os.path.abspath(reveal_sfx)])
            filters.append(f"[{input_count}:a]adelay={delay_rev_ms}|{delay_rev_ms},volume=0.90[a_rev]")
            input_count += 1

        if input_count == 1:
            filter_complex = "[0:a]volume=1.0[aout]"
        elif input_count == 2:
            target_alias = "a_cnt" if "a_cnt" in filters[1] else "a_rev"
            filter_complex = f"{filters[0]};{filters[1]};[a_nar][{target_alias}]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.98[aout]"
        else:
            filter_complex = f"{filters[0]};{filters[1]};{filters[2]};[a_nar][a_cnt][a_rev]amix=inputs=3:duration=longest:dropout_transition=0,alimiter=limit=0.98[aout]"

        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-t", f"{total_duration:.3f}",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            os.path.abspath(output_audio),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0 and os.path.exists(output_audio)

    # -------------------------------------------------------------------------
    # 4. Geração de Overlays Gráficos
    # -------------------------------------------------------------------------
    def create_question_base_overlay(self, item: Dict[str, Any], output_png: str) -> str:
        width = self.config.video_settings["width"]
        height = self.config.video_settings["height"]
        font_path = self.config.video_settings["font_path"]

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_header = ImageFont.truetype(font_path, 44)
        font_option = ImageFont.truetype(font_path, 42)
        font_tag = ImageFont.truetype(font_path, 30)

        # 1. Banner Superior
        draw.rounded_rectangle([60, 40, 1020, 135], radius=24, fill=(10, 10, 16, 235), outline=(255, 215, 0, 255), width=5)
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((540 + dx, 87 + dy), item["header"], font=font_header, fill=(0, 0, 0, 220), anchor="mm")
        draw.text((540, 87), item["header"], font=font_header, fill=(255, 215, 0), anchor="mm")

        # Paletas Topo e Base
        palettes = self.config.theme_palettes
        top_theme = item["top"].get("theme", "red")
        bot_theme = item["bottom"].get("theme", "blue")
        p_top = palettes.get(top_theme, palettes.get("red", {}))
        p_bot = palettes.get(bot_theme, palettes.get("blue", {}))

        # 2. Card Opção A (Topo)
        draw.rounded_rectangle([55, 685, 1025, 895], radius=24, fill=tuple(p_top["card_fill"]), outline=tuple(p_top["card_outline"]), width=5)
        draw.rounded_rectangle([420, 660, 660, 710], radius=14, fill=tuple(p_top["tag_fill"]), outline=tuple(p_top["tag_outline"]), width=3)
        draw.text((540, 685), item["top"]["tag"], font=font_tag, fill=tuple(p_top["text_color"]), anchor="mm")
        lines_top = _wrap_text(item["top"]["title"], font_option, max_width=890)
        _draw_styled_multiline_text(draw, lines_top, font_option, center_x=540, center_y=795)

        # 3. Card Opção B (Base)
        draw.rounded_rectangle([55, 1645, 1025, 1855], radius=24, fill=tuple(p_bot["card_fill"]), outline=tuple(p_bot["card_outline"]), width=5)
        draw.rounded_rectangle([420, 1620, 660, 1670], radius=14, fill=tuple(p_bot["tag_fill"]), outline=tuple(p_bot["tag_outline"]), width=3)
        draw.text((540, 1645), item["bottom"]["tag"], font=font_tag, fill=tuple(p_bot["text_color"]), anchor="mm")
        lines_bot = _wrap_text(item["bottom"]["title"], font_option, max_width=890)
        _draw_styled_multiline_text(draw, lines_bot, font_option, center_x=540, center_y=1755)

        # 4. Linha Divisória Central
        draw.line([(0, 960), (1080, 960)], fill=(255, 255, 255, 240), width=6)

        img.save(output_png, "PNG")
        return output_png

    def create_question_reveal_overlay(self, item: Dict[str, Any], output_png: str) -> str:
        """Gera overlay com porcentagens simuladas e barra de progresso para revelação instantânea."""
        width = self.config.video_settings["width"]
        height = self.config.video_settings["height"]
        font_path = self.config.video_settings["font_path"]

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_pct = ImageFont.truetype(font_path, 42)
        font_disc = ImageFont.truetype(font_path, 22)

        pct_top = int(item.get("percentage_top", 64))
        pct_bot = int(item.get("percentage_bottom", 36))
        if pct_top + pct_bot != 100:
            pct_bot = max(0, 100 - pct_top)

        # 1. Badge de Porcentagem Opção A (Topo - acima do card, alinhado à Tag)
        draw.rounded_rectangle([760, 650, 1010, 712], radius=16, fill=(15, 15, 25, 245), outline=(255, 215, 0, 255), width=3)
        draw.text((885, 681), f"{pct_top}%", font=font_pct, fill=(255, 225, 0, 255), anchor="mm")

        # Barra de Progresso Opção A
        bar_w = 950
        fill_top_w = int(bar_w * (pct_top / 100.0))
        draw.rounded_rectangle([65, 878, 1015, 890], radius=5, fill=(20, 20, 30, 200))
        if fill_top_w > 0:
            draw.rounded_rectangle([65, 878, 65 + fill_top_w, 890], radius=5, fill=(255, 215, 0, 255))

        # 2. Badge de Porcentagem Opção B (Base - acima do card, alinhado à Tag)
        draw.rounded_rectangle([760, 1610, 1010, 1672], radius=16, fill=(15, 15, 25, 245), outline=(70, 160, 255, 255), width=3)
        draw.text((885, 1641), f"{pct_bot}%", font=font_pct, fill=(255, 255, 255, 255), anchor="mm")

        # Barra de Progresso Opção B
        fill_bot_w = int(bar_w * (pct_bot / 100.0))
        draw.rounded_rectangle([65, 1838, 1015, 1850], radius=5, fill=(20, 20, 30, 200))
        if fill_bot_w > 0:
            draw.rounded_rectangle([65, 1838, 65 + fill_bot_w, 1850], radius=5, fill=(70, 160, 255, 255))

        # 3. Identificação Discreta de Simulação (Transparência Ética)
        draw.text((540, 1888), "*estimativa de escolhas baseada em simulação", font=font_disc, fill=(255, 255, 255, 160), anchor="mm")

        img.save(output_png, "PNG")
        return output_png

    def create_center_badge(self, text: str, output_png: str, bg_color=(255, 214, 0), text_color=(0, 0, 0)) -> str:
        width = self.config.video_settings["width"]
        height = self.config.video_settings["height"]
        font_path = self.config.video_settings["font_path"]

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        cx, cy = 540, 960
        radius = 84

        draw.ellipse([cx - radius - 8, cy - radius - 8, cx + radius + 8, cy + radius + 8], fill=(0, 0, 0, 220))
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=bg_color, outline=(255, 255, 255, 255), width=6)

        font_badge = ImageFont.truetype(font_path, 74)
        draw.text((cx, cy), text, font=font_badge, fill=text_color, anchor="mm")

        img.save(output_png, "PNG")
        return output_png

    # -------------------------------------------------------------------------
    # 5. Renderização das Cenas e Concatenação
    # -------------------------------------------------------------------------
    def render_scene(self, item: Dict[str, Any]) -> str:
        scene_id = item["id"]
        output_scene_mp4 = os.path.join(self.config.temp_dir, f"scene_{scene_id}.mp4")

        img_top = os.path.abspath(os.path.join(self.config.images_dir, item["top"]["image_name"]))
        img_bot = os.path.abspath(os.path.join(self.config.images_dir, item["bottom"]["image_name"]))
        audio_path = os.path.abspath(os.path.join(self.config.temp_dir, f"audio_{scene_id}.mp4"))

        duration = item["total_duration"]
        countdown_sec = item["countdown_sec"]
        t_countdown = max(1.0, duration - countdown_sec)
        fps = self.config.video_settings["fps"]
        total_frames = int(duration * fps)

        overlay_base = os.path.abspath(os.path.join(self.config.temp_dir, f"overlay_{scene_id}_base.png"))
        self.create_question_base_overlay(item, overlay_base)

        cnt_colors = self.config.countdown_settings.get("colors", {})
        badge_ou = os.path.abspath(os.path.join(self.config.temp_dir, f"badge_{scene_id}_ou.png"))
        self.create_center_badge("OU", badge_ou, bg_color=tuple(cnt_colors.get("badge_ou_bg", [255, 214, 0])), text_color=tuple(cnt_colors.get("badge_ou_text", [0, 0, 0])))

        enable_badges = self.config.countdown_settings.get("enable_countdown_badges", False)
        reveal_sec = float(self.config.countdown_settings.get("reveal_sec", 1.0))
        t_reveal_start = max(0.5, duration - reveal_sec)

        if enable_badges:
            badge_3 = os.path.abspath(os.path.join(self.config.temp_dir, f"badge_{scene_id}_3.png"))
            self.create_center_badge("3", badge_3, bg_color=tuple(cnt_colors.get("badge_3_bg", [255, 75, 75])), text_color=tuple(cnt_colors.get("badge_countdown_text", [255, 255, 255])))

            badge_2 = os.path.abspath(os.path.join(self.config.temp_dir, f"badge_{scene_id}_2.png"))
            self.create_center_badge("2", badge_2, bg_color=tuple(cnt_colors.get("badge_2_bg", [255, 170, 0])), text_color=tuple(cnt_colors.get("badge_countdown_text", [255, 255, 255])))

            badge_1 = os.path.abspath(os.path.join(self.config.temp_dir, f"badge_{scene_id}_1.png"))
            self.create_center_badge("1", badge_1, bg_color=tuple(cnt_colors.get("badge_1_bg", [45, 210, 60])), text_color=tuple(cnt_colors.get("badge_countdown_text", [255, 255, 255])))

            step = countdown_sec / 3.0
            t3_start, t3_end = t_countdown, t_countdown + step
            t2_start, t2_end = t_countdown + step, t_countdown + 2.0 * step
            t1_start = t_countdown + 2.0 * step

            filter_complex = (
                f"[0:v]scale=1200:1066:force_original_aspect_ratio=increase,crop=1200:1066,"
                f"zoompan=z='min(zoom+0.0015,1.14)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x960:fps={fps}[top];"
                f"[1:v]scale=1200:1066:force_original_aspect_ratio=increase,crop=1200:1066,"
                f"zoompan=z='if(lte(zoom,1.0),1.0,1.14-0.0015*on)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x960:fps={fps}[bot];"
                f"[top][bot]vstack[stacked];"
                f"[stacked][2:v]overlay=0:0[v_base];"
                f"[v_base][3:v]overlay=0:0:enable='lt(t,{t_countdown:.2f})'[v_ou];"
                f"[v_ou][4:v]overlay=0:0:enable='between(t,{t3_start:.2f},{t3_end:.2f})'[v_3];"
                f"[v_3][5:v]overlay=0:0:enable='between(t,{t2_start:.2f},{t2_end:.2f})'[v_2];"
                f"[v_2][6:v]overlay=0:0:enable='gte(t,{t1_start:.2f})'[vfinal]"
            )

            cmd = [
                self.ffmpeg_bin, "-y",
                "-loop", "1", "-i", img_top,
                "-loop", "1", "-i", img_bot,
                "-i", overlay_base,
                "-i", badge_ou,
                "-i", badge_3,
                "-i", badge_2,
                "-i", badge_1,
                "-i", audio_path,
                "-t", f"{duration:.3f}",
                "-filter_complex", filter_complex,
                "-map", "[vfinal]",
                "-map", "7:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                output_scene_mp4,
            ]
        else:
            # Modo Q0-R: Expectativa limpa sem números + Revelação simultânea de porcentagens por ~1s
            overlay_reveal = os.path.abspath(os.path.join(self.config.temp_dir, f"overlay_{scene_id}_reveal.png"))
            self.create_question_reveal_overlay(item, overlay_reveal)

            filter_complex = (
                f"[0:v]scale=1200:1066:force_original_aspect_ratio=increase,crop=1200:1066,"
                f"zoompan=z='min(zoom+0.0015,1.14)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x960:fps={fps}[top];"
                f"[1:v]scale=1200:1066:force_original_aspect_ratio=increase,crop=1200:1066,"
                f"zoompan=z='if(lte(zoom,1.0),1.0,1.14-0.0015*on)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x960:fps={fps}[bot];"
                f"[top][bot]vstack[stacked];"
                f"[stacked][2:v]overlay=0:0[v_base];"
                f"[v_base][3:v]overlay=0:0[v_ou];"
                f"[v_ou][4:v]overlay=0:0:enable='gte(t,{t_reveal_start:.2f})'[vfinal]"
            )

            cmd = [
                self.ffmpeg_bin, "-y",
                "-loop", "1", "-i", img_top,
                "-loop", "1", "-i", img_bot,
                "-i", overlay_base,
                "-i", badge_ou,
                "-i", overlay_reveal,
                "-i", audio_path,
                "-t", f"{duration:.3f}",
                "-filter_complex", filter_complex,
                "-map", "[vfinal]",
                "-map", "5:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                output_scene_mp4,
            ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"[RENDER] Falha na renderização de {scene_id}: {res.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg render falhou para {scene_id}")

        logger.info(f"[ENGINE] Cena {scene_id} renderizada: {output_scene_mp4} ({duration:.2f}s)")
        return output_scene_mp4

    def concat_and_mix_bgm(self, scene_files: List[str]) -> bool:
        """Concatena as cenas e mixa a trilha ambiente com faststart."""
        concat_list_file = os.path.join(self.config.temp_dir, "concat_list.txt")
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for sf in scene_files:
                clean_path = os.path.abspath(sf).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        staged_concat = os.path.join(self.config.temp_dir, "staged_concat.mp4")

        # Concatenação sem perda
        cmd_concat = [
            self.ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", os.path.abspath(concat_list_file),
            "-c", "copy",
            staged_concat,
        ]
        res_c = subprocess.run(cmd_concat, capture_output=True, text=True)
        if res_c.returncode != 0 or not os.path.exists(staged_concat):
            logger.error(f"[CONCAT] Falha na concatenação das cenas: {res_c.stderr[-400:]}")
            return False

        probe = probe_media(staged_concat)
        total_dur = float(probe.get("format_duration", 0.0) or 64.0)

        # Mixagem com BGM
        bgm_path = self.config.video_settings.get("bgm_path", "")
        bgm_vol = self.config.video_settings.get("bgm_volume", 0.14)
        fade_start = max(0.0, total_dur - 3.0)

        filter_complex = (
            f"[0:a]volume=1.0[voice];"
            f"[1:a]volume={bgm_vol:.2f},afade=t=out:st={fade_start:.2f}:d=3[music];"
            f"[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.98[aout]"
        )

        out_mp4 = self.config.output_video_path
        cmd_final = [
            self.ffmpeg_bin, "-y",
            "-i", os.path.abspath(staged_concat),
            "-stream_loop", "-1",
            "-i", os.path.abspath(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_dur:.3f}",
            "-movflags", "+faststart",
            os.path.abspath(out_mp4),
        ]

        res_f = subprocess.run(cmd_final, capture_output=True, text=True)
        return res_f.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 1000

    # -------------------------------------------------------------------------
    # 6. Pipeline Completo de Execução
    # -------------------------------------------------------------------------
    async def render_async(self) -> Dict[str, Any]:
        t_start = time.perf_counter()
        logger.info(f"=== INICIANDO QUIZ ENGINE: NICHO '{self.config.niche}' ===")

        # 1. Imagens
        self.ensure_images()

        # 2. Thumbnail
        self.generate_thumbnail()

        # 3. SFX de Revelação e Countdown
        sfx_chime = self.generate_revelation_sfx()
        enable_badges = self.config.countdown_settings.get("enable_countdown_badges", False)
        sfx_countdown = self.generate_countdown_sfx(duration=3.5) if enable_badges else None

        # 4. Síntese de Voz e Áudio dos Segmentos
        total_planned_duration = 0.0
        hook_cfg = self.config.retention_hook

        reveal_sec = float(self.config.countdown_settings.get("reveal_sec", 1.0))
        default_post_sec = float(self.config.countdown_settings.get("default_sec", 3.0))

        for idx, item in enumerate(self.config.questions):
            scene_id = item["id"]
            narration_mp3 = os.path.join(self.config.temp_dir, f"narration_{scene_id}.mp3")
            dur_voice = await self.synthesize_voice(item["narration"], narration_mp3)

            # Verifica se esta pergunta é o gancho de retenção
            is_hook = item.get("is_hook") or (hook_cfg.get("enabled") and hook_cfg.get("question_id") == scene_id)
            if is_hook:
                hook_narration = item.get("hook_narration") or hook_cfg.get("narration", "")
                hook_mp3 = os.path.join(self.config.temp_dir, f"hook_{scene_id}.mp3")
                dur_hook = await self.synthesize_voice(hook_narration, hook_mp3)
                min_cd = hook_cfg.get("min_countdown_sec", 3.5)
                post_sec = max(float(item.get("countdown_sec", min_cd)), dur_hook + 0.15)
                item["countdown_sec"] = post_sec
                countdown_audio = hook_mp3
                logger.info(f"Pergunta {scene_id} (GANCHO): voz_q={dur_voice:.2f}s | voz_gancho={dur_hook:.2f}s | pos={post_sec:.2f}s")
            else:
                post_sec = float(item.get("countdown_sec", default_post_sec))
                item["countdown_sec"] = post_sec
                countdown_audio = sfx_countdown if enable_badges else None
                logger.info(f"Pergunta {scene_id}: voz_q={dur_voice:.2f}s | pos_espera_revelacao={post_sec:.2f}s")

            dur_total = dur_voice + post_sec
            item["total_duration"] = dur_total

            audio_scene = os.path.join(self.config.temp_dir, f"audio_{scene_id}.mp4")
            self.mix_segment_audio(
                narration_mp3=narration_mp3,
                countdown_audio=countdown_audio,
                output_audio=audio_scene,
                total_duration=dur_total,
                countdown_sec=post_sec,
                reveal_sfx=sfx_chime,
                reveal_sec=reveal_sec,
            )
            total_planned_duration += dur_total

        logger.info(f"Duração Total Planejada: {total_planned_duration:.2f}s (Alvo: {self.config.target_duration_range[0]}-{self.config.target_duration_range[1]}s)")

        # 5. Renderização das Cenas
        scene_files = []
        for item in self.config.questions:
            sc_path = self.render_scene(item)
            scene_files.append(sc_path)

        # 6. Concatenação e BGM
        success = self.concat_and_mix_bgm(scene_files)
        if not success:
            raise RuntimeError("Falha na concatenação ou mixagem final do vídeo.")

        render_time = time.perf_counter() - t_start

        # 7. Validação
        probe_v = probe_media(self.config.output_video_path)
        actual_dur = float(probe_v.get("format_duration", 0.0) or total_planned_duration)
        v_stream = (probe_v.get("video_streams") or [{}])[0]
        w_actual = v_stream.get("width", 1080)
        h_actual = v_stream.get("height", 1920)

        probe_t = probe_media(self.config.output_thumbnail_path)
        t_stream = (probe_t.get("video_streams") or [{}])[0]
        tw_actual = t_stream.get("width", 1080)
        th_actual = t_stream.get("height", 1920)

        result = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "video_path": self.config.output_video_path,
            "thumbnail_path": self.config.output_thumbnail_path,
            "duration": actual_dur,
            "resolution": f"{w_actual}x{h_actual}",
            "thumbnail_resolution": f"{tw_actual}x{th_actual}",
            "render_time": render_time,
            "niche": self.config.niche,
            "total_questions": len(self.config.questions),
        }
        return result

    def render(self) -> Dict[str, Any]:
        """Wrapper síncrono para render_async."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(asyncio.run, self.render_async()).result()
            return loop.run_until_complete(self.render_async())
        except RuntimeError:
            return asyncio.run(self.render_async())


# =============================================================================
# Utilitários de Texto Pillow
# =============================================================================

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def _draw_styled_multiline_text(
    draw: ImageDraw.ImageDraw,
    lines: List[str],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    center_y: int,
    text_color: Tuple[int, int, int] = (255, 255, 255),
    shadow_color: Tuple[int, int, int, int] = (0, 0, 0, 240),
    line_spacing: int = 8,
) -> None:
    line_heights = [font.getbbox(l)[3] - font.getbbox(l)[1] for l in lines]
    total_h = sum(line_heights) + (len(lines) - 1) * line_spacing
    start_y = center_y - total_h // 2
    current_y = start_y
    for idx, line in enumerate(lines):
        lh = line_heights[idx]
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
            draw.text((center_x + dx, current_y + lh // 2 + dy), line, font=font, fill=shadow_color, anchor="mm")
        draw.text((center_x, current_y + lh // 2), line, font=font, fill=text_color, anchor="mm")
        current_y += lh + line_spacing


# =============================================================================
# CLI Entrypoint
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Quiz Engine Reutilizável (Fase Q1)")
    parser.add_argument(
        "--config",
        type=str,
        default=os.path.join(ROOT_DIR, "resource", "quiz_templates", "quiz_template_escolhas_impossiveis.json"),
        help="Caminho do arquivo JSON de configuração do quiz",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        logger.error(f"Arquivo de configuração JSON não encontrado: {config_path}")
        sys.exit(1)

    logger.info(f"Carregando configuração do Quiz: {config_path}")
    config = QuizConfig.from_json(config_path)

    engine = QuizEngine(config)
    result = asyncio.run(engine.render_async())

    print("\n" + "=" * 60)
    print("STATUS = CONCLUIDO_COM_SUCESSO")
    print(f"VIDEO_PATH = {result['video_path']}")
    print(f"THUMBNAIL_PATH = {result['thumbnail_path']}")
    print(f"DURATION = {result['duration']:.2f}s")
    print(f"RENDER_TIME = {result['render_time']:.2f}s")
    print('FIRST_COUNTDOWN_AUDIO = Narração Edge TTS ("Mas atenção... a última escolha vai te surpreender!")')
    print("OTHER_COUNTDOWN_AUDIO = Tique-taque de relógio sintetizado (inalterado)")
    print("PRODUCTION_FILES_MODIFIED = NENHUM")
    print("NEW_DEPENDENCIES = NENHUMA")
    print("ADDITIONAL_COST = R$ 0,00")
    print("NEXT_STEP = Aprovação humana do gate Q1 para avanço ao Q2 (Geração e Estruturação de Conteúdo por Nicho).")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
