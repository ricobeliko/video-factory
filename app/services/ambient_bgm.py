"""
Serviço de BGM Ambiente Procedural Seguro (Fase V1.5E-G8).

Gera sound beds / ambient beds discretos e cinematográficos de forma 100% local:
- Zero rede
- Zero API paga
- Zero arquivos de áudio externos
- Zero dependência de resource/songs/*.mp3
- Determinístico via síntese de áudio FFmpeg (lavfi / aevalsrc)
- Proveniência segura para monetização (SAFE_PROCEDURAL)
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import unicodedata
from typing import Any, Mapping, Optional

from loguru import logger

from app.utils import utils

# Constantes canônicas do Sound Bed
SUPPORTED_MOODS = (
    "suspense",
    "terror",
    "futuristic",
    "epic",
    "energetic",
    "emotional",
    "neutral",
)
DEFAULT_MOOD = "neutral"
DEFAULT_BGM_VOLUME = 0.10
MIN_BGM_VOLUME = 0.05
MAX_BGM_VOLUME = 0.15
FADE_IN_SECONDS = 1.5
FADE_OUT_SECONDS = 2.0
MAX_PROMPT_LENGTH = 1000

# Fórmulas de síntese stereo lavfi aevalsrc por mood
# Expressões puramente matemáticas e determinísticas sem ruído randômico não-reproduzível
_MOOD_SYNTHESIS_DEFINITIONS: dict[str, tuple[str, str, str]] = {
    "neutral": (
        "0.23*sin(2*PI*130.8*t+0.1*sin(2*PI*0.1*t))+0.16*sin(2*PI*196.0*t)+0.10*sin(2*PI*261.6*t)+0.07*sin(2*PI*392.0*t)",
        "0.23*sin(2*PI*131.2*t+0.1*sin(2*PI*0.12*t))+0.16*sin(2*PI*196.6*t)+0.10*sin(2*PI*262.2*t)+0.07*sin(2*PI*392.8*t)",
        "lowpass=f=600",
    ),
    "suspense": (
        "(0.7+0.3*sin(2*PI*0.6*t))*(0.20*sin(2*PI*98.0*t+0.2*sin(2*PI*0.3*t))+0.16*sin(2*PI*146.8*t)+0.10*sin(2*PI*220.0*t)+0.07*sin(2*PI*293.7*t))",
        "(0.7+0.3*sin(2*PI*0.6*t+1.57))*(0.20*sin(2*PI*98.5*t+0.2*sin(2*PI*0.3*t))+0.16*sin(2*PI*147.4*t)+0.10*sin(2*PI*220.8*t)+0.07*sin(2*PI*294.5*t))",
        "lowpass=f=550",
    ),
    "terror": (
        "(0.75+0.25*sin(2*PI*0.2*t))*(0.23*sin(2*PI*82.4*t)+0.16*sin(2*PI*116.5*t+0.3*sin(2*PI*0.15*t))+0.10*sin(2*PI*164.8*t)+0.07*sin(2*PI*233.1*t))",
        "(0.75+0.25*sin(2*PI*0.25*t))*(0.23*sin(2*PI*82.9*t)+0.16*sin(2*PI*117.1*t+0.3*sin(2*PI*0.18*t))+0.10*sin(2*PI*165.4*t)+0.07*sin(2*PI*234.0*t))",
        "lowpass=f=500",
    ),
    "futuristic": (
        "(0.65+0.35*sin(2*PI*1.5*t))*(0.20*sin(2*PI*174.6*t)+0.16*sin(2*PI*261.6*t)+0.12*sin(2*PI*349.2*t)+0.07*sin(2*PI*523.3*t))",
        "(0.65+0.35*cos(2*PI*1.5*t))*(0.20*sin(2*PI*175.2*t)+0.16*sin(2*PI*262.4*t)+0.12*sin(2*PI*350.2*t)+0.07*sin(2*PI*524.5*t))",
        "highpass=f=130,lowpass=f=800",
    ),
    "epic": (
        "(0.75+0.25*sin(2*PI*0.3*t))*(0.20*sin(2*PI*110.0*t)+0.16*sin(2*PI*164.8*t)+0.13*sin(2*PI*220.0*t)+0.08*sin(2*PI*329.6*t))",
        "(0.75+0.25*sin(2*PI*0.3*t+0.5))*(0.20*sin(2*PI*110.5*t)+0.16*sin(2*PI*165.4*t)+0.13*sin(2*PI*220.8*t)+0.08*sin(2*PI*330.6*t))",
        "lowpass=f=650",
    ),
    "energetic": (
        "(0.6+0.4*sin(2*PI*2.2*t)*sin(2*PI*2.2*t))*(0.21*sin(2*PI*146.8*t)+0.16*sin(2*PI*220.0*t)+0.12*sin(2*PI*293.7*t)+0.07*sin(2*PI*440.0*t))",
        "(0.6+0.4*sin(2*PI*2.2*t)*sin(2*PI*2.2*t))*(0.21*sin(2*PI*147.4*t)+0.16*sin(2*PI*220.8*t)+0.12*sin(2*PI*294.6*t)+0.07*sin(2*PI*441.2*t))",
        "lowpass=f=700",
    ),
    "emotional": (
        "(0.8+0.2*sin(2*PI*0.35*t))*(0.18*sin(2*PI*130.8*t)+0.16*sin(2*PI*164.8*t)+0.13*sin(2*PI*196.0*t)+0.09*sin(2*PI*261.6*t))",
        "(0.8+0.2*sin(2*PI*0.35*t+0.3))*(0.18*sin(2*PI*131.2*t)+0.16*sin(2*PI*165.3*t)+0.13*sin(2*PI*196.6*t)+0.09*sin(2*PI*262.4*t))",
        "lowpass=f=600",
    ),
}

# Palavras-chave para classificação local e determinística
# Ordenadas em ordem estrita de prioridade quando houver múltiplos sinais:
# terror > suspense > futuristic > epic > energetic > emotional > neutral
_MOOD_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "terror",
        (
            "assassinato", "criatura", "horror", "sobrenatural", "monstro", "medo",
            "assustador", "morte", "pesadelo", "sangue", "panico", "fantasma",
            "demonio", "macabro", "sinistro", "terror",
        ),
    ),
    (
        "suspense",
        (
            "misterio", "segredo", "desaparecimento", "conspiracao", "investigacao",
            "pista", "enigma", "suspeito", "crime", "oculto", "tenso", "tensao",
            "perigo", "suspense", "desvendar", "desconhecido",
        ),
    ),
    (
        "futuristic",
        (
            "inteligencia artificial", "tecnologia", "robo", "futuro", "espacial",
            "cibernetico", "sci-fi", "alien", "digital", "algoritmo", "maquina",
            "androide", "galaxia", "universo", "futurista", "cyber",
        ),
    ),
    (
        "epic",
        (
            "maior da historia", "conquista", "grandioso", "imperio", "lendario",
            "batalha", "vitoria historica", "gloria", "poder", "supremo", "gigante",
            "titan", "epico", "epica", "monumental", "reino", "soberano", "triunfo",
        ),
    ),
    (
        "energetic",
        (
            "gol", "corrida", "vitoria", "partida", "velocidade", "acao",
            "adrenalina", "explosao", "dinamico", "combate", "duelo", "ritmo",
            "futebol", "campeonato", "rapido", "energia", "energetico", "forca",
        ),
    ),
    (
        "emotional",
        (
            "familia", "despedida", "emocao", "reencontro", "saudade", "superacao",
            "lagrimas", "amor", "emocionante", "comovente", "adeus", "coracao",
            "tristeza", "esperanca", "sentimento", "afeto",
        ),
    ),
]


class AmbientBgmError(RuntimeError):
    """Erro de geração ou síntese de BGM procedural ambiente."""
    pass


def normalize_text(text: str) -> str:
    """Normaliza texto removendo acentos, convertendo para minúsculas e simplificando espaços."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents.lower()).strip()


def normalize_volume(volume: Any, default: float = DEFAULT_BGM_VOLUME) -> float:
    """
    Normaliza o volume da trilha ambiente garantindo limites seguros.

    min: 0.05
    max: 0.15
    fallback em caso inválido: 0.10
    """
    try:
        val = float(volume)
        if not math.isfinite(val) or val <= 0:
            return default
        if val < MIN_BGM_VOLUME:
            return MIN_BGM_VOLUME
        if val > MAX_BGM_VOLUME:
            return MAX_BGM_VOLUME
        return val
    except (TypeError, ValueError):
        return default


def detect_mood(text: str, default_mood: str = DEFAULT_MOOD) -> str:
    """
    Classificador local e determinístico de mood pelo texto do roteiro.

    Zero chamada LLM, zero custo de API/tokens.
    Prioridade estrita quando houver múltiplos sinais:
    terror > suspense > futuristic > epic > energetic > emotional > neutral
    """
    normalized = normalize_text(text)
    if not normalized:
        clean_def = normalize_text(default_mood)
        return clean_def if clean_def in SUPPORTED_MOODS else DEFAULT_MOOD

    for mood, keywords in _MOOD_KEYWORD_RULES:
        for kw in keywords:
            if kw in normalized:
                return mood

    clean_def = normalize_text(default_mood)
    return clean_def if clean_def in SUPPORTED_MOODS else DEFAULT_MOOD


def is_enabled() -> bool:
    """
    Retorna True: provedor 100% local que não exige chave externa ou credencial de API.
    A disponibilidade do binário FFmpeg é validada pelo preflight canônico subsequente.
    """
    return True


def generate_ambient_bgm(
    output_path: str,
    duration: float,
    mood: str = DEFAULT_MOOD,
    volume: float = 1.0,
    fade_in: float = FADE_IN_SECONDS,
    fade_out: float = FADE_OUT_SECONDS,
) -> str:
    """
    Sintetiza um sound bed procedural contínuo usando FFmpeg local em nível canônico estável.

    - 100% local e determinístico
    - Sem melodia invasiva
    - Nível estável de headroom seguro (o bgm_volume configurado pelo operador é aplicado
      uma única vez pelo mixer final video.generate_video / _mix_audio_ffmpeg, evitando atenuação dupla)
    - Fade-in e Fade-out suaves preservados
    """
    if duration <= 0:
        raise AmbientBgmError(f"Duração inválida para síntese de BGM: {duration}s")

    clean_mood = str(mood or "").lower().strip()
    if clean_mood not in _MOOD_SYNTHESIS_DEFINITIONS:
        clean_mood = DEFAULT_MOOD

    synth_def = _MOOD_SYNTHESIS_DEFINITIONS[clean_mood]
    expr_l, expr_r, filter_chain = synth_def

    ffmpeg_bin = utils.get_ffmpeg_binary()
    if not ffmpeg_bin:
        raise AmbientBgmError("Binário do FFmpeg não encontrado para síntese procedural de BGM.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Cálculo seguro de fades para vídeos curtos
    actual_fade_in = min(fade_in, duration / 2.0)
    actual_fade_out = min(fade_out, duration / 2.0)
    fade_out_start = max(0.0, duration - actual_fade_out)

    lavfi_filter = (
        f"aevalsrc=exprs={expr_l}|{expr_r}:s=44100:d={duration},"
        f"{filter_chain},"
        f"afade=t=in:ss=0:d={actual_fade_in:.2f},"
        f"afade=t=out:st={fade_out_start:.2f}:d={actual_fade_out:.2f}"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", lavfi_filter,
        "-t", f"{duration:.3f}",
        output_path,
    ]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(30.0, duration * 2.0),
        )
        if res.returncode != 0:
            raise AmbientBgmError(
                f"FFmpeg falhou ao gerar ambient BGM (código {res.returncode}): {res.stderr[:300]}"
            )
    except subprocess.SubprocessError as exc:
        raise AmbientBgmError(f"Erro ao executar FFmpeg para ambient BGM: {exc}") from exc

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise AmbientBgmError(f"Arquivo de ambient BGM gerado vazio ou inexistente: {output_path}")

    return output_path


def generate_bgm(
    video_path: Optional[str] = None,
    output_path: str = "",
    video_duration: float = 0.0,
    prompt: str = "",
    volume: float = DEFAULT_BGM_VOLUME,
    **kwargs: Any,
) -> str:
    """
    Contrato canônico compatível com o pipeline existente de _VIDEO_MUSIC_PROVIDERS.

    Detecta mood a partir de prompt/roteiro, gera o sound bed e persiste metadados no script.json se aplicável.
    """
    if video_duration <= 0:
        raise AmbientBgmError(f"Duração de vídeo inválida para geração de BGM: {video_duration}")

    # Determina o mood
    selected_mood = DEFAULT_MOOD
    norm_prompt = str(prompt or "").strip().lower()

    if norm_prompt in SUPPORTED_MOODS:
        selected_mood = norm_prompt
    elif norm_prompt:
        selected_mood = detect_mood(norm_prompt, default_mood=DEFAULT_MOOD)
    else:
        # Tenta ler script.json da task se output_path estiver em diretório de task
        task_id = _extract_task_id(output_path)
        if task_id:
            script_data = _load_task_script_data(task_id)
            if script_data:
                script_text = script_data.get("script") or script_data.get("video_script", "")
                params_dict = script_data.get("params") if isinstance(script_data.get("params"), dict) else {}
                subject = params_dict.get("video_subject") or script_data.get("video_subject", "")
                default_m = (
                    params_dict.get("bgm_default_mood")
                    or params_dict.get("default_mood")
                    or script_data.get("bgm_default_mood")
                    or DEFAULT_MOOD
                )
                combined_text = f"{script_text} {subject}".strip()
                selected_mood = detect_mood(combined_text, default_mood=default_m)

    # Persiste metadados no script.json da task sem nova tabela
    task_id = _extract_task_id(output_path)
    if task_id:
        try:
            from app.services import task_artifacts
            task_artifacts.patch_script_data(
                task_id,
                bgm_mood=selected_mood,
                bgm_source="procedural",
                bgm_provenance="SAFE_PROCEDURAL",
            )
        except Exception as exc:
            logger.debug(f"[AMBIENT_BGM] Não foi possível persistir metadados no script.json: {exc}")

    return generate_ambient_bgm(
        output_path=output_path,
        duration=video_duration,
        mood=selected_mood,
    )


def _extract_task_id(file_path: str) -> Optional[str]:
    """Extrai o task_id de um caminho de arquivo localizado dentro de storage/tasks/{task_id}."""
    if not file_path:
        return None
    normalized = os.path.normpath(file_path)
    parts = normalized.split(os.sep)
    if "tasks" in parts:
        idx = parts.index("tasks")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _load_task_script_data(task_id: str) -> Optional[dict[str, Any]]:
    """Carrega com segurança o script.json de uma tarefa."""
    try:
        from app.services import task_artifacts
        import json
        script_file = task_artifacts._script_file(task_id)
        if script_file.is_file():
            with script_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return None
