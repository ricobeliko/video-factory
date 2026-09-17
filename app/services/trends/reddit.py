from typing import List
from urllib.parse import quote_plus
from loguru import logger
import requests

from app.services.trends.base import BaseTrendProvider, TrendSignal


class RedditTrendsProvider(BaseTrendProvider):
    """Coleta tópicos em alta e discussões populares via endpoint JSON público do Reddit."""

    name: str = "reddit"

    # Mapeamento de subreddits por afinidade de nicho
    NICHE_SUBREDDITS = {
        "curiosidades": ["todayilearned", "curiosidades", "interestingasfuck"],
        "ciencia": ["science", "fatoscuriosos", "space"],
        "tecnologia": ["technology", "gadgets", "futurism"],
        "historia": ["history", "historyporn", "historiadobrasil"],
        "financas": ["personalfinance", "investimentos", "economy"],
    }

    def __init__(self, timeout: int = 6):
        self.timeout = timeout

    def fetch_trends(
        self,
        niche: str = "",
        language: str = "pt-BR",
        region: str = "BR",
        limit: int = 20,
    ) -> List[TrendSignal]:
        clean_niche = (niche or "").strip().lower()
        subreddits = self.NICHE_SUBREDDITS.get(clean_niche)

        headers = {
            "User-Agent": "MoneyPrinterTurbo-TrendRadar/1.0 (by /u/automation_bot)"
        }

        signals: List[TrendSignal] = []
        try:
            if subreddits:
                sub = subreddits[0]
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
            elif clean_niche:
                encoded_q = quote_plus(clean_niche)
                url = f"https://www.reddit.com/search.json?q={encoded_q}&sort=hot&limit={limit}"
            else:
                url = f"https://www.reddit.com/r/popular/hot.json?limit={limit}"

            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"[RedditTrendsProvider] HTTP {resp.status_code} ao consultar {url}")
                return signals

            data = resp.json()
            children = data.get("data", {}).get("children", [])

            for item in children[:limit]:
                pdata = item.get("data", {})
                title = pdata.get("title") or ""
                if not title.strip() or pdata.get("over_18", False):
                    continue

                permalink = pdata.get("permalink") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else pdata.get("url", "")
                score = float(pdata.get("score") or 0)
                comments = int(pdata.get("num_comments") or 0)

                # Pontuação de 50 a 90 baseada em upvotes
                scaled_score = 50.0
                if score >= 5000:
                    scaled_score = 90.0
                elif score >= 1000:
                    scaled_score = 80.0
                elif score >= 200:
                    scaled_score = 70.0
                elif score >= 50:
                    scaled_score = 60.0

                signals.append(
                    TrendSignal(
                        title=title.strip(),
                        source=self.name,
                        source_key=f"reddit_{pdata.get('id', '')}",
                        source_url=full_url,
                        description=pdata.get("selftext", "")[:300],
                        published_at=str(pdata.get("created_utc", "")),
                        region=region,
                        language=language,
                        raw_score=scaled_score,
                        source_confidence="MEDIUM",
                        metadata={
                            "upvotes": score,
                            "comments": comments,
                            "subreddit": pdata.get("subreddit", ""),
                        },
                    )
                )
        except Exception as exc:
            logger.warning(f"[RedditTrendsProvider] Falha ao coletar tendências: {exc}")

        return signals
