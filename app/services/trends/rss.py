import xml.etree.ElementTree as ET
from typing import List
from urllib.parse import quote_plus
from loguru import logger
import requests

from app.services.trends.base import BaseTrendProvider, TrendSignal


class RssNewsProvider(BaseTrendProvider):
    """Coleta notícias e assuntos em evidência via feeds RSS públicos (Google News RSS)."""

    name: str = "rss"

    def __init__(self, timeout: int = 6):
        self.timeout = timeout

    def fetch_trends(
        self,
        niche: str = "",
        language: str = "pt-BR",
        region: str = "BR",
        limit: int = 20,
    ) -> List[TrendSignal]:
        geo = (region or "BR").upper()
        hl = (language or "pt-BR").lower()

        # Monta query temática para o Google News RSS
        query = (niche or "tendências").strip()
        encoded_query = quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={geo}&ceid={geo}:{hl}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        signals: List[TrendSignal] = []
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"[RssNewsProvider] HTTP {resp.status_code} ao consultar {url}")
                return signals

            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is None:
                return signals

            items = channel.findall("item")

            for idx, item in enumerate(items[:max(limit * 2, 25)]):
                raw_title = item.findtext("title") or ""
                if not raw_title.strip():
                    continue

                # Remove o nome do veículo ao final (ex: "Título da matéria - Nome do Veículo")
                title = raw_title
                source_outlet = ""
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source_outlet = parts[1].strip()

                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                description = item.findtext("description") or ""

                # Variação suave por relevância/posição no feed
                raw_score = max(50.0, 75.0 - idx * 2.0)

                signals.append(
                    TrendSignal(
                        title=title,
                        source=self.name,
                        source_key=f"rss_{geo}_{title.lower()}",
                        source_url=link.strip(),
                        description=description.strip(),
                        published_at=pub_date.strip(),
                        region=geo,
                        language=language,
                        raw_score=raw_score,
                        source_confidence="MEDIUM",
                        metadata={"outlet": source_outlet, "niche_query": query},
                    )
                )
        except Exception as exc:
            logger.warning(f"[RssNewsProvider] Falha ao coletar tendências: {exc}")

        return signals
