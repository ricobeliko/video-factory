import xml.etree.ElementTree as ET
from typing import List
from loguru import logger
import requests

from app.services.trends.base import BaseTrendProvider, TrendSignal


class GoogleTrendsProvider(BaseTrendProvider):
    """Coleta tendências diárias do feed público RSS do Google Trends."""

    name: str = "google_trends"

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
        url = f"https://trends.google.com/trending/rss?geo={geo}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        signals: List[TrendSignal] = []
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"[GoogleTrendsProvider] HTTP {resp.status_code} ao consultar {url}")
                return signals

            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is None:
                return signals

            ns = {"ht": "https://trends.google.com/trending/rss"}
            items = channel.findall("item")

            for idx, item in enumerate(items[:limit]):
                title = item.findtext("title") or ""
                if not title.strip():
                    continue

                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                description = item.findtext("description") or ""
                approx_traffic = item.findtext("ht:approx_traffic", namespaces=ns) or ""

                # Pontuação baseada no tráfego aproximado e posição na lista
                score = max(50.0, 68.0 - idx * 1.5)
                if approx_traffic:
                    clean_traffic = approx_traffic.replace("+", "").replace(",", "").replace(".", "").strip().upper()
                    if "M" in clean_traffic or "500K" in clean_traffic:
                        score = 95.0
                    elif "200K" in clean_traffic:
                        score = 85.0
                    elif "100K" in clean_traffic:
                        score = 75.0
                    elif "50K" in clean_traffic:
                        score = 65.0

                signals.append(
                    TrendSignal(
                        title=title.strip(),
                        source=self.name,
                        source_key=f"gt_{geo}_{title.strip().lower()}",
                        source_url=link.strip(),
                        description=description.strip(),
                        published_at=pub_date.strip(),
                        region=geo,
                        language=language,
                        raw_score=score,
                        source_confidence="HIGH",
                        metadata={"approx_traffic": approx_traffic},
                    )
                )
        except Exception as exc:
            logger.warning(f"[GoogleTrendsProvider] Falha ao coletar tendências: {exc}")

        return signals
