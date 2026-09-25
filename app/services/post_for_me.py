"""Post for Me API Client & YouTube Publishing Integration (Fase V15-E.2).

Contrato oficial relevante:
- Autenticação: Authorization: Bearer <POST_FOR_ME_API_KEY>
- Base URL padrão: https://api.postforme.dev/v1 (override opcional via POST_FOR_ME_BASE_URL)
- Mapeamento determinístico de contas YouTube:
  - Default: channel-default-youtube -> UCss-ng7mkGuB2v-5KKtIN9A ("Dose Diária De Internet")
  - Mistério: channel-historias-misterio-youtube -> UCGJaC83EuaOwiZ0a3-KqUZA ("Dose Diária de Histórias e mistérios")
- Resolução de conta por platform=youtube, user_id=expected_channel_id, status=connected (Fail Closed)
- Upload de mídia: POST /v1/media/create-upload-url -> PUT binário -> media_url
- Idempotência: GET /v1/social-posts?external_id=video-factory:<task_id>:youtube:<channel_id> antes de criar
- Criação: POST /v1/social-posts
- Polling com timeout bounded e erro transient para retry no scheduler sem duplicar
- Extração do YouTube Video ID nativo para publication_events.external_id
- Sanitização absoluta contra vazamento de API Key e segredos em logs e retornos
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from loguru import logger

# Base URL padrão e variáveis de ambiente
DEFAULT_BASE_URL = "https://api.postforme.dev/v1"
ENV_API_KEY = "POST_FOR_ME_API_KEY"
ENV_BASE_URL = "POST_FOR_ME_BASE_URL"

# Canais canônicos homologados
CHANNEL_DEFAULT_YOUTUBE = "channel-default-youtube"
CHANNEL_DEFAULT_YT_ID = "UCss-ng7mkGuB2v-5KKtIN9A"
CHANNEL_DEFAULT_DISPLAY = "Dose Diária De Internet"

CHANNEL_MYSTERY_YOUTUBE = "channel-historias-misterio-youtube"
CHANNEL_MYSTERY_YT_ID = "UCGJaC83EuaOwiZ0a3-KqUZA"
CHANNEL_MYSTERY_DISPLAY = "Dose Diária de Histórias e mistérios"

YOUTUBE_CHANNEL_MAP: Dict[str, Dict[str, str]] = {
    CHANNEL_DEFAULT_YOUTUBE: {
        "youtube_channel_id": CHANNEL_DEFAULT_YT_ID,
        "display_name": CHANNEL_DEFAULT_DISPLAY,
        "profile_id": "default",
    },
    CHANNEL_MYSTERY_YOUTUBE: {
        "youtube_channel_id": CHANNEL_MYSTERY_YT_ID,
        "display_name": CHANNEL_MYSTERY_DISPLAY,
        "profile_id": "profile-historias-misterio",
    },
}

ALLOWED_PRIVACY_STATUSES = {"public", "private", "unlisted"}

# Regex para extração de YouTube Video ID a partir de URLs conhecidas
_YOUTUBE_URL_REGEX = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_\-]{6,15})",
    re.IGNORECASE,
)


class PostForMeError(Exception):
    """Exceção base do Post for Me."""
    pass


class PostForMeAuthError(PostForMeError):
    """Erro de autenticação ou API Key ausente/inválida."""
    pass


class PostForMeAccountNotFoundError(PostForMeError):
    """Nenhuma conta conectada correspondente encontrada."""
    pass


class PostForMeAccountDisconnectedError(PostForMeError):
    """Conta encontrada mas está desconectada."""
    pass


class PostForMeAmbiguousAccountError(PostForMeError):
    """Mais de uma conta conectada candidata para o mesmo canal."""
    pass


class PostForMeTimeoutError(PostForMeError):
    """Timeout de polling aguardando conclusão do post (erro transitório)."""
    pass


class PostForMeUploadError(PostForMeError):
    """Falha durante upload do binário para a URL pré-assinada."""
    pass


def resolve_target_youtube_channel_id(
    channel_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve o ID do canal do YouTube nativo (UC...) de forma determinística.
    
    Aceita:
    - channel-default-youtube -> UCss-ng7mkGuB2v-5KKtIN9A
    - channel-historias-misterio-youtube -> UCGJaC83EuaOwiZ0a3-KqUZA
    - profile_id default / profile-historias-misterio se channel_id ausente
    - ID nativo direto se já começar com 'UC'
    Retorna None se não for possível mapear com certeza (Fail Closed).
    """
    c_clean = str(channel_id or "").strip()
    p_clean = str(profile_id or "").strip()

    if c_clean in YOUTUBE_CHANNEL_MAP:
        return YOUTUBE_CHANNEL_MAP[c_clean]["youtube_channel_id"]

    if c_clean.startswith("UC") and len(c_clean) >= 20:
        return c_clean

    if not c_clean or c_clean == "default":
        if p_clean in ("default", ""):
            return CHANNEL_DEFAULT_YT_ID
        elif p_clean == "profile-historias-misterio":
            return CHANNEL_MYSTERY_YT_ID

    if p_clean == "profile-historias-misterio":
        return CHANNEL_MYSTERY_YT_ID
    if p_clean == "default":
        return CHANNEL_DEFAULT_YT_ID

    return None


def sanitize_secrets(text: Any, api_key: Optional[str] = None) -> str:
    """Sanitiza strings para garantir ausência de API Keys, headers e tokens em logs/retornos."""
    msg = str(text or "")
    # Redigir qualquer Authorization header
    msg = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED_TOKEN]", msg)
    if api_key and api_key in msg:
        msg = msg.replace(api_key, "[REDACTED_API_KEY]")
    # Redigir URLs assinadas com tokens de query
    msg = re.sub(r"([?&](?:sig|signature|token|key|X-Amz-Signature)=)[^&\s]+", r"\1[REDACTED]", msg)
    return msg


def extract_youtube_video_id(data: Any) -> Optional[str]:
    """Extrai de forma determinística o video ID nativo do YouTube.
    
    Prioriza id nativo retornado em platform_data; caso indisponível, extrai da URL.
    NUNCA aceita IDs com prefixo de Post for Me (ex.: spt_..., spc_..., spr_...).
    """
    if isinstance(data, dict):
        # 1. Checa platform_data interno
        pdata = data.get("platform_data") or data.get("platformData")
        if isinstance(pdata, dict):
            pid = pdata.get("id") or pdata.get("video_id") or pdata.get("videoId")
            if pid and isinstance(pid, str) and not pid.startswith(("spt_", "spc_", "spr_")):
                return pid.strip()
            purl = pdata.get("url") or pdata.get("link") or pdata.get("video_url")
            if purl and isinstance(purl, str):
                m = _YOUTUBE_URL_REGEX.search(purl)
                if m:
                    return m.group(1)

        # 2. Checa chaves diretas
        for key in ("video_id", "videoId", "platform_post_id"):
            val = data.get(key)
            if val and isinstance(val, str) and not val.startswith(("spt_", "spc_", "spr_")):
                return val.strip()

        for key in ("url", "link", "video_url", "share_url", "external_url"):
            val = data.get(key)
            if val and isinstance(val, str):
                m = _YOUTUBE_URL_REGEX.search(val)
                if m:
                    return m.group(1)

    elif isinstance(data, str):
        m = _YOUTUBE_URL_REGEX.search(data)
        if m:
            return m.group(1)

    return None


def extract_post_result(
    data: Dict[str, Any],
    target_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Extrai e normaliza o resultado de publicação por conta.

    Aceita:
    1. SocialPostResultDto retornado por GET /v1/social-post-results
    2. SocialPostDto container com results/post_results embutidos (ou top-level fallback)

    Retorna:
    {
        "success": bool,
        "post_id": str,
        "youtube_video_id": Optional[str],
        "url": Optional[str],
        "error": Optional[str],
        "status": str,
    }
    """
    if not isinstance(data, dict):
        return {
            "success": False,
            "post_id": "",
            "youtube_video_id": None,
            "url": None,
            "error": "Dados de resultado inválidos",
            "status": "error",
        }

    # Caso 1: Objeto é diretamente um SocialPostResultDto (possui 'success' booleano e não é container)
    has_results_container = any(k in data for k in ("results", "post_results", "social_account_results"))
    if "success" in data and not has_results_container:
        success = bool(data.get("success", False))
        post_id = str(data.get("post_id") or data.get("id") or "")
        err_val = data.get("error") or data.get("message")
        if isinstance(err_val, dict):
            error = err_val.get("message") or err_val.get("error") or str(err_val)
        else:
            error = str(err_val) if err_val else None

        pdata = data.get("platform_data") or data.get("platformData")
        url = None
        if isinstance(pdata, dict):
            url = pdata.get("url") or pdata.get("link") or pdata.get("video_url")
        if not url:
            url = data.get("url") or data.get("link") or data.get("video_url")

        vid_id = extract_youtube_video_id(data)
        if not vid_id and url:
            vid_id = extract_youtube_video_id(url)

        return {
            "success": success,
            "post_id": post_id,
            "youtube_video_id": vid_id,
            "url": url,
            "error": error,
            "status": "processed" if success else "failed",
        }

    # Caso 2: Objeto é um SocialPostDto container (ou fallback)
    post_id = str(data.get("id") or "")
    post_status = str(data.get("status") or "").lower().strip()

    raw_results = (
        data.get("results")
        or data.get("post_results")
        or data.get("social_account_results")
        or []
    )

    matching_result: Optional[Dict[str, Any]] = None
    if isinstance(raw_results, list):
        if target_account_id:
            for r in raw_results:
                if isinstance(r, dict) and (
                    r.get("social_account_id") == target_account_id
                    or r.get("account_id") == target_account_id
                    or r.get("id") == target_account_id
                ):
                    matching_result = r
                    break
        if not matching_result and raw_results:
            first = raw_results[0]
            if isinstance(first, dict):
                matching_result = first
    elif isinstance(raw_results, dict):
        if target_account_id and target_account_id in raw_results:
            matching_result = raw_results[target_account_id]
        elif "youtube" in raw_results:
            matching_result = raw_results["youtube"]
        elif raw_results:
            first_val = next(iter(raw_results.values()))
            if isinstance(first_val, dict):
                matching_result = first_val

    success = False
    error: Optional[str] = None
    url: Optional[str] = None
    vid_id: Optional[str] = None

    if matching_result:
        success = bool(matching_result.get("success", False))
        err_val = matching_result.get("error") or matching_result.get("message")
        if isinstance(err_val, dict):
            error = err_val.get("message") or err_val.get("error") or str(err_val)
        else:
            error = str(err_val) if err_val else None

        pdata = matching_result.get("platform_data") or matching_result.get("platformData")
        if isinstance(pdata, dict):
            url = pdata.get("url") or pdata.get("link") or pdata.get("video_url")
        if not url:
            url = (
                matching_result.get("url")
                or matching_result.get("link")
                or matching_result.get("video_url")
            )
        vid_id = extract_youtube_video_id(matching_result)
    else:
        # Fallback para campos top-level do post se não houver array de results
        if post_status in ("completed", "posted", "success", "published"):
            success = True
        elif post_status in ("failed", "error"):
            success = False
            error = str(data.get("error") or data.get("message") or "publication failed")

        url = data.get("url") or data.get("link")
        vid_id = extract_youtube_video_id(data)

    if not vid_id and url:
        vid_id = extract_youtube_video_id(url)

    return {
        "success": success,
        "post_id": post_id,
        "youtube_video_id": vid_id,
        "url": url,
        "error": error,
        "status": post_status,
    }


class PostForMeClient:
    """Cliente HTTP para Post for Me API v1."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        self._api_key = (api_key or os.environ.get(ENV_API_KEY, "")).strip()
        self._base_url = (base_url or os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL)).strip().rstrip("/")
        self._timeout = timeout

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def base_url(self) -> str:
        return self._base_url

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise PostForMeAuthError("POST_FOR_ME_API_KEY ausente ou não configurada.")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        req_timeout = timeout or self._timeout
        headers = self._headers()

        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=req_timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise PostForMeTimeoutError(f"timeout: Post for Me request to {path} timed out: {sanitize_secrets(exc, self._api_key)}") from exc
        except requests.exceptions.RequestException as exc:
            msg = sanitize_secrets(str(exc), self._api_key)
            raise PostForMeError(f"connection/network error communicating with Post for Me: {msg}") from exc

        if not resp.ok:
            status_code = resp.status_code
            err_body = sanitize_secrets(resp.text, self._api_key)
            if status_code in (401, 403):
                raise PostForMeAuthError(f"Post for Me auth failed ({status_code}): {err_body}")
            if status_code == 429:
                raise PostForMeError(f"429 rate limit exceeded: {err_body}")
            if status_code >= 500:
                raise PostForMeError(f"{status_code} server error: {err_body}")
            raise PostForMeError(f"Post for Me API error ({status_code}): {err_body}")

        try:
            return resp.json()
        except Exception as exc:
            raise PostForMeError(f"Invalid JSON returned from Post for Me: {sanitize_secrets(exc, self._api_key)}") from exc

    def list_social_accounts(self, platform: str = "youtube") -> List[Dict[str, Any]]:
        """Consulta as contas sociais conectadas, filtrando por plataforma quando aplicável."""
        params = {"platform": platform} if platform else None
        res = self._request("GET", "/social-accounts", params=params)
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            return res.get("data") or res.get("accounts") or res.get("items") or []
        return []

    def resolve_youtube_account(self, expected_channel_id: str) -> Dict[str, Any]:
        """Resolve a conta conectada de forma DETERMINÍSTICA.
        
        Garantias:
        - platform == 'youtube'
        - user_id == expected_channel_id
        - status == 'connected'
        - NUNCA resolve somente por username/display name
        - FAIL CLOSED se 0 ou >1 contas ou se disconnected
        """
        if not expected_channel_id:
            raise PostForMeAccountNotFoundError("Canal do YouTube esperado não fornecido para resolução.")

        accounts = self.list_social_accounts(platform="youtube")
        candidates: List[Dict[str, Any]] = []

        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            plat = str(acc.get("platform") or acc.get("provider") or "").lower().strip()
            if plat != "youtube":
                continue

            user_id = str(
                acc.get("user_id")
                or acc.get("account_id")
                or acc.get("channel_id")
                or acc.get("external_id")
                or ""
            ).strip()

            status = str(acc.get("status") or "").lower().strip()

            if user_id == expected_channel_id:
                if status != "connected":
                    raise PostForMeAccountDisconnectedError(
                        f"Conta Post for Me para o canal {expected_channel_id} está desconectada (status: {status})."
                    )
                candidates.append(acc)

        if not candidates:
            raise PostForMeAccountNotFoundError(
                f"Nenhuma conta Post for Me conectada encontrada para o canal YouTube: {expected_channel_id}"
            )

        if len(candidates) > 1:
            raise PostForMeAmbiguousAccountError(
                f"Múltiplas contas Post for Me conectadas ({len(candidates)}) encontradas para o canal {expected_channel_id}. Bloqueando por ambiguidade."
            )

        account = candidates[0]
        acc_id = account.get("id")
        if not acc_id:
            raise PostForMeAccountNotFoundError(f"Conta resolvida para {expected_channel_id} não possui 'id' interno.")

        return account

    def create_media_upload_url(self, content_type: str = "video/mp4") -> Tuple[str, str]:
        """Solicita URLs para upload temporário de mídia.
        
        Retorna (upload_url, media_url).
        """
        payload = {"content_type": content_type}
        res = self._request("POST", "/media/create-upload-url", json_data=payload)
        
        data_dict = res.get("data") if isinstance(res, dict) and isinstance(res.get("data"), dict) else res
        if not isinstance(data_dict, dict):
            raise PostForMeUploadError("Resposta inválida ao criar upload url")

        upload_url = data_dict.get("upload_url") or data_dict.get("uploadUrl")
        media_url = data_dict.get("media_url") or data_dict.get("mediaUrl")

        if not upload_url or not media_url:
            raise PostForMeUploadError("upload_url ou media_url ausentes na resposta de create-upload-url")

        return str(upload_url), str(media_url)

    def upload_media_binary(self, upload_url: str, video_path: str) -> None:
        """Executa PUT do arquivo binário na URL pré-assinada."""
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {video_path}")
        if os.path.getsize(video_path) == 0:
            raise ValueError(f"Arquivo de vídeo vazio (0 bytes): {video_path}")

        try:
            with open(video_path, "rb") as f:
                headers = {"Content-Type": "video/mp4"}
                resp = requests.put(upload_url, data=f, headers=headers, timeout=300)
                resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            msg = sanitize_secrets(str(exc), self._api_key)
            raise PostForMeUploadError(f"Falha no PUT binário para media upload: {msg}") from exc

    def get_social_post_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        """Consulta posts existentes com o external_id determinístico para idempotência."""
        res = self._request("GET", "/social-posts", params={"external_id": external_id})
        items: List[Dict[str, Any]] = []
        if isinstance(res, list):
            items = res
        elif isinstance(res, dict):
            items = res.get("data") or res.get("items") or res.get("posts") or []
            if not items and res.get("id") and res.get("external_id") == external_id:
                return res

        for item in items:
            if isinstance(item, dict) and item.get("external_id") == external_id:
                return item

        return None

    def get_social_post(self, post_id: str) -> Dict[str, Any]:
        """Consulta o estado e resultados de um social-post por ID."""
        res = self._request("GET", f"/social-posts/{post_id}")
        if isinstance(res, dict) and isinstance(res.get("data"), dict):
            return res["data"]
        if isinstance(res, dict):
            return res
        raise PostForMeError(f"Resposta inesperada ao consultar social-post {post_id}")

    def list_social_post_results(
        self,
        post_id: Optional[str] = None,
        social_account_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta resultados individuais de publicação via GET /v1/social-post-results."""
        params: Dict[str, Any] = {}
        if post_id:
            params["post_id"] = post_id
        if social_account_id:
            params["social_account_id"] = social_account_id
        if platform:
            params["platform"] = platform

        res = self._request("GET", "/social-post-results", params=params or None)
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            return res.get("data") or res.get("items") or res.get("results") or []
        return []

    def get_post_result_for_account(
        self,
        post_id: str,
        social_account_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Recupera o Post Result associado ao social post e social account alvo."""
        results = self.list_social_post_results(
            post_id=post_id,
            social_account_id=social_account_id,
        )
        if not results:
            return None

        if social_account_id:
            for r in results:
                if isinstance(r, dict) and (
                    r.get("social_account_id") == social_account_id
                    or r.get("account_id") == social_account_id
                    or r.get("id") == social_account_id
                ):
                    return r
        # Retorna o primeiro resultado se não encontrar por ID exato
        if results and isinstance(results[0], dict):
            return results[0]
        return None

    def create_social_post(
        self,
        caption: str,
        social_account_id: str,
        media_url: str,
        title: str,
        privacy_status: str,
        external_id: str,
        made_for_kids: bool = False,
    ) -> Dict[str, Any]:
        """Cria um novo post na Post for Me respeitando o contrato oficial."""
        clean_privacy = str(privacy_status or "").lower().strip()
        if clean_privacy not in ALLOWED_PRIVACY_STATUSES:
            raise ValueError(
                f"privacy_status inválido '{privacy_status}'. Deve ser um de: {sorted(ALLOWED_PRIVACY_STATUSES)}"
            )

        payload = {
            "caption": caption,
            "social_accounts": [social_account_id],
            "media": [{"url": media_url}],
            "external_id": external_id,
            "platform_configurations": {
                "youtube": {
                    "title": title[:100],  # Limite oficial do YouTube
                    "privacy_status": clean_privacy,
                    "made_for_kids": bool(made_for_kids),
                }
            },
        }

        res = self._request("POST", "/social-posts", json_data=payload)
        if isinstance(res, dict) and isinstance(res.get("data"), dict):
            return res["data"]
        if isinstance(res, dict):
            return res
        raise PostForMeError("Resposta inválida na criação de social-post")

    def poll_social_post(
        self,
        post_id: str,
        timeout_sec: int = 120,
        poll_interval_sec: float = 2.0,
    ) -> Dict[str, Any]:
        """Executa polling limitado aguardando a publicação atingir estado terminal."""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout_sec:
            post = self.get_social_post(post_id)
            status = str(post.get("status") or "").lower().strip()

            if status in ("processed", "completed", "posted", "success", "published", "done"):
                return post
            if status in ("failed", "error"):
                return post

            time.sleep(poll_interval_sec)

        raise PostForMeTimeoutError(
            f"timeout: Post for Me post {post_id} still processing after {timeout_sec}s"
        )

    def publish_video(
        self,
        video_path: str,
        title: str,
        caption: str,
        channel_id: str,
        task_id: str,
        privacy_status: str = "public",
        made_for_kids: bool = False,
        profile_id: Optional[str] = None,
        timeout_sec: int = 120,
        poll_interval_sec: float = 2.0,
    ) -> Dict[str, Any]:
        """Fluxo completo de publicação no YouTube via Post for Me com proteção de idempotência."""
        # 1. Validação de API Key
        if not self.is_configured():
            logger.error("[POST_FOR_ME] Tentativa de publicação sem POST_FOR_ME_API_KEY configurada.")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": None,
                "external_id": None,
                "external_url": None,
                "privacy_status": privacy_status,
                "error": "POST_FOR_ME_API_KEY ausente ou não configurada.",
                "error_code": "AUTH_CONFIG_MISSING",
            }

        # 2. Resolução do canal nativo do YouTube
        expected_yt_id = resolve_target_youtube_channel_id(channel_id=channel_id, profile_id=profile_id)
        if not expected_yt_id:
            msg = f"Canal do YouTube não pôde ser resolvido para channel_id='{channel_id}', profile_id='{profile_id}'."
            logger.error(f"[POST_FOR_ME] {msg}")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": None,
                "external_id": None,
                "external_url": None,
                "privacy_status": privacy_status,
                "error": msg,
                "error_code": "CHANNEL_RESOLUTION_FAILED",
            }

        # 3. Validação estrita de privacidade
        clean_privacy = str(privacy_status or "public").lower().strip()
        if clean_privacy not in ALLOWED_PRIVACY_STATUSES:
            msg = f"privacy_status inválido: '{privacy_status}'. Opções: {sorted(ALLOWED_PRIVACY_STATUSES)}"
            logger.error(f"[POST_FOR_ME] {msg}")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": None,
                "external_id": None,
                "external_url": None,
                "privacy_status": clean_privacy,
                "error": msg,
                "error_code": "INVALID_PRIVACY_STATUS",
            }

        # 4. Resolução da conta Post for Me correspondente (Fail closed)
        try:
            account = self.resolve_youtube_account(expected_yt_id)
            social_account_id = str(account.get("id"))
        except (
            PostForMeAccountNotFoundError,
            PostForMeAccountDisconnectedError,
            PostForMeAmbiguousAccountError,
            PostForMeAuthError,
            PostForMeError,
        ) as exc:
            msg = sanitize_secrets(str(exc), self._api_key)
            logger.error(f"[POST_FOR_ME] Falha na resolução da conta YouTube: {msg}")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": None,
                "external_id": None,
                "external_url": None,
                "privacy_status": clean_privacy,
                "error": msg,
                "error_code": type(exc).__name__,
            }

        # 5. External ID determinístico para idempotência
        ext_channel_id = channel_id or ("channel-default-youtube" if expected_yt_id == CHANNEL_DEFAULT_YT_ID else "channel-historias-misterio-youtube")
        deterministic_external_id = f"video-factory:{task_id}:youtube:{ext_channel_id}"

        post_id: Optional[str] = None
        try:
            # Consulta se post com mesmo external_id já existe
            existing_post = self.get_social_post_by_external_id(deterministic_external_id)
            if existing_post and existing_post.get("id"):
                post_id = str(existing_post["id"])
                logger.info(
                    f"[POST_FOR_ME] Post existente encontrado para external_id '{deterministic_external_id}' "
                    f"(id: {post_id}). Reutilizando post sem duplicar upload."
                )
            else:
                # Fluxo de upload de mídia
                upload_url, media_url = self.create_media_upload_url(content_type="video/mp4")
                self.upload_media_binary(upload_url, video_path)

                # Criação do social-post
                new_post = self.create_social_post(
                    caption=caption,
                    social_account_id=social_account_id,
                    media_url=media_url,
                    title=title,
                    privacy_status=clean_privacy,
                    external_id=deterministic_external_id,
                    made_for_kids=made_for_kids,
                )
                post_id = str(new_post.get("id"))
                logger.info(f"[POST_FOR_ME] Social post criado com sucesso. id: {post_id}")

            # 6. Polling do resultado aguardando estado terminal do post
            final_post = self.poll_social_post(
                post_id,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
            )

            # 7. Consulta do Post Result correspondente via GET /v1/social-post-results
            post_result = None
            try:
                post_result = self.get_post_result_for_account(
                    post_id=post_id,
                    social_account_id=social_account_id,
                )
            except Exception as exc:
                logger.warning(
                    f"[POST_FOR_ME] Falha ao consultar post-results separados para post {post_id}: "
                    f"{sanitize_secrets(exc, self._api_key)}"
                )

            # 8. Extração e avaliação do resultado
            if post_result:
                res_info = extract_post_result(post_result, target_account_id=social_account_id)
            else:
                res_info = extract_post_result(final_post, target_account_id=social_account_id)

            if res_info["success"]:
                vid_id = res_info.get("youtube_video_id")
                ext_url = res_info.get("url")
                if not ext_url and vid_id:
                    ext_url = f"https://www.youtube.com/watch?v={vid_id}"

                if not vid_id:
                    logger.warning(
                        f"[POST_FOR_ME] Publicação confirmada com sucesso (id: {post_id}), "
                        f"mas YouTube Video ID nativo não pôde ser extraído da resposta/URL."
                    )

                return {
                    "success": True,
                    "provider": "post_for_me",
                    "request_id": post_id,
                    "external_id": vid_id,
                    "external_url": ext_url,
                    "privacy_status": clean_privacy,
                    "error": None,
                    "error_code": None,
                }
            else:
                err_msg = res_info.get("error") or "Post for Me reportou falha na publicação."
                logger.error(f"[POST_FOR_ME] Falha no resultado do post {post_id}: {err_msg}")
                return {
                    "success": False,
                    "provider": "post_for_me",
                    "request_id": post_id,
                    "external_id": None,
                    "external_url": None,
                    "privacy_status": clean_privacy,
                    "error": str(err_msg),
                    "error_code": "POST_RESULT_FAILED",
                }

        except PostForMeTimeoutError as exc:
            msg = sanitize_secrets(str(exc), self._api_key)
            logger.warning(f"[POST_FOR_ME] {msg}")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": post_id,
                "external_id": None,
                "external_url": None,
                "privacy_status": clean_privacy,
                "error": msg,
                "error_code": "POLLING_TIMEOUT",
            }
        except Exception as exc:
            msg = sanitize_secrets(str(exc), self._api_key)
            logger.error(f"[POST_FOR_ME] Erro durante publicação: {msg}")
            return {
                "success": False,
                "provider": "post_for_me",
                "request_id": post_id,
                "external_id": None,
                "external_url": None,
                "privacy_status": clean_privacy,
                "error": msg,
                "error_code": type(exc).__name__,
            }


# Instância global padrão do cliente
post_for_me_client = PostForMeClient()
