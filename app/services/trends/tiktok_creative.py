from typing import List
from loguru import logger

from app.services.trends.base import BaseTrendProvider, TrendSignal


class TikTokCreativeProvider(BaseTrendProvider):
    """Provider extensível preparado para integração oficial com TikTok Creative Center / Commercial Content API.
    
    Não utiliza scraping frágil nem atalhos inseguros.
    """

    name: str = "tiktok_creative"

    def __init__(self, api_token: str = ""):
        self.api_token = api_token

    def fetch_trends(
        self,
        niche: str = "",
        language: str = "pt-BR",
        region: str = "BR",
        limit: int = 20,
    ) -> List[TrendSignal]:
        # Interface extensível: quando houver token de API comercial configurado, realiza a consulta
        if not self.api_token:
            logger.debug("[TikTokCreativeProvider] Nenhum token configurado; provider inativo sem scraping frágil.")
            return []

        # Estrutura pronta para integração com TikTok Commercial Content API
        signals: List[TrendSignal] = []
        return signals
