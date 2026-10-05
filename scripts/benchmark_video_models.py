#!/usr/bin/env python3
"""
Open-Source Video Generation Benchmark Harness (Fase V16.6.1).

Prepara e padroniza o benchmark comparativo para modelos open-source de vídeo:
1. Wan 2.2 (Alibaba)
2. LTX-Video (Lightricks)
3. FramePack

Contrato Operacional:
- Execução real em GPU (VRAM intensiva) será executada no PC Forte.
- No ambiente DEV: suporta modo `--dry-run` para validar métricas, estrutura,
  formatos JSON/CSV e pipeline sem requerer GPU nem baixar pesos gigantes.
- Utiliza rigorosamente o mesmo cenário/prompt para todos os modelos:
  "large tornado rotating across rural field under dark storm clouds, cinematic realistic footage, vertical 9:16"
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Garante path de importação do MoneyPrinterTurbo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from app.services.hybrid_visual import (
    ComfyUIClient,
    ComfyUIVisualProvider,
    GenerationRequest,
    VisualCapability,
)

# Cenário Canônico Padronizado
STANDARD_BENCHMARK_PROMPT = (
    "large tornado rotating across rural field under dark storm clouds, "
    "cinematic realistic footage, vertical 9:16"
)

BENCHMARK_MODELS = [
    "wan_2_2",
    "ltx_video",
    "framepack",
]


@dataclass
class BenchmarkEntry:
    model: str
    provider: str
    prompt: str
    aspect_ratio: str
    target_duration_seconds: float
    output_resolution: str
    generation_time_seconds: float
    startup_load_time_seconds: float
    frames_generated: int
    fps: float
    file_size_bytes: int
    vram_peak_mb: Optional[float] = None
    ram_peak_mb: Optional[float] = None
    success: bool = False
    error: Optional[str] = None
    output_path: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Subjective Quality Placeholders (para anotação manual ou avaliação multimodal)
    subjective_quality: Optional[float] = None  # Escala 1 a 5
    prompt_adherence: Optional[float] = None    # Escala 1 a 5
    temporal_consistency: Optional[float] = None  # Escala 1 a 5
    realism: Optional[float] = None             # Escala 1 a 5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_current_vram_mb() -> Optional[float]:
    """Coleta o pico de VRAM alocada se PyTorch + CUDA estiverem disponíveis."""
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2)
    except Exception:
        pass
    return None


def get_current_ram_mb() -> Optional[float]:
    """Coleta o uso de memória RAM do processo se psutil estiver disponível."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        pass
    return None


class VideoBenchmarkRunner:
    """
    Executor do benchmark padronizado para modelos de vídeo.
    Gera relatórios estruturados em JSON e CSV com métricas de desempenho.
    """

    def __init__(
        self,
        comfyui_endpoint: str = "http://127.0.0.1:8188",
        output_dir: str = "storage/benchmarks",
        dry_run: bool = False,
    ):
        self.comfyui_endpoint = comfyui_endpoint
        self.output_dir = output_dir
        self.dry_run = dry_run
        self.client = ComfyUIClient(endpoint=comfyui_endpoint)
        os.makedirs(self.output_dir, exist_ok=True)

    def run_model_benchmark(
        self,
        model_name: str,
        prompt: str = STANDARD_BENCHMARK_PROMPT,
        aspect_ratio: str = "9:16",
        duration_seconds: float = 4.0,
    ) -> BenchmarkEntry:
        """Executa a medição de uma única configuração de modelo."""
        logger.info(
            f"[BENCHMARK][START] model={model_name} duration={duration_seconds}s "
            f"aspect={aspect_ratio} dry_run={self.dry_run}"
        )

        resolution = "720x1280" if aspect_ratio == "9:16" else "1280x720"
        expected_frames = int(duration_seconds * 24)

        if self.dry_run:
            # Simulação determinística para validação em DEV sem GPU
            simulated_gen_times = {
                "wan_2_2": 24.5,
                "ltx_video": 12.8,
                "framepack": 18.2,
            }
            simulated_vram = {
                "wan_2_2": 14200.0,
                "ltx_video": 9800.0,
                "framepack": 11500.0,
            }
            gen_time = simulated_gen_times.get(model_name, 15.0)
            vram = simulated_vram.get(model_name, 8000.0)

            mock_output_path = os.path.join(
                self.output_dir, f"dry_run_{model_name}_tornado.mp4"
            )
            # Cria arquivo representativo vazio para simular output
            with open(mock_output_path, "wb") as f:
                f.write(b"\x00" * 1024)

            entry = BenchmarkEntry(
                model=model_name,
                provider="comfyui_headless",
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                target_duration_seconds=duration_seconds,
                output_resolution=resolution,
                generation_time_seconds=gen_time,
                startup_load_time_seconds=2.5,
                frames_generated=expected_frames,
                fps=24.0,
                file_size_bytes=1024,
                vram_peak_mb=vram,
                ram_peak_mb=get_current_ram_mb() or 512.0,
                success=True,
                output_path=mock_output_path,
            )
            logger.info(
                f"[BENCHMARK][DRY_RUN_SUCCESS] model={model_name} gen_time={gen_time}s vram={vram}MB"
            )
            return entry

        # Execução Real via ComfyUI
        t_start = time.time()
        provider = ComfyUIVisualProvider(
            client=self.client,
            default_model=model_name,
        )

        if not provider.is_available():
            return BenchmarkEntry(
                model=model_name,
                provider="comfyui_headless",
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                target_duration_seconds=duration_seconds,
                output_resolution=resolution,
                generation_time_seconds=0.0,
                startup_load_time_seconds=0.0,
                frames_generated=0,
                fps=0.0,
                file_size_bytes=0,
                success=False,
                error=f"ComfyUI server at {self.comfyui_endpoint} not reachable",
            )

        req = GenerationRequest(
            scene_id=f"bench_{model_name}",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            target_capability=VisualCapability.TEXT_TO_VIDEO,
            model=model_name,
            output_path=os.path.join(self.output_dir, f"{model_name}_tornado.mp4"),
        )

        res = provider.generate(req)
        total_time = round(time.time() - t_start, 3)

        return BenchmarkEntry(
            model=model_name,
            provider="comfyui_headless",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            target_duration_seconds=duration_seconds,
            output_resolution=resolution,
            generation_time_seconds=res.metrics.generation_time_seconds or total_time,
            startup_load_time_seconds=round(max(0.0, total_time - (res.metrics.generation_time_seconds or total_time)), 3),
            frames_generated=res.metrics.frames_generated or expected_frames,
            fps=res.metrics.fps or 24.0,
            file_size_bytes=res.metrics.file_size_bytes or 0,
            vram_peak_mb=get_current_vram_mb(),
            ram_peak_mb=get_current_ram_mb(),
            success=res.success,
            error=res.error,
            output_path=res.output_path,
        )

    def run_benchmark_suite(
        self,
        models: Optional[List[str]] = None,
        prompt: str = STANDARD_BENCHMARK_PROMPT,
        aspect_ratio: str = "9:16",
        duration_seconds: float = 4.0,
    ) -> List[BenchmarkEntry]:
        """Executa a suíte de benchmark completa para todos os modelos configurados."""
        models_to_test = models or BENCHMARK_MODELS
        results: List[BenchmarkEntry] = []

        logger.info(f"[BENCHMARK_SUITE] Running benchmark for models: {models_to_test}")
        for model in models_to_test:
            entry = self.run_model_benchmark(
                model_name=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
            )
            results.append(entry)

        return results

    def save_reports(
        self,
        entries: List[BenchmarkEntry],
        prefix: str = "benchmark_results",
    ) -> Dict[str, str]:
        """Salva os relatórios nos formatos JSON e CSV estruturados."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(self.output_dir, f"{prefix}_{timestamp}.json")
        csv_path = os.path.join(self.output_dir, f"{prefix}_{timestamp}.csv")

        # 1. Salva JSON
        data = {
            "timestamp": timestamp,
            "prompt": entries[0].prompt if entries else STANDARD_BENCHMARK_PROMPT,
            "models_tested": [e.model for e in entries],
            "dry_run": self.dry_run,
            "results": [e.to_dict() for e in entries],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # 2. Salva CSV
        if entries:
            fieldnames = list(entries[0].to_dict().keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for e in entries:
                    writer.writerow(e.to_dict())

        logger.info(f"[BENCHMARK_REPORTS] Saved JSON: {json_path}")
        logger.info(f"[BENCHMARK_REPORTS] Saved CSV: {csv_path}")

        return {"json": json_path, "csv": csv_path}


def main():
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo Open-Source Video Benchmark")
    parser.add_argument(
        "--models",
        type=str,
        default="wan_2_2,ltx_video,framepack",
        help="Comma-separated model names to benchmark",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=STANDARD_BENCHMARK_PROMPT,
        help="Prompt used for the benchmark generation",
    )
    parser.add_argument(
        "--aspect-ratio",
        type=str,
        default="9:16",
        choices=["9:16", "16:9", "1:1"],
        help="Target aspect ratio",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=4.0,
        help="Duration of the generated video in seconds (clamped to 3-5s)",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="http://127.0.0.1:8188",
        help="ComfyUI server endpoint",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="storage/benchmarks",
        help="Directory to save benchmark reports and video outputs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run simulated benchmark without requiring GPU inference",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON results to stdout",
    )

    args = parser.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    duration = max(3.0, min(5.0, args.duration))

    runner = VideoBenchmarkRunner(
        comfyui_endpoint=args.endpoint,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )

    results = runner.run_benchmark_suite(
        models=models,
        prompt=args.prompt,
        aspect_ratio=args.aspect_ratio,
        duration_seconds=duration,
    )

    reports = runner.save_reports(results)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))

    print("\n=== Benchmark Complete ===")
    print(f"Models Tested: {', '.join(models)}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Reports: {reports['json']} | {reports['csv']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
