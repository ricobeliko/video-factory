"""Fundação do Publicador Direto do YouTube via YouTube Data API v3 (Fase V15-E.1).

Fornece:
1. Gerenciamento seguro de credenciais OAuth 2.0 por perfil e canal.
2. Armazenamento isolado de tokens em storage/credentials/youtube/.
3. Verificação de identidade do canal autenticado (get_authenticated_channel).
4. Upload de vídeo direto com suporte resumable e fail-closed.
5. Guard mandatória de privacidade da POC: estritamente 'private' (DIRECT_POC_PRIVATE_ONLY).
6. Sanitização absoluta contra vazamento de tokens e segredos em logs e retornos.

IMPORTANTE:
- Não substitui o Scheduler nem o Upload-Post existente.
- Não realiza chamadas automáticas em workers.
- Totalmente isolado do banco de dados (zero escrita em publication_events/scheduled_posts nesta fase).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Escopos OAuth oficiais
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

DEFAULT_SCOPES = [
    YOUTUBE_UPLOAD_SCOPE,
    YOUTUBE_READONLY_SCOPE,
]

# Guard de Privacidade da POC (V15-E.1)
ALLOWED_POC_PRIVACY_STATUS = "private"
ERROR_DIRECT_POC_PRIVATE_ONLY = "DIRECT_POC_PRIVATE_ONLY"

# Códigos de erro normalizados
ERROR_VIDEO_FILE_MISSING = "VIDEO_FILE_MISSING"
ERROR_VIDEO_FILE_ZERO_BYTES = "VIDEO_FILE_ZERO_BYTES"
ERROR_OAUTH_CREDENTIALS_MISSING = "OAUTH_CREDENTIALS_MISSING"
ERROR_OAUTH_TOKEN_EXPIRED = "OAUTH_TOKEN_EXPIRED"
ERROR_CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
ERROR_CHANNEL_NOT_FOUND = "CHANNEL_NOT_FOUND"
ERROR_UPLOAD_FAILED = "UPLOAD_FAILED"


def sanitize_identifier(value: str) -> str:
    """Sanitiza strings de perfil e canal para uso seguro em caminhos de arquivo."""
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(value or "").strip())
    return clean or "unknown"


def get_credentials_dir(base_dir: Optional[str] = None) -> Path:
    """Retorna o diretório base canônico para tokens OAuth do YouTube."""
    if base_dir:
        p = Path(base_dir).resolve()
    else:
        p = PROJECT_ROOT / "storage" / "credentials" / "youtube"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_token_path(
    profile_id: str,
    channel_id: str,
    base_dir: Optional[str] = None,
) -> Path:
    """Gera o caminho canônico isolado do token OAuth para o par (profile_id, channel_id)."""
    clean_p = sanitize_identifier(profile_id)
    clean_c = sanitize_identifier(channel_id)
    target_dir = get_credentials_dir(base_dir)
    return target_dir / f"youtube_direct_{clean_p}_{clean_c}.json"


def resolve_client_secret_path(
    explicit_path: Optional[str] = None,
    credentials_dir: Optional[str] = None,
) -> Optional[Path]:
    """Localiza o arquivo client_secret.json oficial do Google OAuth."""
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.is_file():
            return p

    # Variável de ambiente YOUTUBE_DIRECT_CLIENT_SECRET
    env_path = os.environ.get("YOUTUBE_DIRECT_CLIENT_SECRET", "").strip()
    if env_path:
        p = Path(env_path).resolve()
        if p.is_file():
            return p

    # Localização padrão em storage/credentials/youtube/client_secret.json
    base = get_credentials_dir(credentials_dir)
    cand = base / "client_secret.json"
    if cand.is_file():
        return cand

    # Raiz do projeto
    cand2 = PROJECT_ROOT / "client_secret.json"
    if cand2.is_file():
        return cand2

    return None


def save_credentials(
    credentials: Any,
    profile_id: str,
    channel_id: str,
    credentials_dir: Optional[str] = None,
) -> Path:
    """Persiste credenciais OAuth localmente no caminho isolado do canal."""
    token_path = get_token_path(profile_id, channel_id, base_dir=credentials_dir)
    token_json = credentials.to_json() if hasattr(credentials, "to_json") else str(credentials)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(token_json)
    logger.info(
        f"[YOUTUBE_DIRECT] Credenciais salvas com sucesso em: {token_path.name} "
        f"(profile={profile_id}, channel={channel_id})"
    )
    return token_path


def load_credentials(
    profile_id: str,
    channel_id: str,
    credentials_dir: Optional[str] = None,
    auto_refresh: bool = True,
) -> Optional[Any]:
    """Carrega credenciais OAuth para o perfil/canal, renovando o token se expirado."""
    token_path = get_token_path(profile_id, channel_id, base_dir=credentials_dir)
    if not token_path.is_file():
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(token_path), scopes=DEFAULT_SCOPES)
        if creds and creds.expired and creds.refresh_token and auto_refresh:
            creds.refresh(Request())
            # Atualiza o arquivo salvo com o novo token de acesso
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            logger.info(f"[YOUTUBE_DIRECT] Token OAuth renovado para {profile_id}/{channel_id}")
        return creds
    except Exception as exc:
        logger.warning(
            f"[YOUTUBE_DIRECT] Falha ao carregar credenciais para {profile_id}/{channel_id}: {exc}"
        )
        return None


def get_oauth_flow(
    client_secrets_file: str,
    scopes: Optional[List[str]] = None,
) -> Any:
    """Cria e configura o fluxo de autorização OAuth 2.0 (InstalledAppFlow)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    target_scopes = scopes or DEFAULT_SCOPES
    return InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_file),
        scopes=target_scopes,
    )


def get_authenticated_channel(
    credentials: Optional[Any] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    credentials_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta a identidade do canal autenticado via channels.list(mine=True).

    Retorna estritamente:
    - channel_id: ID canônico do YouTube (ex: UCxxxxxxxx)
    - channel_title: Nome de exibição do canal
    Zero segredos ou tokens.
    """
    creds = credentials
    if not creds and profile_id and channel_id:
        creds = load_credentials(profile_id, channel_id, credentials_dir=credentials_dir)

    if not creds:
        raise ValueError("Credenciais OAuth ausentes para consulta de identidade do canal.")

    import googleapiclient.discovery

    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=creds, cache_discovery=False
    )
    res = youtube.channels().list(part="snippet", mine=True).execute()

    items = res.get("items", [])
    if not items:
        raise ValueError("Nenhum canal do YouTube associado à conta autenticada.")

    item = items[0]
    c_id = item.get("id")
    c_title = item.get("snippet", {}).get("title", "")

    return {
        "channel_id": c_id,
        "channel_title": c_title,
    }


def upload_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    privacy_status: str = "private",
    profile_id: str = "default",
    channel_id: str = "default",
    expected_channel_id: Optional[str] = None,
    client_secrets_file: Optional[str] = None,
    credentials_dir: Optional[str] = None,
    credentials: Optional[Any] = None,
    chunk_size: int = 1024 * 1024 * 4,  # 4MB por chunk para upload resumable
) -> Dict[str, Any]:
    """Executa o upload direto de vídeo para o YouTube via YouTube Data API v3.

    Garantias:
    - PRIVATE-ONLY guard da POC: bloqueia public e unlisted com DIRECT_POC_PRIVATE_ONLY.
    - Validação de arquivo físico existente e > 0 bytes.
    - Validação de credenciais e integridade OAuth.
    - Validação de correspondência de canal quando expected_channel_id fornecido.
    - Upload resumable com videos.insert.
    - Retorno estruturado normalizado com zero secrets.
    """
    clean_privacy = str(privacy_status or "").strip().lower()

    # 1. Guard de Privacidade da POC (V15-E.1)
    if clean_privacy != ALLOWED_POC_PRIVACY_STATUS:
        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_DIRECT_POC_PRIVATE_ONLY,
            "error_message": (
                f"Nesta POC o status de privacidade é restrito a '{ALLOWED_POC_PRIVACY_STATUS}'. "
                f"Valor rejeitado: '{privacy_status}'"
            ),
        }

    # 2. Validação do arquivo de vídeo
    v_path = Path(video_path).resolve() if video_path else None
    if not v_path or not v_path.is_file():
        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_VIDEO_FILE_MISSING,
            "error_message": f"Arquivo de vídeo não encontrado no caminho: '{video_path}'",
        }

    if v_path.stat().st_size <= 0:
        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_VIDEO_FILE_ZERO_BYTES,
            "error_message": f"Arquivo de vídeo vazio (0 bytes): '{video_path}'",
        }

    # 3. Obtenção das credenciais OAuth
    creds = credentials
    if not creds:
        creds = load_credentials(profile_id, channel_id, credentials_dir=credentials_dir)

    if not creds:
        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_OAUTH_CREDENTIALS_MISSING,
            "error_message": (
                f"Credenciais OAuth ausentes para profile='{profile_id}', channel='{channel_id}'. "
                "Execute o probe manual para autorizar o canal."
            ),
        }

    if hasattr(creds, "expired") and creds.expired and not getattr(creds, "refresh_token", None):
        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_OAUTH_TOKEN_EXPIRED,
            "error_message": "Token OAuth expirado sem refresh token disponível. Reautorização necessária.",
        }

    # 4. Verificação de correspondência de canal (Channel Identity Guard)
    if expected_channel_id:
        try:
            auth_info = get_authenticated_channel(
                credentials=creds,
                profile_id=profile_id,
                channel_id=channel_id,
                credentials_dir=credentials_dir,
            )
            actual_channel_id = auth_info.get("channel_id")
            clean_expected = str(expected_channel_id).strip()
            if actual_channel_id != clean_expected:
                return {
                    "success": False,
                    "provider": "youtube_direct",
                    "external_id": None,
                    "external_url": None,
                    "privacy_status": clean_privacy,
                    "error_code": ERROR_CHANNEL_MISMATCH,
                    "error_message": (
                        f"Canal autenticado ('{actual_channel_id}') não corresponde ao canal "
                        f"esperado ('{clean_expected}'). Upload abortado."
                    ),
                }
        except Exception as exc:
            return {
                "success": False,
                "provider": "youtube_direct",
                "external_id": None,
                "external_url": None,
                "privacy_status": clean_privacy,
                "error_code": ERROR_CHANNEL_NOT_FOUND,
                "error_message": f"Falha ao validar identidade do canal autenticado: {exc}",
            }

    # 5. Execução do upload via videos.insert com resumable upload
    try:
        import googleapiclient.discovery
        import googleapiclient.http
        import googleapiclient.errors

        youtube = googleapiclient.discovery.build(
            "youtube", "v3", credentials=creds, cache_discovery=False
        )

        body: Dict[str, Any] = {
            "snippet": {
                "title": title,
                "description": description or "",
                "tags": tags or [],
            },
            "status": {
                "privacyStatus": ALLOWED_POC_PRIVACY_STATUS,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = googleapiclient.http.MediaFileUpload(
            str(v_path),
            mimetype="video/mp4",
            chunksize=chunk_size,
            resumable=True,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        # Loop de chunks resumable
        response = None
        if hasattr(request, "next_chunk"):
            while response is None:
                status, response = request.next_chunk()
        else:
            response = request.execute()

        video_id = response.get("id") if isinstance(response, dict) else None
        external_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None

        return {
            "success": True,
            "provider": "youtube_direct",
            "external_id": video_id,
            "external_url": external_url,
            "privacy_status": ALLOWED_POC_PRIVACY_STATUS,
            "error_code": None,
            "error_message": None,
        }

    except Exception as exc:
        err_msg = str(exc)
        # Sanitiza mensagem para garantir ausência de segredos ou tokens
        sanitized_msg = re.sub(r"ya29\.[a-zA-Z0-9_\-]+", "[REDACTED_ACCESS_TOKEN]", err_msg)
        sanitized_msg = re.sub(r"1//[a-zA-Z0-9_\-]+", "[REDACTED_REFRESH_TOKEN]", sanitized_msg)
        logger.error(f"[YOUTUBE_DIRECT] Erro durante upload: {sanitized_msg}")

        return {
            "success": False,
            "provider": "youtube_direct",
            "external_id": None,
            "external_url": None,
            "privacy_status": clean_privacy,
            "error_code": ERROR_UPLOAD_FAILED,
            "error_message": sanitized_msg,
        }
