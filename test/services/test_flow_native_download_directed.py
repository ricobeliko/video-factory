import http.server
import os
import socketserver
import tempfile
import threading
import time
import unittest
from typing import Optional

from playwright.sync_api import sync_playwright

from scripts.flow_playwright import (
    _persist_download,
    launch_flow_context,
    validate_clip_file,
)


class TestFlowNativeDownloadDirected(unittest.TestCase):
    """
    Validação local dirigida com browser real (Edge headless), sem Google Flow e sem créditos.
    Comprova que:
    1. playwright_downloads e native_download_staging são diretórios isolados e distintos.
    2. Downloads gravados via CDP no native_download_staging sobrevivem ao fechamento abrupto da página/target.
    3. download.save_as() falha com TargetClosedError após o fechamento do target.
    4. O artefato concluído no native_download_staging permanece intacto no disco.
    5. _persist_download() recupera o arquivo do staging nativo e gera o canonical válido.
    """

    server: Optional[socketserver.TCPServer] = None
    server_thread: Optional[threading.Thread] = None
    port: int = 0
    test_video_bytes: bytes = b""

    @classmethod
    def setUpClass(cls):
        # Carrega amostra de vídeo real para validação estrita de ffprobe/validate_clip_file
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sample_path = os.path.join(
            repo_root, "storage", "thematic_scene_3_nasa_PIA10063_motion.mp4"
        )
        if os.path.exists(sample_path):
            with open(sample_path, "rb") as f:
                cls.test_video_bytes = f.read()
        else:
            cls.test_video_bytes = (
                b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42" + b"V" * 4096
            )

        video_bytes = cls.test_video_bytes

        class DownloadHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="sample_clip.mp4"'
                )
                self.send_header("Content-Length", str(len(video_bytes)))
                self.end_headers()
                self.wfile.write(video_bytes)

            def log_message(self, format, *args):
                pass  # silencia logs do servidor local

        cls.server = socketserver.TCPServer(("127.0.0.1", 0), DownloadHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()

    def test_native_cdp_staging_survives_target_closed(self):
        """Prova que o artefato no native_download_staging sobrevive ao TargetClosedError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_data_dir = os.path.join(tmp_dir, "edge_profile")
            pw_downloads_dir = os.path.join(tmp_dir, "playwright_downloads")
            native_staging_dir = os.path.join(
                tmp_dir, "native_download_staging", "run_directed_01"
            )
            canonical_out = os.path.join(
                tmp_dir, "canonical_clips", "flow_scene_directed.mp4"
            )

            os.makedirs(pw_downloads_dir, exist_ok=True)
            os.makedirs(native_staging_dir, exist_ok=True)
            os.makedirs(os.path.dirname(canonical_out), exist_ok=True)

            # 1. Prova que os diretórios são fisicamente e conceitualmente distintos
            self.assertNotEqual(
                os.path.abspath(pw_downloads_dir),
                os.path.abspath(native_staging_dir),
            )
            self.assertFalse(
                os.path.abspath(native_staging_dir).startswith(
                    os.path.abspath(pw_downloads_dir)
                )
            )

            with sync_playwright() as p:
                # 2. Inicializa Edge via launch_flow_context apontando downloads_path apenas para pw_downloads_dir
                context, err = launch_flow_context(
                    p,
                    user_data_dir=user_data_dir,
                    headless=True,
                    downloads_path=pw_downloads_dir,
                )
                self.assertIsNone(err)
                self.assertIsNotNone(context)

                page = context.pages[0] if context.pages else context.new_page()

                # 3. Configura CDP para direcionar downloads nativos do Chromium exclusivamente para native_staging_dir
                cdp = context.new_cdp_session(page)
                cdp.send(
                    "Page.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": os.path.abspath(native_staging_dir),
                    },
                )
                try:
                    cdp.send(
                        "Browser.setDownloadBehavior",
                        {
                            "behavior": "allow",
                            "downloadPath": os.path.abspath(native_staging_dir),
                            "eventsEnabled": True,
                        },
                    )
                except Exception:
                    pass

                # 4. Navega para página local e dispara download
                page.set_content(f"""
                    <html>
                    <body>
                        <a id="dl_link" href="http://127.0.0.1:{self.port}/sample_clip.mp4" download="sample_clip.mp4">
                            Baixar Clipe
                        </a>
                    </body>
                    </html>
                """)

                with page.expect_download(timeout=10000) as dl_info:
                    page.click("#dl_link")
                download = dl_info.value
                self.assertEqual(download.suggested_filename, "sample_clip.mp4")

                # 5. Aguarda conclusão do download nativo no staging (sem .crdownload)
                t_deadline = time.time() + 10.0
                staged_files = []
                while time.time() < t_deadline:
                    staged_files = [
                        f
                        for f in os.listdir(native_staging_dir)
                        if not f.endswith(".crdownload") and not f.startswith(".")
                    ]
                    if staged_files:
                        break
                    time.sleep(0.2)

                self.assertEqual(
                    len(staged_files),
                    1,
                    f"Esperado exatamente 1 arquivo concluído no staging nativo, obtido: {staged_files}",
                )
                self.assertEqual(staged_files[0], "sample_clip.mp4")

                # 6. Provoca fechamento abrupto do target/page e context
                page.close()
                context.close()

                # 7. Verifica que save_as() e path() falham com TargetClosedError (reproduzindo produção)
                save_as_failed = False
                try:
                    download.save_as(canonical_out)
                except Exception as exc:
                    save_as_failed = True
                    self.assertIn("closed", str(exc).lower())

                self.assertTrue(
                    save_as_failed,
                    "download.save_as() deveria ter falhado com TargetClosedError após encerramento do target/context",
                )

                # 8. PROVA DE SOBREVIVÊNCIA: o arquivo no native_staging_dir SOBREVIVEU fisicamente
                staged_after_close = os.listdir(native_staging_dir)
                self.assertIn(
                    "sample_clip.mp4",
                    staged_after_close,
                    "O arquivo sample_clip.mp4 DEVE sobreviver fisicamente no native_download_staging após o fechamento do target!",
                )

                # 9. PROVA DE ISOLAMENTO: playwright_downloads NÃO contém o arquivo
                pw_files = os.listdir(pw_downloads_dir)
                self.assertNotIn("sample_clip.mp4", pw_files)

                # 10. O arquivo no native staging continua intacto
                staged_after_context_close = os.listdir(native_staging_dir)
                self.assertIn(
                    "sample_clip.mp4",
                    staged_after_context_close,
                    "O arquivo DEVE permanecer no native staging mesmo após encerramento completo do contexto Playwright!",
                )

                # 12. _persist_download recupera com sucesso o arquivo do native staging
                ok, persist_err = _persist_download(
                    download,
                    canonical_out,
                    staging_dir=native_staging_dir,
                    timeout_ms=5000,
                )
                self.assertTrue(ok, f"Persistência falhou: {persist_err}")
                self.assertIsNone(persist_err)
                self.assertTrue(os.path.exists(canonical_out))

                # 13. Canonical é validado
                val = validate_clip_file(canonical_out)
                self.assertTrue(val.get("valid"), f"Clipe canonical inválido: {val}")
                self.assertEqual(os.path.getsize(canonical_out), len(self.test_video_bytes))


if __name__ == "__main__":
    unittest.main()
