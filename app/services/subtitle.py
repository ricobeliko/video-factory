import json
import os.path
import re
import threading
import unicodedata
from timeit import default_timer as timer
from typing import Any, Dict, Optional

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
from loguru import logger

from app.config import config
from app.utils import utils

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
initial_prompt = config.whisper.get("initial_prompt", "") or None
model = None
_model_lock = threading.Lock()


def create(audio_file, subtitle_file: str = "", word_level: bool = False):
    global model
    if WhisperModel is None:
        logger.warning("faster_whisper not available, skipping whisper subtitle generation")
        return ""
    with _model_lock:
        if not model:
            model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
            model_bin_file = f"{model_path}/model.bin"
            if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
                model_path = model_size

            logger.info(
                f"loading model: {model_path}, device: {device}, compute_type: {compute_type}"
            )
            try:
                model = WhisperModel(
                    model_size_or_path=model_path, device=device, compute_type=compute_type
                )
            except Exception as e:
                logger.error(
                    f"failed to load model: {e} \n\n"
                    f"********************************************\n"
                    f"this may be caused by network issue. \n"
                    f"please download the model manually and put it in the 'models' folder. \n"
                    f"see [README.md FAQ](https://github.com/harry0703/MoneyPrinterTurbo) for more details.\n"
                    f"********************************************\n\n"
                )
                return None

    logger.info(f"start, output file: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        **({"initial_prompt": initial_prompt} if initial_prompt else {}),
    )

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []

    def recognized(seg_text, seg_start, seg_end):
        seg_text = seg_text.strip()
        if not seg_text:
            return

        msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
        logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        if word_level and segment.words:
            for word in segment.words:
                cleaned_word = word.word.strip()
                if cleaned_word:
                    recognized(cleaned_word, word.start, word.end)
            continue

        words_idx = 0
        words_len = len(segment.words)

        seg_start = 0
        seg_end = 0
        seg_text = ""

        if segment.words:
            is_segmented = False
            for word in segment.words:
                if not is_segmented:
                    seg_start = word.start
                    is_segmented = True

                seg_end = word.end
                # If it contains punctuation, then break the sentence.
                seg_text += word.word

                if utils.str_contains_punctuation(word.word):
                    # remove last char
                    seg_text = seg_text[:-1]
                    if not seg_text:
                        continue

                    recognized(seg_text, seg_start, seg_end)

                    is_segmented = False
                    seg_text = ""

                if words_idx == 0 and segment.start < word.start:
                    seg_start = word.start
                if words_idx == (words_len - 1) and segment.end > word.end:
                    seg_end = word.end
                words_idx += 1

        if not seg_text:
            continue

        recognized(seg_text, seg_start, seg_end)

    end = timer()

    diff = end - start
    logger.info(f"complete, elapsed: {diff:.2f} s")

    idx = 1
    lines = []
    for subtitle in subtitles:
        text = subtitle.get("msg")
        if text:
            lines.append(
                utils.text_to_srt(
                    idx, text, subtitle.get("start_time"), subtitle.get("end_time")
                )
            )
            idx += 1

    sub = "\n".join(lines) + "\n"
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(sub)
    logger.info(f"subtitle file created: {subtitle_file}")


def file_to_subtitles(filename):
    if not filename or not os.path.isfile(filename):
        return []

    times_texts = []
    current_times = None
    current_text = ""
    index = 0
    with open(filename, "r", encoding="utf-8-sig") as f:
        for line in f:
            times = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", line)
            if times:
                current_times = line
            elif line.strip() == "" and current_times:
                index += 1
                times_texts.append((index, current_times.strip(), current_text.strip()))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line

    # Flush the final block. SRT files whose last subtitle is not followed by a
    # trailing blank line never hit the blank-line branch above, so without this
    # the last subtitle would be silently dropped.
    if current_times:
        index += 1
        times_texts.append((index, current_times.strip(), current_text.strip()))
    return times_texts


def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity(a, b):
    distance = levenshtein_distance(a.lower(), b.lower())
    max_length = max(len(a), len(b))
    return 1 - (distance / max_length)


def correct(subtitle_file, video_script):
    subtitle_items = file_to_subtitles(subtitle_file)
    normalized_script = utils.normalize_script_for_subtitle_matching(video_script)
    script_lines = utils.split_string_by_punctuations(normalized_script)

    corrected = False
    new_subtitle_items = []
    script_index = 0
    subtitle_index = 0

    while script_index < len(script_lines) and subtitle_index < len(subtitle_items):
        script_line = script_lines[script_index].strip()
        subtitle_line = subtitle_items[subtitle_index][2].strip()

        if script_line == subtitle_line:
            new_subtitle_items.append(subtitle_items[subtitle_index])
            script_index += 1
            subtitle_index += 1
        else:
            combined_subtitle = subtitle_line
            start_time = subtitle_items[subtitle_index][1].split(" --> ")[0]
            end_time = subtitle_items[subtitle_index][1].split(" --> ")[1]
            next_subtitle_index = subtitle_index + 1

            while next_subtitle_index < len(subtitle_items):
                next_subtitle = subtitle_items[next_subtitle_index][2].strip()
                if similarity(
                    script_line, combined_subtitle + " " + next_subtitle
                ) > similarity(script_line, combined_subtitle):
                    combined_subtitle += " " + next_subtitle
                    end_time = subtitle_items[next_subtitle_index][1].split(" --> ")[1]
                    next_subtitle_index += 1
                else:
                    break

            if similarity(script_line, combined_subtitle) > 0.8:
                logger.warning(
                    f"Merged/Corrected - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True
            else:
                logger.warning(
                    f"Mismatch - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True

            script_index += 1
            subtitle_index = next_subtitle_index

    # Process the remaining lines of the script.
    while script_index < len(script_lines):
        logger.warning(f"Extra script line: {script_lines[script_index]}")
        if subtitle_index < len(subtitle_items):
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    subtitle_items[subtitle_index][1],
                    script_lines[script_index],
                )
            )
            subtitle_index += 1
        else:
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    "00:00:00,000 --> 00:00:00,000",
                    script_lines[script_index],
                )
            )
        script_index += 1
        corrected = True

    if corrected:
        with open(subtitle_file, "w", encoding="utf-8") as fd:
            for i, item in enumerate(new_subtitle_items):
                fd.write(f"{i + 1}\n{item[1]}\n{item[2]}\n\n")
        logger.info("Subtitle corrected")
    else:
        logger.success("Subtitle is correct")


def parse_srt_timestamp(ts_str: str) -> Optional[float]:
    """Converte timestamp SRT ('HH:MM:SS,mmm' ou 'HH:MM:SS.mmm') em segundos (float).

    Rejeita de forma estrita (retorna None):
    - hora negativa (< 0)
    - minuto < 0 ou >= 60
    - segundo < 0 ou >= 60
    - milissegundo < 0 ou > 999
    - campos vazios ou não numéricos
    - timestamp estruturalmente inválido
    """
    try:
        if not ts_str or not isinstance(ts_str, str):
            return None
        clean = ts_str.strip().replace(".", ",")
        parts = clean.split(":")
        if len(parts) != 3:
            return None
        if not parts[0].strip() or not parts[1].strip() or not parts[2].strip():
            return None

        h_str = parts[0].strip()
        m_str = parts[1].strip()
        s_parts = parts[2].strip().split(",")
        if len(s_parts) > 2 or not s_parts[0].strip():
            return None
        s_str = s_parts[0].strip()
        ms_str = s_parts[1].strip() if len(s_parts) > 1 else "0"
        if not ms_str:
            return None

        h = int(h_str)
        m = int(m_str)
        s = int(s_str)
        ms = int(ms_str)

        if h < 0:
            return None
        if m < 0 or m >= 60:
            return None
        if s < 0 or s >= 60:
            return None
        if ms < 0 or ms > 999:
            return None

        return h * 3600.0 + m * 60.0 + s + (ms / 1000.0)
    except Exception:
        return None


def validate_subtitle_file(
    subtitle_path: str,
    video_script: Optional[str] = None,
) -> Dict[str, Any]:
    """Valida a integridade física, sintática e semântica de um arquivo SRT.

    Requisitos canônicos (Fail-Closed):
    - caminho não vazio e arquivo regular existente em disco
    - tamanho > 0 bytes e não composto exclusivamente de whitespace
    - legível em UTF-8 / UTF-8-SIG
    - possui pelo menos 1 cue
    - todo cue possui timestamps válidos (start < end, não todos zero)
    - todo cue possui texto não vazio (não apenas índices/timestamps)
    - coerência mínima com o roteiro (se video_script fornecido)

    Retorno estruturado sem lançar exceções:
    {
        "valid": bool,
        "reason": str,
        "cue_count": int,
        "text_chars": int,
        "total_duration": float,
    }
    """
    empty_result = {
        "valid": False,
        "reason": "empty_path",
        "cue_count": 0,
        "text_chars": 0,
        "total_duration": 0.0,
    }
    if not subtitle_path or not isinstance(subtitle_path, str) or not subtitle_path.strip():
        return empty_result

    if not os.path.exists(subtitle_path):
        return {**empty_result, "reason": "file_not_found"}

    if not os.path.isfile(subtitle_path):
        return {**empty_result, "reason": "not_a_regular_file"}

    try:
        file_size = os.path.getsize(subtitle_path)
    except Exception as exc:
        return {**empty_result, "reason": f"io_error_getsize: {exc}"}

    if file_size == 0:
        return {**empty_result, "reason": "empty_file"}

    try:
        with open(subtitle_path, "r", encoding="utf-8-sig") as f:
            raw_content = f.read()
    except UnicodeDecodeError:
        return {**empty_result, "reason": "invalid_utf8_encoding"}
    except Exception as exc:
        return {**empty_result, "reason": f"io_error_read: {exc}"}

    if not raw_content or not raw_content.strip():
        return {**empty_result, "reason": "whitespace_only"}

    # Parse cues
    lines = raw_content.splitlines()
    cues = []
    current_time_line = None
    current_text_lines = []

    for line in lines:
        stripped = line.strip()
        if "-->" in stripped:
            if current_time_line is not None:
                cue_text = "\n".join(current_text_lines).strip()
                cues.append((current_time_line, cue_text))
                current_text_lines = []
            current_time_line = stripped
        elif stripped == "":
            if current_time_line is not None:
                cue_text = "\n".join(current_text_lines).strip()
                cues.append((current_time_line, cue_text))
                current_time_line = None
                current_text_lines = []
        else:
            if current_time_line is not None:
                current_text_lines.append(stripped)

    if current_time_line is not None:
        cue_text = "\n".join(current_text_lines).strip()
        cues.append((current_time_line, cue_text))

    if not cues:
        return {**empty_result, "reason": "no_cues_found"}

    all_zero_timestamps = True
    total_text_chars = 0
    min_start = float("inf")
    max_end = float("-inf")

    for idx, (time_line, text) in enumerate(cues, start=1):
        if not text or not text.strip():
            return {
                "valid": False,
                "reason": "empty_cue_text",
                "cue_count": len(cues),
                "text_chars": total_text_chars,
                "total_duration": 0.0,
            }

        total_text_chars += len(text.strip())

        parts = time_line.split("-->")
        if len(parts) != 2:
            return {
                "valid": False,
                "reason": "malformed_timestamp_line",
                "cue_count": len(cues),
                "text_chars": total_text_chars,
                "total_duration": 0.0,
            }

        start_sec = parse_srt_timestamp(parts[0])
        end_sec = parse_srt_timestamp(parts[1])

        if start_sec is None or end_sec is None:
            return {
                "valid": False,
                "reason": "invalid_timestamp_format",
                "cue_count": len(cues),
                "text_chars": total_text_chars,
                "total_duration": 0.0,
            }

        if start_sec == 0.0 and end_sec == 0.0:
            return {
                "valid": False,
                "reason": "all_timestamps_zero",
                "cue_count": len(cues),
                "text_chars": total_text_chars,
                "total_duration": 0.0,
            }

        if start_sec >= end_sec:
            return {
                "valid": False,
                "reason": "invalid_timestamp_order",
                "cue_count": len(cues),
                "text_chars": total_text_chars,
                "total_duration": 0.0,
            }

        if start_sec > 0.0 or end_sec > 0.0:
            all_zero_timestamps = False

        min_start = min(min_start, start_sec)
        max_end = max(max_end, end_sec)

    if all_zero_timestamps:
        return {
            "valid": False,
            "reason": "all_timestamps_zero",
            "cue_count": len(cues),
            "text_chars": total_text_chars,
            "total_duration": 0.0,
        }

    total_duration = max(0.0, max_end - (min_start if min_start != float("inf") else 0.0))

    # Coerência com o roteiro (Coverage + Lexical Overlap)
    if video_script and isinstance(video_script, str) and str(video_script).strip():
        # A) Cobertura proporcional de caracteres úteis (sem whitespace e pontuação)
        script_chars = re.sub(r"[\s\W_]+", "", str(video_script), flags=re.UNICODE)
        all_cue_text = " ".join(text for _, text in cues)
        subs_chars = re.sub(r"[\s\W_]+", "", all_cue_text, flags=re.UNICODE)

        if len(script_chars) >= 30:
            coverage_ratio = len(subs_chars) / len(script_chars)
            # Bloqueia se a cobertura for inferior a 20% ou texto minúsculo (< 15 chars)
            if coverage_ratio < 0.20 or len(subs_chars) < 15:
                return {
                    "valid": False,
                    "reason": "text_incoherent_with_script",
                    "cue_count": len(cues),
                    "text_chars": total_text_chars,
                    "total_duration": total_duration,
                }

        # B) Sobreposição lexical (tokens úteis com normalização sem acentos)
        def _extract_tokens(txt: str) -> set:
            nfkd = unicodedata.normalize("NFKD", txt)
            ascii_txt = nfkd.encode("ASCII", "ignore").decode("ASCII").lower()
            return set(re.findall(r"\b[a-z0-9]{3,}\b", ascii_txt))

        script_tokens = _extract_tokens(str(video_script))
        sub_tokens = _extract_tokens(all_cue_text)

        if len(script_tokens) >= 4:
            overlap = script_tokens.intersection(sub_tokens)
            overlap_ratio = len(overlap) / len(script_tokens)
            # Se não houver palavras em comum ou sobreposição for insignificante (< 15%)
            if overlap_ratio < 0.15 or len(overlap) == 0:
                return {
                    "valid": False,
                    "reason": "text_incoherent_with_script",
                    "cue_count": len(cues),
                    "text_chars": total_text_chars,
                    "total_duration": total_duration,
                }

    return {
        "valid": True,
        "reason": "valid",
        "cue_count": len(cues),
        "text_chars": total_text_chars,
        "total_duration": total_duration,
    }


validate_srt = validate_subtitle_file


if __name__ == "__main__":
    task_id = "c12fd1e6-4b0a-4d65-a075-c87abe35a072"
    task_dir = utils.task_dir(task_id)
    subtitle_file = f"{task_dir}/subtitle.srt"
    audio_file = f"{task_dir}/audio.mp3"

    subtitles = file_to_subtitles(subtitle_file)
    print(subtitles)

    script_file = f"{task_dir}/script.json"
    with open(script_file, "r") as f:
        script_content = f.read()
    s = json.loads(script_content)
    script = s.get("script")

    correct(subtitle_file, script)

    subtitle_file = f"{task_dir}/subtitle-test.srt"
    create(audio_file, subtitle_file)
