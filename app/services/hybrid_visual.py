"""
Hybrid Visual Generation Foundation (Fase V16.6).

Fornece uma arquitetura provider-agnostic para síntese e seleção visual de cenas:
1. stock (Pexels, Pixabay, biblioteca local)
2. generated_image (Nano Banana, SDXL, Flux)
3. generated_video (Wan 2.2, LTX-Video, FramePack via ComfyUI)

Princípio Fundamental:
- Não gerar 100% do vídeo por IA.
- Usar geração IA somente quando melhorar de verdade a aderência visual.
- Se o provider falhar, timeout, indisponível ou capability não suportada:
  o pipeline continua usando stock de forma resiliente e transparente.
- Nunca deixar a geração do vídeo inteiro falhar por indisponibilidade de IA.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Union
import urllib.error
import urllib.parse
import urllib.request

from loguru import logger


# =============================================================================
# Benchmark Constants (Fase V16.6.1)
# =============================================================================

STANDARD_BENCHMARK_PROMPT = (
    "large tornado rotating across rural field under dark storm clouds, "
    "cinematic realistic footage, vertical 9:16"
)

BENCHMARK_MODELS = [
    "wan_2_2",
    "ltx_video",
    "framepack",
]


# =============================================================================
# Capabilities & Data Contracts
# =============================================================================

class VisualCapability(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_VIDEO = "image_to_video"
    TEXT_TO_VIDEO = "text_to_video"
    STOCK = "stock"


@dataclass
class ProviderCapabilities:
    supports_text_to_image: bool = False
    supports_image_to_video: bool = False
    supports_text_to_video: bool = False
    supports_stock: bool = False
    max_duration_seconds: float = 10.0
    supported_aspect_ratios: List[str] = field(
        default_factory=lambda: ["9:16", "16:9", "1:1"]
    )
    requires_input_image: bool = False

    def has_capability(self, capability: Union[str, VisualCapability]) -> bool:
        cap_str = capability.value if isinstance(capability, VisualCapability) else str(capability)
        if cap_str == VisualCapability.TEXT_TO_IMAGE.value:
            return self.supports_text_to_image
        if cap_str == VisualCapability.IMAGE_TO_VIDEO.value:
            return self.supports_image_to_video
        if cap_str == VisualCapability.TEXT_TO_VIDEO.value:
            return self.supports_text_to_video
        if cap_str == VisualCapability.STOCK.value:
            return self.supports_stock
        return False


@dataclass
class GenerationRequest:
    scene_id: Union[int, str]
    prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "9:16"
    duration_seconds: float = 4.0
    seed: Optional[int] = None
    input_image_path: Optional[str] = None
    output_path: Optional[str] = None
    target_capability: VisualCapability = VisualCapability.TEXT_TO_VIDEO
    model: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationMetrics:
    generation_time_seconds: float = 0.0
    queue_time_seconds: float = 0.0
    frames_generated: int = 0
    fps: float = 0.0
    vram_peak_mb: Optional[float] = None
    ram_peak_mb: Optional[float] = None
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationResult:
    scene_id: Union[int, str]
    success: bool
    provider: str
    model: str = ""
    output_path: Optional[str] = None
    media_type: str = "video"  # "video", "image", "stock"
    metrics: GenerationMetrics = field(default_factory=GenerationMetrics)
    error: Optional[str] = None
    fallback_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["metrics"] = self.metrics.to_dict()
        return res


# =============================================================================
# Provider Interface (ABC)
# =============================================================================

class VisualGenerationProvider(ABC):
    """Interface abstrata provider-agnostic para geradores visuais."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único do provider."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Capacidades técnicas suportadas pelo provider."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Health check ou verificação de disponibilidade operacional."""
        ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Executa a geração do ativo visual."""
        ...


# =============================================================================
# Stock Visual Provider (Default baseline)
# =============================================================================

class StockVisualProvider(VisualGenerationProvider):
    """
    Provider representativo da biblioteca de stock footage (Pexels, Pixabay, etc.).
    Sempre disponível e serve como destino do fallback.
    """

    @property
    def name(self) -> str:
        return "stock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stock=True,
            max_duration_seconds=60.0,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            scene_id=request.scene_id,
            success=True,
            provider=self.name,
            model="stock_library",
            output_path=request.output_path,
            media_type="stock",
            metadata={"note": "resolved_via_stock_library"},
        )


# =============================================================================
# Nano Banana Adapter (generated_image stub / contract)
# =============================================================================

class NanoBananaImageAdapter(VisualGenerationProvider):
    """
    Adapter para o gerador de imagem Nano Banana (Fase V16.6 / V16.7.1).

    Contrato Operacional:
    - Provider opcional de imagem para keyframes e ilustrações conceituais de cena.
    - Em ambiente DEV: implementado em modo stub/configurável sem chamadas pagas.
    - Não exige credencial obrigatória agora.
    - Se a chave de API não estiver configurada, is_available() retorna False e
      o HybridVisualDirector realiza fallback seguro para stock.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: str = "https://api.nanobanana.ai/v1",
        timeout_seconds: float = 30.0,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or os.getenv("NANO_BANANA_API_KEY", "")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.mock_mode = mock_mode

    @property
    def name(self) -> str:
        return "nano_banana"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_text_to_image=True,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return bool(self.mock_mode or (self.api_key and self.api_key.strip()))

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.is_available():
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model="nano_banana_image_v1",
                fallback_reason="NANO_BANANA_NOT_CONFIGURED",
                error="Nano Banana API key not configured",
            )

        if not self.capabilities.has_capability(request.target_capability):
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model="nano_banana_image_v1",
                fallback_reason="CAPABILITY_UNSUPPORTED",
                error=f"Capability '{request.target_capability}' not supported by Nano Banana",
            )

        start_time = time.time()
        # Modo stub / mock para testes locais seguros
        if self.mock_mode:
            gen_time = round(time.time() - start_time, 3)
            out_file = request.output_path or f"storage/mock_nano_banana_scene_{request.scene_id}.png"
            return GenerationResult(
                scene_id=request.scene_id,
                success=True,
                provider=self.name,
                model="nano_banana_image_v1",
                output_path=out_file,
                media_type="image",
                metrics=GenerationMetrics(
                    generation_time_seconds=gen_time,
                    width=1080 if request.aspect_ratio == "9:16" else 1920,
                    height=1920 if request.aspect_ratio == "9:16" else 1080,
                ),
                metadata={"prompt": request.prompt, "aspect_ratio": request.aspect_ratio},
            )

        # Chamada real futura (requer credencial autorizada)
        return GenerationResult(
            scene_id=request.scene_id,
            success=False,
            provider=self.name,
            model="nano_banana_image_v1",
            fallback_reason="NANO_BANANA_STUB_MODE",
            error="Real generation not executed in DEV environment",
        )


# =============================================================================
# ComfyUI Integration (Headless / API Client)
# =============================================================================

class ComfyUIClient:
    """
    Cliente HTTP mínimo para orquestração remota/local do ComfyUI API.

    Projetado para o modelo headless no PC Forte:
    - O PC Forte executa o ComfyUI com aceleração GPU (Wan 2.2, LTX, FramePack).
    - O app envia o workflow/request via HTTP e aguarda o resultado.
    - Zero dependência pesada no notebook de desenvolvimento.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8188",
        timeout_seconds: float = 60.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def check_health(self) -> bool:
        """Verifica se o servidor ComfyUI está respondendo via /system_stats."""
        url = f"{self.endpoint}/system_stats"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
            with urllib.request.urlopen(req, timeout=min(5.0, self.timeout_seconds)) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return "system" in data or "devices" in data or isinstance(data, dict)
            return False
        except Exception as exc:
            logger.debug(f"[COMFYUI][HEALTH_CHECK_FAILED] endpoint={url} error={exc}")
            return False

    def submit_workflow(
        self,
        prompt_workflow: Dict[str, Any],
        client_id: str = "moneyprinterturbo_client",
    ) -> Dict[str, Any]:
        """Submete um workflow ComfyUI para a fila de execução via POST /prompt."""
        url = f"{self.endpoint}/prompt"
        payload = json.dumps({"prompt": prompt_workflow, "client_id": client_id}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "MoneyPrinterTurbo-VisualDirector"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                raise RuntimeError(f"ComfyUI HTTP {status}")
        except Exception as exc:
            logger.error(f"[COMFYUI][SUBMIT_FAILED] endpoint={url} error={exc}")
            raise

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """Consulta o status e histórico de execução via GET /history/{prompt_id}."""
        url = f"{self.endpoint}/history/{prompt_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                raise RuntimeError(f"ComfyUI HTTP {status}")
        except Exception as exc:
            logger.error(f"[COMFYUI][GET_HISTORY_FAILED] prompt_id={prompt_id} error={exc}")
            raise

    def poll_until_complete(
        self,
        prompt_id: str,
        poll_interval: float = 1.0,
        max_wait_seconds: float = 60.0,
    ) -> Dict[str, Any]:
        """Aguarda a conclusão do processamento em ComfyUI via polling de /history."""
        start = time.time()
        while time.time() - start < max_wait_seconds:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                prompt_data = history[prompt_id]
                if "outputs" in prompt_data and prompt_data["outputs"]:
                    return prompt_data
                status = prompt_data.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI execution error: {status.get('messages', [])}")
            time.sleep(poll_interval)
        raise TimeoutError(f"ComfyUI polling timed out after {max_wait_seconds}s for prompt_id={prompt_id}")

    def get_output_url(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> str:
        """Retorna a URL HTTP direta para download do ativo gerado via GET /view."""
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder
        return f"{self.endpoint}/view?{urllib.parse.urlencode(params)}"

    def download_output(
        self,
        filename: str,
        destination_path: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> str:
        """Faz download do ativo final gerado pelo ComfyUI para o disco local."""
        url = self.get_output_url(filename, subfolder=subfolder, folder_type=folder_type)
        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp, open(
            destination_path, "wb"
        ) as fp:
            fp.write(resp.read())
        return destination_path


# =============================================================================
# ComfyUI Visual Provider (Wan 2.2, LTX-Video, FramePack)
# =============================================================================

class ComfyUIVisualProvider(VisualGenerationProvider):
    """
    Provider para geração de vídeo acelerada via ComfyUI (Wan 2.2, LTX-Video, FramePack).
    Suporta text_to_video, image_to_video e text_to_image.
    """

    def __init__(
        self,
        client: Optional[ComfyUIClient] = None,
        endpoint: str = "http://127.0.0.1:8188",
        default_model: str = "wan_2_2",
        timeout_seconds: float = 60.0,
    ):
        self.client = client or ComfyUIClient(endpoint=endpoint, timeout_seconds=timeout_seconds)
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "comfyui"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_text_to_video=True,
            supports_image_to_video=True,
            supports_text_to_image=True,
            max_duration_seconds=10.0,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return self.client.check_health()

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.is_available():
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=request.model or self.default_model,
                fallback_reason="PROVIDER_UNAVAILABLE",
                error=f"ComfyUI endpoint {self.client.endpoint} unreachable",
            )

        if not self.capabilities.has_capability(request.target_capability):
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=request.model or self.default_model,
                fallback_reason="CAPABILITY_UNSUPPORTED",
                error=f"Capability '{request.target_capability}' not supported by ComfyUI provider",
            )

        start_time = time.time()
        model_name = request.model or self.default_model

        try:
            # Constrói workflow template representativo para a inferência
            workflow = {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": request.seed or 42,
                        "steps": 20,
                        "cfg": 7.0,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                    },
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": request.prompt},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": request.negative_prompt or "ugly, blurry, low quality"},
                },
                "meta": {
                    "model": model_name,
                    "aspect_ratio": request.aspect_ratio,
                    "duration_seconds": request.duration_seconds,
                    "capability": request.target_capability.value,
                },
            }

            sub_resp = self.client.submit_workflow(workflow)
            prompt_id = sub_resp.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"Missing prompt_id in ComfyUI response: {sub_resp}")

            history_data = self.client.poll_until_complete(
                prompt_id=prompt_id,
                poll_interval=1.0,
                max_wait_seconds=self.timeout_seconds,
            )

            # Extrai filename do output
            outputs = history_data.get("outputs", {})
            filename = f"comfyui_{model_name}_{request.scene_id}.mp4"
            subfolder = ""
            for node_id, node_out in outputs.items():
                if "gifs" in node_out and node_out["gifs"]:
                    filename = node_out["gifs"][0].get("filename", filename)
                    subfolder = node_out["gifs"][0].get("subfolder", "")
                    break
                if "images" in node_out and node_out["images"]:
                    filename = node_out["images"][0].get("filename", filename)
                    subfolder = node_out["images"][0].get("subfolder", "")
                    break

            out_path = request.output_path or f"storage/comfyui_output_{filename}"
            self.client.download_output(filename, out_path, subfolder=subfolder)

            duration = time.time() - start_time
            file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

            return GenerationResult(
                scene_id=request.scene_id,
                success=True,
                provider=self.name,
                model=model_name,
                output_path=out_path,
                media_type="video" if "video" in request.target_capability.value else "image",
                metrics=GenerationMetrics(
                    generation_time_seconds=round(duration, 3),
                    file_size_bytes=file_size,
                    frames_generated=int(request.duration_seconds * 24),
                    fps=24.0,
                ),
                metadata={
                    "prompt_id": prompt_id,
                    "prompt": request.prompt,
                    "model": model_name,
                },
            )

        except TimeoutError as exc:
            logger.warning(f"[COMFYUI][TIMEOUT] scene_id={request.scene_id} model={model_name} error={exc}")
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=model_name,
                fallback_reason="PROVIDER_TIMEOUT",
                error=str(exc),
            )
        except Exception as exc:
            logger.error(f"[COMFYUI][ERROR] scene_id={request.scene_id} model={model_name} error={exc}")
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=model_name,
                fallback_reason="GENERATION_FAILED",
                error=str(exc),
            )


# =============================================================================
# Hybrid Visual Director (Orchestrator with Resilient Fallback)
# =============================================================================

class HybridVisualDirector:
    """
    Orquestrador central de seleção e geração visual de cenas.

    Implementa a política de decisão inteligente e fail-safe:
    - visual_generation_enabled = false -> 100% stock library (comportamento atual idêntico).
    - visual_generation_enabled = true -> Tenta provider preferencial de IA.
    - Qualquer falha (indisponibilidade, timeout, erro, capability não suportada) ->
      Fallback imediato e transparente para stock.
    - O pipeline nunca falha por indisponibilidade de IA.
    """

    def __init__(
        self,
        visual_generation_enabled: bool = False,
        preferred_video_provider: str = "stock",
        preferred_image_provider: str = "nano_banana",
        providers: Optional[Dict[str, VisualGenerationProvider]] = None,
    ):
        self.visual_generation_enabled = visual_generation_enabled
        self.preferred_video_provider = preferred_video_provider
        self.preferred_image_provider = preferred_image_provider
        self.providers: Dict[str, VisualGenerationProvider] = providers or {}

    def register_provider(self, provider: VisualGenerationProvider) -> None:
        self.providers[provider.name] = provider

    def get_provider(self, name: str) -> Optional[VisualGenerationProvider]:
        return self.providers.get(name)

    def resolve_scene_visual(
        self,
        request: GenerationRequest,
        stock_resolver_fallback: Optional[Callable[[], Any]] = None,
    ) -> GenerationResult:
        """
        Resolve o ativo visual para uma cena respeitando o pipeline híbrido.
        Garante retorno de GenerationResult válido ou acionamento do fallback stock.
        """
        # 1. Se geração visual estiver desabilitada: fallback direto para stock
        if not self.visual_generation_enabled:
            logger.info(
                f"[HYBRID_VISUAL] visual_generation_enabled=False. Using stock for scene {request.scene_id}"
            )
            return self._execute_stock_fallback(
                request=request,
                reason="VISUAL_GENERATION_DISABLED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        # 2. Determina o provider candidato com base na capability requisitada
        target_cap = request.target_capability
        if target_cap == VisualCapability.TEXT_TO_IMAGE:
            provider_name = self.preferred_image_provider
        elif target_cap in (VisualCapability.TEXT_TO_VIDEO, VisualCapability.IMAGE_TO_VIDEO):
            provider_name = self.preferred_video_provider
        else:
            provider_name = "stock"

        # Se o provider preferencial for "stock", usa stock sem tentar IA
        if provider_name == "stock":
            return self._execute_stock_fallback(
                request=request,
                reason="PREFERRED_IS_STOCK",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        provider = self.get_provider(provider_name)
        if not provider:
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' not registered. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="PROVIDER_NOT_REGISTERED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        # 3. Health check prévio
        if not provider.is_available():
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' unavailable. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="PROVIDER_UNAVAILABLE",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        # 4. Verificação de capability técnica
        if not provider.capabilities.has_capability(target_cap):
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' does not support '{target_cap}'. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="CAPABILITY_UNSUPPORTED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        # 5. Tentativa de geração com tratamento robusto de exceções
        try:
            result = provider.generate(request)
            if result.success:
                logger.info(
                    f"[HYBRID_VISUAL][SUCCESS] Generated scene {request.scene_id} "
                    f"using provider={provider_name} model={result.model}"
                )
                return result
            else:
                logger.warning(
                    f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' failed "
                    f"(reason={result.fallback_reason}, error={result.error}). Fallback to stock."
                )
                return self._execute_stock_fallback(
                    request=request,
                    reason=result.fallback_reason or "GENERATION_FAILED",
                    error=result.error,
                    stock_resolver_fallback=stock_resolver_fallback,
                )
        except Exception as exc:
            logger.error(
                f"[HYBRID_VISUAL][FALLBACK] Unexpected exception in provider '{provider_name}': {exc}. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="GENERATION_EXCEPTION",
                error=str(exc),
                stock_resolver_fallback=stock_resolver_fallback,
            )

    def _execute_stock_fallback(
        self,
        request: GenerationRequest,
        reason: str,
        error: Optional[str] = None,
        stock_resolver_fallback: Optional[Callable[[], Any]] = None,
    ) -> GenerationResult:
        """Executa com segurança o fallback para material de stock."""
        fallback_path = None
        if stock_resolver_fallback:
            try:
                fallback_path = stock_resolver_fallback()
            except Exception as exc:
                logger.warning(f"[HYBRID_VISUAL] Stock fallback callback failed: {exc}")

        return GenerationResult(
            scene_id=request.scene_id,
            success=True,
            provider="stock",
            model="stock_library",
            output_path=str(fallback_path) if fallback_path else request.output_path,
            media_type="stock",
            fallback_reason=reason,
            error=error,
            metadata={
                "reason_for_generated_vs_stock": f"fallback_due_to_{reason}",
                "original_prompt": request.prompt,
            },
        )


# =============================================================================
# Factory Helper
# =============================================================================

def build_hybrid_visual_director(
    config_dict: Optional[Dict[str, Any]] = None,
) -> HybridVisualDirector:
    """
    Cria uma instância configurada do HybridVisualDirector com os providers
    padrão inicializados (Stock, Nano Banana adapter, ComfyUI provider).
    """
    cfg = config_dict or {}
    enabled = bool(cfg.get("visual_generation_enabled", False))
    preferred_video = str(cfg.get("preferred_video_provider", "stock"))
    preferred_image = str(cfg.get("preferred_image_provider", "nano_banana"))
    comfyui_endpoint = str(cfg.get("comfyui_endpoint", "http://127.0.0.1:8188"))

    director = HybridVisualDirector(
        visual_generation_enabled=enabled,
        preferred_video_provider=preferred_video,
        preferred_image_provider=preferred_image,
    )

    # Registra providers padrão
    director.register_provider(StockVisualProvider())
    director.register_provider(NanoBananaImageAdapter())
    director.register_provider(
        ComfyUIVisualProvider(
            client=ComfyUIClient(endpoint=comfyui_endpoint),
            default_model="wan_2_2",
        )
    )

    return director
