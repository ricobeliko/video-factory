"""
Test Suite para Clip Captions Service (Fase V11-D — Captions).

Cobre os requisitos de legendas:
1. schema caption_tracks idempotente
2. schema caption_cues idempotente
3. transcript obrigatório
4. transcript FAILED rejeitado
5. segment inexistente rejeita
6. segment não SELECTED rejeita
7. render inexistente não quebra track creation
8. source/profile preservados
9. SECONDARY bloqueado
10. PRIMARY aceita
11. cue overlap correto
12. timestamps convertidos para clip-relative
13. cue antes do clip ignorada
14. cue depois do clip ignorada
15. cue parcial no início cortada
16. cue parcial no fim cortada
17. start >= 0
18. end > start
19. end <= clip duration
20. whitespace cleanup
21. texto não semanticamente alterado
22. unicode preservado
23. SRT escaping seguro
24. ASS escaping seguro
25. CLEAN style válido
26. BOLD style válido
27. style inválido rejeitado
28. safe area aplicada
29. font fallback seguro
30. SRT criado
31. ASS criado
32. fingerprint determinístico
33. force=False reutiliza
34. force=True histórico
35. PROCESSING duplicado bloqueado
"""
from datetime import datetime, timezone
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import (
    clip_captions,
    clip_mode,
    clip_transcription,
    operator_console,
    profile_manager,
)
from app.utils import utils


class TestClipCaptions(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.tmp_dir.name, "test_captions.db")

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        profile_manager.init_profile_db(db_path=self.test_db_path)
        profile_manager.ensure_default_profile(db_path=self.test_db_path)
        clip_mode.init_clip_db(db_path=self.test_db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.test_db_path)
        clip_captions.init_clip_captions_db(db_path=self.test_db_path)

        # Arquivo de vídeo mock
        self.fake_video = os.path.join(self.tmp_dir.name, "fake_video.mp4")
        with open(self.fake_video, "wb") as f:
            f.write(b"MOCK_VIDEO_DATA")

        self.mock_probe = {
            "duration_seconds": 200.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_probe):
            imp = clip_mode.import_clip_source(
                self.fake_video,
                source_origin="owned",
                authorization_confirmed=True,
                authorization_note="Teste Unitário Captions",
                db_path=self.test_db_path,
            )
            self.source_id = imp["source_id"]

        # Cria transcrição COMPLETED com segmentos para a source
        self.transcript_id = "trans_test_001"
        now_iso = datetime.now(timezone.utc).isoformat()
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_transcripts (
                    id, source_id, profile_id, provider, model_name,
                    language, status, full_text, started_at, completed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    self.transcript_id,
                    self.source_id,
                    "default",
                    "faster-whisper",
                    "base",
                    "pt",
                    "COMPLETED",
                    "Texto completo de teste",
                    now_iso,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            # Cues da transcrição (escala global de 0 a 200s):
            # 1: 0s -> 50s: "Introdução fora do corte"
            # 2: 110s -> 125s: "Início parcial do corte"
            # 3: 125s -> 135s: "Frase do meio com acentuação e pontuação!"
            # 4: 135s -> 148s: "Segunda frase central com espaços   duplos."
            # 5: 148s -> 155s: "Fim parcial do corte"
            # 6: 160s -> 180s: "Encerramento fora do corte"
            cues_to_insert = [
                ("tseg_1", 1, 0.0, 50.0, "Introdução fora do corte"),
                ("tseg_2", 2, 110.0, 125.0, "Início parcial do corte"),
                ("tseg_3", 3, 125.0, 135.0, "Frase do meio com acentuação e pontuação!"),
                ("tseg_4", 4, 135.0, 148.0, "Segunda frase central com espaços   duplos."),
                ("tseg_5", 5, 148.0, 155.0, "Fim parcial do corte"),
                ("tseg_6", 6, 160.0, 180.0, "Encerramento fora do corte"),
            ]
            for cid, seq, s, e, txt in cues_to_insert:
                conn.execute(
                    """
                    INSERT INTO clip_transcript_segments (
                        id, transcript_id, source_id, sequence, start_seconds, end_seconds, text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (cid, self.transcript_id, self.source_id, seq, s, e, txt, now_iso),
                )

        # Cria segmento SELECTED de 120s a 150s (Duração: 30s)
        seg_res = clip_mode.create_clip_segment(
            source_id=self.source_id,
            start_seconds=120.0,
            end_seconds=150.0,
            title="Segmento 120-150",
            db_path=self.test_db_path,
        )
        self.segment_id = seg_res["segment_id"]
        clip_mode.update_clip_segment_status(self.segment_id, "SELECTED", db_path=self.test_db_path)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def test_01_and_02_schemas_idempotent(self):
        """1 e 2: Verifica que a inicialização do schema de tracks e cues é idempotente."""
        clip_captions.init_clip_captions_db(db_path=self.test_db_path)
        clip_captions.init_clip_captions_db(db_path=self.test_db_path)
        with clip_mode.get_connection(self.test_db_path) as conn:
            t1 = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_caption_tracks';").fetchone()
            t2 = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_caption_cues';").fetchone()
            self.assertIsNotNone(t1)
            self.assertIsNotNone(t2)

    def test_03_transcript_required(self):
        """3: Rejeita geração se a fonte não tiver transcrição COMPLETED."""
        other_vid = os.path.join(self.tmp_dir.name, "v2.mp4")
        with open(other_vid, "wb") as f:
            f.write(b"video 2")
        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_probe):
            imp2 = clip_mode.import_clip_source(other_vid, source_origin="owned", authorization_confirmed=True, db_path=self.test_db_path)
        seg2 = clip_mode.create_clip_segment(imp2["source_id"], 0.0, 10.0, db_path=self.test_db_path)
        clip_mode.update_clip_segment_status(seg2["segment_id"], "SELECTED", db_path=self.test_db_path)

        with self.assertRaises(clip_captions.TranscriptRequiredError):
            clip_captions.generate_clip_captions(seg2["segment_id"], db_path=self.test_db_path)

    def test_04_transcript_failed_rejected(self):
        """4: Transcrição em status FAILED é rejeitada (não é COMPLETED)."""
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute("UPDATE clip_transcripts SET status = 'FAILED' WHERE id = ?", (self.transcript_id,))

        with self.assertRaises(clip_captions.TranscriptRequiredError):
            clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)

    def test_05_segment_inexistent_rejected(self):
        """5: Segmento inexistente levanta erro."""
        with self.assertRaises(clip_captions.ClipCaptionError):
            clip_captions.generate_clip_captions("seg_non_existent", db_path=self.test_db_path)

    def test_06_segment_not_selected_rejected(self):
        """6: Segmento em CANDIDATE ou REJECTED não gera legendas."""
        clip_mode.update_clip_segment_status(self.segment_id, "CANDIDATE", db_path=self.test_db_path)
        with self.assertRaises(clip_captions.ClipCaptionError):
            clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)

        clip_mode.update_clip_segment_status(self.segment_id, "REJECTED", db_path=self.test_db_path)
        with self.assertRaises(clip_captions.ClipCaptionError):
            clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)

    def test_07_render_inexistent_does_not_break_caption_track(self):
        """7: Ausência prévia de render vertical não impede a geração da faixa de legenda."""
        track = clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(track["status"], "COMPLETED")
        self.assertTrue(os.path.isfile(track["srt_path"]))

    def test_08_source_profile_preserved(self):
        """8: source_id e profile_id são corretamente associados na track de legendas."""
        track = clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(track["source_id"], self.source_id)
        self.assertEqual(track["profile_id"], "default")

    def test_09_and_10_secondary_blocked_primary_accepted(self):
        """9 e 10: SECONDARY_VIEW_ONLY é bloqueado; PRIMARY é aceito."""
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        track = clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)
        self.assertIsNotNone(track)

    def test_11_to_19_timing_clip_relative_and_boundary_clipping(self):
        """11 a 19: Validação minuciosa de corte de timestamps e conversão clip-relative."""
        track = clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)
        cues = clip_captions.get_caption_cues(track["id"], db_path=self.test_db_path)

        self.assertGreaterEqual(len(cues), 4)

        # 13 e 14: Cues antes e depois do clip ignoradas
        all_texts = " ".join([c["text"] for c in cues])
        self.assertNotIn("fora do corte", all_texts)

        # 15: Cue parcial no início cortada (inicia em 0.0s)
        self.assertEqual(cues[0]["start_seconds"], 0.0)
        self.assertIn("Início parcial", cues[0]["text"])

        # 16: Cue parcial no fim cortada (termina em <= 30.0s)
        last_cue = cues[-1]
        self.assertLessEqual(last_cue["end_seconds"], 30.0)

        # 17, 18, 19: Invariantes temporais estritos
        for c in cues:
            self.assertGreaterEqual(c["start_seconds"], 0.0)
            self.assertGreater(c["end_seconds"], c["start_seconds"])
            self.assertLessEqual(c["end_seconds"], 30.0)

    def test_20_to_24_text_cleanup_unicode_escaping(self):
        """20 a 24: Limpeza de espaços, preservação unicode e escaping de SRT/ASS."""
        raw_text = "  Texto com {chaves} e acentuação: José & Maria.  \n Quebra  "
        cleaned = clip_captions.clean_caption_text(raw_text)
        self.assertEqual(cleaned, "Texto com {chaves} e acentuação: José & Maria.\nQuebra")

        # ASS escaping
        ass_esc = clip_captions.escape_text_for_ass(raw_text)
        self.assertIn(r"\{chaves\}", ass_esc)
        self.assertIn(r"\NQuebra", ass_esc)

        # SRT escaping
        srt_esc = clip_captions.escape_text_for_srt(raw_text)
        self.assertIn("José & Maria", srt_esc)
        self.assertIn("Quebra", srt_esc)

    def test_25_to_29_styles_and_safe_area(self):
        """25 a 29: Validação de estilos CLEAN, BOLD, estilo inválido e safe area vertical."""
        # Clean
        track_clean = clip_captions.generate_clip_captions(self.segment_id, style="CLEAN", force=True, db_path=self.test_db_path)
        self.assertEqual(track_clean["style"], "CLEAN")
        with open(track_clean["ass_path"], "r", encoding="utf-8") as f:
            ass_clean = f.read()
        self.assertIn(f",60,60,{clip_captions.SAFE_AREA_MARGIN_V},1", ass_clean)
        self.assertIn("PlayResY: 1920", ass_clean)

        # Bold
        track_bold = clip_captions.generate_clip_captions(self.segment_id, style="BOLD", force=True, db_path=self.test_db_path)
        self.assertEqual(track_bold["style"], "BOLD")
        with open(track_bold["ass_path"], "r", encoding="utf-8") as f:
            ass_bold = f.read()
        self.assertIn(",-1,0,0,0,100,100", ass_bold)

        # Invalid style
        with self.assertRaises(clip_captions.ClipCaptionError):
            clip_captions.generate_clip_captions(self.segment_id, style="NEON_CRAZY", db_path=self.test_db_path)

    def test_29_font_fallback_and_safe_resolution(self):
        """29: Valida resolução segura de fonte padrão (Arial) e fallback de fontes no ASS."""
        # Fonte padrão utilizada é Arial
        ass_default = clip_captions.generate_ass_content(cues=[])
        self.assertIn("Style: Default,Arial,", ass_default)

        # Fallback para fonte arbitrária/customizada é tratado sem exceção no gerador ASS
        ass_fallback = clip_captions.generate_ass_content(cues=[], font_name="NonExistentFallbackFont")
        self.assertIn("Style: Default,NonExistentFallbackFont,", ass_fallback)

    def test_30_and_31_srt_and_ass_created(self):
        """30 e 31: Confirma existência física e conteúdo de SRT e ASS."""
        track = clip_captions.generate_clip_captions(self.segment_id, db_path=self.test_db_path)
        self.assertTrue(os.path.isfile(track["srt_path"]))
        self.assertTrue(os.path.isfile(track["ass_path"]))

        with open(track["srt_path"], "r", encoding="utf-8") as f:
            srt = f.read()
        self.assertIn("-->", srt)

        with open(track["ass_path"], "r", encoding="utf-8") as f:
            ass = f.read()
        self.assertIn("[Script Info]", ass)
        self.assertIn("Dialogue: 0,", ass)

    def test_32_to_34_fingerprint_and_idempotency(self):
        """32 a 34: Fingerprint determinístico, force=False reutiliza, force=True cria histórico."""
        t1 = clip_captions.generate_clip_captions(self.segment_id, style="CLEAN", force=False, db_path=self.test_db_path)
        t2 = clip_captions.generate_clip_captions(self.segment_id, style="CLEAN", force=False, db_path=self.test_db_path)
        self.assertEqual(t1["id"], t2["id"])
        self.assertEqual(t1["caption_fingerprint"], t2["caption_fingerprint"])

        # force=True cria novo ID sem apagar o anterior
        t3 = clip_captions.generate_clip_captions(self.segment_id, style="CLEAN", force=True, db_path=self.test_db_path)
        self.assertNotEqual(t1["id"], t3["id"])
        self.assertEqual(t1["caption_fingerprint"], t3["caption_fingerprint"])

        all_tracks = clip_captions.list_caption_tracks_for_segment(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(len(all_tracks), 2)

    def test_35_duplicate_processing_blocked(self):
        """35: Bloqueia tentativa de processamento concorrente duplicado."""
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_caption_tracks (
                    id, segment_id, source_id, profile_id, transcript_id,
                    style, language, cue_count, duration_seconds,
                    srt_path, ass_path, caption_fingerprint, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "cap_in_progress",
                    self.segment_id,
                    self.source_id,
                    "default",
                    self.transcript_id,
                    "CLEAN",
                    "pt",
                    0,
                    30.0,
                    "/tmp/s.srt",
                    "/tmp/s.ass",
                    "dummy_fp",
                    "PROCESSING",
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        with self.assertRaises(clip_captions.DuplicateCaptionProcessingError):
            clip_captions.generate_clip_captions(self.segment_id, style="CLEAN", db_path=self.test_db_path)


if __name__ == "__main__":
    unittest.main()
