#!/usr/bin/env python
"""Probe e Ferramenta Manual CLI para YouTube Direct Publisher (Fase V15-E.1).

Permite:
1. 'status' : inspecionar a presença e validade de credenciais/tokens para um perfil/canal.
2. 'auth'   : disparar o fluxo manual de autorização OAuth 2.0 (InstalledAppFlow).
3. 'whoami' : auditar a identidade do canal autenticado (channel_id e channel_title).
4. 'upload' : testar upload direto com guard de privacidade PRIVATE estrita da POC.

REGRAS DE SEGURANÇA:
- Estritamente fail-closed.
- Zero vazamento de access_token, refresh_token ou client_secret em stdout/stderr.
- Zero chamadas automáticas ou escrita em banco de dados de produção.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import youtube_direct


def cmd_status(args: argparse.Namespace) -> int:
    """Inspeciona o status das credenciais para o perfil/canal especificado."""
    profile_id = args.profile_id
    channel_id = args.channel_id
    cred_dir = args.credentials_dir

    token_path = youtube_direct.get_token_path(profile_id, channel_id, base_dir=cred_dir)
    cs_path = youtube_direct.resolve_client_secret_path(args.client_secret, credentials_dir=cred_dir)

    print("=" * 72)
    print(" YOUTUBE DIRECT PUBLISHER — STATUS")
    print("=" * 72)
    print(f"Profile ID           : {profile_id}")
    print(f"Channel ID           : {channel_id}")
    print(f"Client Secret Found  : {'YES' if cs_path else 'NO'} ({cs_path or 'Not configured'})")
    print(f"Token Storage File   : {token_path}")
    print(f"Token Exists         : {'YES' if token_path.is_file() else 'NO'}")

    if token_path.is_file():
        creds = youtube_direct.load_credentials(
            profile_id, channel_id, credentials_dir=cred_dir, auto_refresh=False
        )
        if creds:
            has_refresh = bool(getattr(creds, "refresh_token", None))
            is_expired = getattr(creds, "expired", False)
            print(f"Token Valid/Loaded   : YES")
            print(f"Token Expired        : {'YES' if is_expired else 'NO'}")
            print(f"Refresh Token Present: {'YES' if has_refresh else 'NO'}")
            print(f"Authorized Scopes    : {', '.join(getattr(creds, 'scopes', []) or [])}")
            try:
                auth_info = youtube_direct.get_authenticated_channel(
                    credentials=creds, profile_id=profile_id, channel_id=channel_id, credentials_dir=cred_dir
                )
                print(f"Authenticated Channel: {auth_info.get('channel_title')} ({auth_info.get('channel_id')})")
            except Exception as exc:
                print(f"Authenticated Channel: [ERROR] {exc}")
        else:
            print("Token Valid/Loaded   : NO (Falha na desserialização)")
    else:
        print("Authenticated Channel: N/A (Token ausente)")

    print("=" * 72)
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    """Dispara o fluxo de consentimento OAuth 2.0 manual."""
    profile_id = args.profile_id
    channel_id = args.channel_id
    cred_dir = args.credentials_dir

    cs_path = youtube_direct.resolve_client_secret_path(args.client_secret, credentials_dir=cred_dir)
    if not cs_path or not cs_path.is_file():
        print(
            f"[ERRO] client_secret.json não encontrado. "
            f"Especifique via --client-secret ou configure YOUTUBE_DIRECT_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 1

    print("=" * 72)
    print(" INICIANDO FLUXO MANUAL GOOGLE OAUTH 2.0")
    print("=" * 72)
    print(f"Profile Alvo  : {profile_id}")
    print(f"Canal Alvo    : {channel_id}")
    print(f"Client Secret : {cs_path}")
    print(f"Escopos       : {', '.join(youtube_direct.DEFAULT_SCOPES)}")
    print("-" * 72)

    flow = youtube_direct.get_oauth_flow(str(cs_path))

    if args.console:
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("\n1. Abra a URL abaixo no seu navegador:")
        print(auth_url)
        print("\n2. Faça login com a conta Google dona do canal desejado.")
        print("3. Conceda as permissões solicitadas.")
        code = input("\nCole o código de autorização gerado aqui: ").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
    else:
        print("\nIniciando servidor local para captura de autenticação...")
        print("Por favor, selecione e autorize o canal correto no navegador.")
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    saved_path = youtube_direct.save_credentials(
        creds, profile_id=profile_id, channel_id=channel_id, credentials_dir=cred_dir
    )

    try:
        auth_info = youtube_direct.get_authenticated_channel(credentials=creds)
        c_id = auth_info.get("channel_id")
        c_title = auth_info.get("channel_title")
    except Exception as exc:
        c_id = "UNKNOWN"
        c_title = f"[Erro ao consultar]: {exc}"

    print("\n" + "=" * 72)
    print(" AUTORIZAÇÃO CONCLUÍDA COM SUCESSO!")
    print(f"Canal Vinculado : {c_title} (ID: {c_id})")
    print(f"Token Gravado   : {saved_path}")
    print("=" * 72)
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    """Verifica e exibe a identidade do canal autenticado sem expor segredos."""
    profile_id = args.profile_id
    channel_id = args.channel_id
    cred_dir = args.credentials_dir

    try:
        auth_info = youtube_direct.get_authenticated_channel(
            profile_id=profile_id, channel_id=channel_id, credentials_dir=cred_dir
        )
        print("=" * 72)
        print(" IDENTIDADE DO CANAL AUTENTICADO")
        print("=" * 72)
        print(f"Profile ID    : {profile_id}")
        print(f"Channel ID    : {channel_id}")
        print(f"CHANNEL_ID    : {auth_info.get('channel_id')}")
        print(f"CHANNEL_TITLE : {auth_info.get('channel_title')}")
        print("=" * 72)
        return 0
    except Exception as exc:
        print(f"[ERRO] Falha ao verificar canal autenticado: {exc}", file=sys.stderr)
        return 1


def cmd_upload(args: argparse.Namespace) -> int:
    """Executa tentativa de upload de vídeo obedecendo às guards da POC."""
    res = youtube_direct.upload_video(
        video_path=args.video,
        title=args.title,
        description=args.description or "",
        privacy_status=args.privacy,
        profile_id=args.profile_id,
        channel_id=args.channel_id,
        expected_channel_id=args.expected_channel_id,
        credentials_dir=args.credentials_dir,
    )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("=" * 72)
        if res.get("success"):
            print(" UPLOAD CONCLUÍDO COM SUCESSO (YOUTUBE DIRECT POC)")
            print(f"External Video ID : {res.get('external_id')}")
            print(f"External URL      : {res.get('external_url')}")
            print(f"Privacy Status    : {res.get('privacy_status')}")
        else:
            print(" FALHA NO UPLOAD DIRETO")
            print(f"Error Code        : {res.get('error_code')}")
            print(f"Error Message     : {res.get('error_message')}")
        print("=" * 72)

    return 0 if res.get("success") else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe e CLI de Diagnóstico para YouTube Direct Publisher (V15-E.1)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: status
    p_status = subparsers.add_parser("status", help="Verifica estado das credenciais")
    p_status.add_argument("--profile-id", default="default", help="ID do perfil de conteúdo")
    p_status.add_argument("--channel-id", default="channel-default-youtube", help="ID do canal")
    p_status.add_argument("--client-secret", default=None, help="Caminho do client_secret.json")
    p_status.add_argument("--credentials-dir", default=None, help="Diretório de credenciais customizado")

    # Subcomando: auth
    p_auth = subparsers.add_parser("auth", help="Inicia autorização OAuth 2.0 manual")
    p_auth.add_argument("--profile-id", default="default", help="ID do perfil de conteúdo")
    p_auth.add_argument("--channel-id", default="channel-default-youtube", help="ID do canal")
    p_auth.add_argument("--client-secret", default=None, help="Caminho do client_secret.json")
    p_auth.add_argument("--credentials-dir", default=None, help="Diretório de credenciais customizado")
    p_auth.add_argument("--console", action="store_true", help="Usa fluxo no terminal via código de autorização")

    # Subcomando: whoami
    p_whoami = subparsers.add_parser("whoami", help="Mostra identidade do canal autenticado")
    p_whoami.add_argument("--profile-id", default="default", help="ID do perfil de conteúdo")
    p_whoami.add_argument("--channel-id", default="channel-default-youtube", help="ID do canal")
    p_whoami.add_argument("--credentials-dir", default=None, help="Diretório de credenciais customizado")

    # Subcomando: upload
    p_upload = subparsers.add_parser("upload", help="Executa upload direto de vídeo (POC)")
    p_upload.add_argument("--profile-id", default="default", help="ID do perfil de conteúdo")
    p_upload.add_argument("--channel-id", default="channel-default-youtube", help="ID do canal")
    p_upload.add_argument("--video", required=True, help="Caminho do arquivo de vídeo")
    p_upload.add_argument("--title", required=True, help="Título do vídeo")
    p_upload.add_argument("--description", default="", help="Descrição do vídeo")
    p_upload.add_argument("--privacy", default="private", help="Status de privacidade (restrito a 'private' na POC)")
    p_upload.add_argument("--expected-channel-id", default=None, help="ID esperado do canal para validação pré-upload")
    p_upload.add_argument("--credentials-dir", default=None, help="Diretório de credenciais customizado")
    p_upload.add_argument("--json", action="store_true", help="Gera saída estruturada em JSON")

    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status(args)
    elif args.command == "auth":
        return cmd_auth(args)
    elif args.command == "whoami":
        return cmd_whoami(args)
    elif args.command == "upload":
        return cmd_upload(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
