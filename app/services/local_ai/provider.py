"""
app/services/local_ai/provider.py
==================================
Provedor de IA Local compatível com OpenAI (Fase V1.4B).

Permite conectar a Video Factory a servidores locais (como llama-server)
operando estritamente em localhost/127.0.0.1, sem dependências externas pesadas
e com fail-closed para tarefas que exigem validação factual.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

from app.config import config


class LocalAIError(Exception):
    """Exceção base para erros de comunicação com a IA local."""
    pass


class LocalAIServerUnavailableError(LocalAIError):
    """Disparado quando o servidor local está inacessível ou desconectado."""
    pass


class LocalAITimeoutError(LocalAIError):
    """Disparado quando a inferência local excede o tempo limite configurado."""
    pass


class LocalAIResponseFormatError(LocalAIError):
    """Disparado quando a resposta da IA local não obedece ao formato esperado."""
    pass


class LocalAIConfig:
    """Configurações operacionais da IA local."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        # 1. enabled (padrão estrito: False para não afetar produção)
        if enabled is not None:
            self.enabled = bool(enabled)
        else:
            cfg_val = config.app.get("local_ai_enabled")
            if cfg_val is not None:
                self.enabled = bool(cfg_val)
            else:
                self.enabled = os.getenv("LOCAL_AI_ENABLED", "false").lower() in ("true", "1", "yes")

        # 2. base_url (padrão: http://127.0.0.1:8089/v1)
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = (
                config.app.get("local_ai_base_url")
                or os.getenv("LOCAL_AI_BASE_URL", "http://127.0.0.1:8089/v1")
            ).rstrip("/")

        # 3. model (padrão: qwen3-8b ou modelo configurado)
        if model:
            self.model = model
        else:
            self.model = (
                config.app.get("local_ai_model")
                or os.getenv("LOCAL_AI_MODEL", "qwen3-8b")
            )

        # 4. timeout_seconds (padrão: 120s)
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
        else:
            self.timeout_seconds = float(
                config.app.get("local_ai_timeout_seconds")
                or os.getenv("LOCAL_AI_TIMEOUT_SECONDS", "120.0")
            )

        self._validate_security()

    def _validate_security(self) -> None:
        """Garante que por padrão o endpoint aponte apenas para localhost."""
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            # Permite hosts locais privados ou em rede interna se configurado explicitamente, mas avisa
            logger.warning(
                f"[LocalAI] Atenção: base_url aponta para host não-localhost: '{hostname}'."
            )


class LocalAIResponse:
    """Encapsula a resposta de inferência da IA local com metadados."""

    def __init__(
        self,
        content: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_seconds: float = 0.0,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.content = content
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.latency_seconds = latency_seconds
        self.raw_response = raw_response or {}

    def json(self) -> Any:
        """Extrai e faz parse de JSON embutido na resposta, tratando eventuais blocos markdown."""
        text = self.content.strip()
        # Remove tags de raciocínio se presentes
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # 1. Parse direto
        try:
            return json.loads(text)
        except Exception:
            pass

        # 2. Bloco ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # 3. Primeira { até última }
        first_b = text.find("{")
        last_b = text.rfind("}")
        if first_b != -1 and last_b != -1 and last_b > first_b:
            try:
                return json.loads(text[first_b : last_b + 1])
            except Exception:
                pass

        # 4. Primeira [ até última ]
        first_sq = text.find("[")
        last_sq = text.rfind("]")
        if first_sq != -1 and last_sq != -1 and last_sq > first_sq:
            try:
                return json.loads(text[first_sq : last_sq + 1])
            except Exception:
                pass

        raise LocalAIResponseFormatError(
            f"Não foi possível extrair JSON válido da resposta da IA local: {text[:200]}..."
        )


class LocalAIProvider:
    """Cliente HTTP leve para o servidor local compatível com OpenAI."""

    def __init__(self, cfg: Optional[LocalAIConfig] = None):
        self.config = cfg or LocalAIConfig()

    def is_enabled(self) -> bool:
        """Indica se a IA local está habilitada no sistema."""
        return self.config.enabled

    def is_available(self, timeout: float = 1.5) -> bool:
        """Verifica se o servidor local está respondendo sem lançar exceções."""
        test_url = f"{self.config.base_url}/models"
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "VideoFactory-LocalAI/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            # Tenta /health como fallback
            try:
                health_url = self.config.base_url.replace("/v1", "/health")
                req2 = urllib.request.Request(health_url, headers={"User-Agent": "VideoFactory-LocalAI/1.0"})
                with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                    return resp2.status == 200
            except Exception:
                return False

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: Optional[float] = None,
    ) -> LocalAIResponse:
        """
        Executa chamada de chat completion contra o endpoint local.
        Fail-closed: em caso de indisponibilidade ou erro, lança exceção tipada.
        """
        target_model = model or self.config.model
        effective_timeout = timeout if timeout is not None else self.config.timeout_seconds
        endpoint = f"{self.config.base_url}/chat/completions"

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "VideoFactory-LocalAI/1.0",
            },
            method="POST",
        )

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw_data = resp.read().decode("utf-8")
                parsed = json.loads(raw_data)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            raise LocalAIError(
                f"Erro HTTP {e.code} da IA local ({endpoint}): {err_body[:200]}"
            ) from e
        except (TimeoutError, socket.timeout) as e:
            raise LocalAITimeoutError(
                f"Tempo limite excedido ({effective_timeout:.1f}s) aguardando IA local em {endpoint}"
            ) from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise LocalAITimeoutError(
                    f"Tempo limite excedido ({effective_timeout:.1f}s) aguardando IA local em {endpoint}"
                ) from e
            raise LocalAIServerUnavailableError(
                f"Servidor local de IA inacessível em {endpoint}: {str(e)}"
            ) from e
        except socket.error as e:
            raise LocalAIServerUnavailableError(
                f"Servidor local de IA inacessível em {endpoint}: {str(e)}"
            ) from e
        except Exception as e:
            raise LocalAIError(f"Erro inesperado ao consultar IA local: {str(e)}") from e

        dt = time.time() - t0

        choices = parsed.get("choices", [])
        if not choices:
            raise LocalAIResponseFormatError("IA local retornou resposta sem escolhas (choices vazias).")

        message = choices[0].get("message", {})
        content = message.get("content", "").strip()

        usage = parsed.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        return LocalAIResponse(
            content=content,
            model=target_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_seconds=dt,
            raw_response=parsed,
        )
