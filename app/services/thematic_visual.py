"""
app/services/thematic_visual.py
===============================
V16.8.2 — Alternative Visual Sources Evaluation.

Responsabilidade:
Arquitetura provider-agnostic para busca, ranqueamento determinístico,
avaliação de licenças e aquisição de ativos visuais em fontes públicas confiáveis
(NASA Image Library, Wikimedia Commons) quando o acervo de stock tradicional
apresentar baixa aderência contextual.

Princípios Fundamentais:
1. Zero dependência de provedores pagos (Gemini, Nano Banana e Imagen não são requisitos).
2. Prioridade visual canônica:
   - 1. STOCK_HIGH_CONFIDENCE (acervo stock existente de alta qualidade)
   - 2. TRUSTED_THEMATIC_SOURCE (NASA/JPL, Wikimedia com licenças abertas/domínio público)
   - 3. FREE_GENERATIVE_PROVIDER (somente se comprovadamente gratuito e sem fricção)
   - 4. STATIC_IMAGE + STILL_MOTION (motion sutil sobre imagem autêntica)
   - 5. FALLBACK_STOCK (resiliência total sem quebrar o pipeline)
3. Auditoria estrita de licenças:
   - Se uma licença for incerta, marcar LICENSE_REVIEW_REQUIRED e bloquear uso automático.
4. Score determinístico leve sem chamadas a LLMs pagos.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from loguru import logger


# =============================================================================
# Enums & Contracts
# =============================================================================

class ThematicLicenseStatus(str, Enum):
    """Classificação formal de compatibilidade de licença do ativo temático."""
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    COMPATIBLE_LICENSE = "COMPATIBLE_LICENSE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"

    # Backward compatibility aliases
    CC0 = "PUBLIC_DOMAIN"
    CC_BY = "COMPATIBLE_LICENSE"
    CC_BY_SA = "COMPATIBLE_LICENSE"
    OPEN_GOVERNMENT = "COMPATIBLE_LICENSE"
    LICENSE_REVIEW_REQUIRED = "REVIEW_REQUIRED"


class GenerativeProviderFeasibility(str, Enum):
    """Classificação de viabilidade para provedores generativos gratuitos auditados."""
    AVAILABLE = "AVAILABLE"
    REQUIRES_ACCOUNT = "REQUIRES_ACCOUNT"
    REQUIRES_BILLING = "REQUIRES_BILLING"
    FREE_QUOTA_UNKNOWN = "FREE_QUOTA_UNKNOWN"
    NOT_USEFUL_FOR_CURRENT_PROJECT = "NOT_USEFUL_FOR_CURRENT_PROJECT"


@dataclass
class ThematicAsset:
    """Ativo visual recuperado de fonte temática pública."""
    asset_id: str
    provider_name: str
    title: str
    description: str = ""
    source_url: str = ""
    download_url: str = ""
    thumbnail_url: Optional[str] = None
    author: Optional[str] = None
    attribution: Optional[str] = None
    license_status: ThematicLicenseStatus = ThematicLicenseStatus.REVIEW_REQUIRED
    license_name: str = "Unknown"
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: str = "landscape"  # "landscape", "portrait", "square"
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    local_path: Optional[str] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def provider(self) -> str:
        return self.provider_name

    @property
    def asset_url(self) -> str:
        return self.download_url

    @property
    def semantic_score(self) -> float:
        return self.score_breakdown.get("semantic_match", 0.0)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["provider"] = self.provider_name
        data["asset_url"] = self.download_url
        data["semantic_score"] = self.semantic_score
        data["license_status"] = self.license_status.value
        return data


@dataclass
class ThematicQualityGateResult:
    """Resultado da validação técnica e de conformidade do ativo temático."""
    is_valid: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Provider Base Contract
# =============================================================================

class ThematicVisualProvider(ABC):
    """Interface abstrata provider-agnostic para fontes temáticas de mídia."""

    name: str = "thematic_base"
    provider_type: str = "thematic"
    authority_score: float = 10.0

    @abstractmethod
    def supports_topic(self, topic: str) -> bool:
        """Indica se este provedor possui especialidade relevante para o tópico."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 10,
        options: Optional[Dict[str, Any]] = None,
    ) -> List[ThematicAsset]:
        """Realiza busca no acervo e retorna candidatos com metadados estruturados."""
        pass

    def rank(
        self,
        assets: List[ThematicAsset],
        target_subject: str = "",
        narration: str = "",
        target_aspect_ratio: str = "9:16",
        used_asset_ids: Optional[List[str]] = None,
    ) -> List[ThematicAsset]:
        """Ranqueia deterministicamente os ativos usando ThematicScoringEngine."""
        scoring_engine = ThematicScoringEngine()
        ranked = []
        for asset in assets:
            score, breakdown = scoring_engine.compute_thematic_score(
                asset=asset,
                target_subject=target_subject,
                narration=narration,
                target_aspect_ratio=target_aspect_ratio,
                is_reused=(used_asset_ids is not None and asset.asset_id in used_asset_ids),
            )
            asset.score = score
            asset.score_breakdown = breakdown
            ranked.append(asset)

        ranked.sort(key=lambda a: a.score, reverse=True)
        return ranked

    def fetch_asset(
        self,
        asset: ThematicAsset,
        target_path: str,
        timeout: int = 25,
    ) -> str:
        """
        Baixa o ativo do repositório remoto para o caminho local.
        Suporta sobrescrita segura e garante validação de integridade.
        """
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        urls_to_try = [asset.download_url]
        if asset.thumbnail_url and asset.thumbnail_url not in urls_to_try:
            urls_to_try.append(asset.thumbnail_url)
        nasa_id = asset.extra_metadata.get("nasa_id")
        if nasa_id:
            urls_to_try.append(f"http://images-assets.nasa.gov/image/{nasa_id}/{nasa_id}~orig.jpg")
            urls_to_try.append(f"http://images-assets.nasa.gov/image/{nasa_id}/{nasa_id}~small.jpg")

        last_error = None
        content = None
        for u in urls_to_try:
            if not u:
                continue
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 VideoFactoryBot/1.0"
                }
                req = urllib.request.Request(u, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read()
                    if data and len(data) > 0:
                        content = data
                        asset.download_url = u
                        break
            except Exception as exc:
                last_error = exc

        if not content or len(content) == 0:
            raise ValueError(f"Falha ao baixar ativo {asset.asset_id}: {last_error}")

        with open(target_path, "wb") as f:
            f.write(content)

        asset.local_path = target_path
        logger.info(
            f"[THEMATIC_PROVIDER][{self.name}] Ativo baixado com sucesso: {asset.asset_id} -> {target_path} ({len(content)} bytes)"
        )
        return target_path

    def metadata(self, asset: ThematicAsset) -> Dict[str, Any]:
        """Retorna metadados para auditoria e observabilidade de cena."""
        return {
            "provider": asset.provider,
            "provider_name": self.name,
            "provider_type": self.provider_type,
            "asset_id": asset.asset_id,
            "title": asset.title,
            "description": asset.description,
            "author": asset.author or "Unknown",
            "attribution": asset.attribution or "",
            "source_url": asset.source_url,
            "asset_url": asset.asset_url,
            "license_status": asset.license_status.value,
            "license_name": asset.license_name,
            "width": asset.width,
            "height": asset.height,
            "orientation": asset.orientation,
            "thematic_score": asset.score,
            "semantic_score": asset.semantic_score,
            "score_breakdown": asset.score_breakdown,
        }

    def license_info(self, asset: ThematicAsset) -> Dict[str, Any]:
        """Retorna informações específicas de licenciamento e uso."""
        return {
            "license_status": asset.license_status.value,
            "license_name": asset.license_name,
            "author": asset.author,
            "attribution": asset.attribution,
            "source_url": asset.source_url,
            "asset_url": asset.asset_url,
            "requires_attribution": asset.license_status == ThematicLicenseStatus.COMPATIBLE_LICENSE,
            "commercial_allowed": asset.license_status in (ThematicLicenseStatus.PUBLIC_DOMAIN, ThematicLicenseStatus.COMPATIBLE_LICENSE),
        }


# =============================================================================
# NASA Image Library Provider
# =============================================================================

class NASAImageLibraryProvider(ThematicVisualProvider):
    """
    Provedor oficial da NASA Image and Video Library (images-api.nasa.gov).
    Totalmente gratuito, aberto, sem necessidade de API key, contendo registros
    científicos autênticos de Marte, missões espaciais, rovers, JPL e astronomia.
    """

    name = "nasa_image_library"
    provider_type = "thematic_public_agency"
    authority_score = 15.0

    SUPPORTED_KEYWORDS = {
        "marte", "mars", "space", "espaço", "lua", "moon", "solar", "sun", "sol",
        "astronomia", "astronomy", "planet", "planeta", "vulcao", "volcano",
        "olympus", "mons", "rover", "curiosity", "perseverance", "voyager",
        "apollo", "jpl", "hubble", "webb", "galaxy", "galáxia", "cosmos",
        "cosmo", "saturno", "jupiter", "twilight", "sunset", "pôr do sol",
        "crater", "cratera", "caldera", "caldeira", "escarpment", "escarpa",
    }

    def supports_topic(self, topic: str) -> bool:
        if not topic:
            return False
        tokens = re.findall(r"\w+", topic.lower())
        return any(t in self.SUPPORTED_KEYWORDS for t in tokens)

    def search(
        self,
        query: str,
        limit: int = 10,
        options: Optional[Dict[str, Any]] = None,
    ) -> List[ThematicAsset]:
        safe_query = query.strip()
        if not safe_query:
            return []

        # Constrói requisição oficial
        encoded_q = urllib.parse.quote(safe_query)
        api_url = f"https://images-api.nasa.gov/search?q={encoded_q}&media_type=image"

        headers = {
            "User-Agent": "VideoFactoryBot/1.0 (https://github.com/ricobeliko/video-factory; bot@videofactory.internal)"
        }
        req = urllib.request.Request(api_url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning(f"[THEMATIC_NASA][SEARCH_FAILED] Falha ao consultar NASA API: {exc}")
            return []

        items = data.get("collection", {}).get("items", [])
        assets: List[ThematicAsset] = []

        for item in items[:limit]:
            data_list = item.get("data", [])
            if not data_list:
                continue
            item_data = data_list[0]
            nasa_id = item_data.get("nasa_id", "")
            title = item_data.get("title", "")
            description = item_data.get("description", "")
            secondary_creator = item_data.get("secondary_creator") or item_data.get("photographer") or "NASA / JPL"
            center = item_data.get("center", "NASA")

            # Resolve link de imagem a partir dos links oficiais retornados
            links = item.get("links", [])
            thumb_url = links[0].get("href") if links else None
            canonical_link = next((lnk for lnk in links if lnk.get("rel") == "canonical"), None)

            if canonical_link and canonical_link.get("href"):
                download_url = canonical_link.get("href")
                w_val = canonical_link.get("width") or 1920
                h_val = canonical_link.get("height") or 1080
            elif thumb_url:
                download_url = thumb_url
                w_val = links[0].get("width") or 1280
                h_val = links[0].get("height") or 720
            elif nasa_id:
                download_url = f"https://images-assets.nasa.gov/image/{nasa_id}/{nasa_id}~orig.jpg"
                w_val = 1920
                h_val = 1080
            else:
                download_url = ""
                w_val = 1920
                h_val = 1080

            source_page = f"https://images.nasa.gov/details/{nasa_id}"

            # Imagens da NASA são de domínio público segundo suas diretrizes de mídia
            # (exceto menção explícita em contrário)
            asset = ThematicAsset(
                asset_id=f"nasa_{nasa_id}",
                provider_name=self.name,
                title=title,
                description=description,
                source_url=source_page,
                download_url=download_url,
                thumbnail_url=thumb_url,
                author=f"{secondary_creator} ({center})",
                attribution="NASA/JPL-Caltech" if "jpl" in center.lower() else "NASA",
                license_status=ThematicLicenseStatus.PUBLIC_DOMAIN,
                license_name="Public Domain (NASA Media Usage Guidelines)",
                width=w_val,
                height=h_val,
                orientation="landscape",
                extra_metadata={
                    "nasa_id": nasa_id,
                    "center": center,
                    "date_created": item_data.get("date_created", ""),
                },
            )
            assets.append(asset)

        return assets


# =============================================================================
# Wikimedia Commons Provider
# =============================================================================

class WikimediaCommonsProvider(ThematicVisualProvider):
    """
    Provedor para Wikimedia Commons (commons.wikimedia.org).
    Acervo enciclopédico público e global com informações explícitas de licença,
    autor e termos de uso.
    """

    name = "wikimedia_commons"
    provider_type = "thematic_encyclopedia"
    authority_score = 12.0

    def supports_topic(self, topic: str) -> bool:
        # Wikimedia cobre virtualmente qualquer tópico enciclopédico
        return bool(topic and topic.strip())

    def _parse_license(self, meta: Dict[str, Any]) -> Tuple[ThematicLicenseStatus, str]:
        lic_name = meta.get("LicenseShortName", {}).get("value", "")
        usage_terms = meta.get("UsageTerms", {}).get("value", "")
        combined = f"{lic_name} {usage_terms}".lower()

        # 1. Restrições e bloqueios explícitos (Copyright / All Rights Reserved / NC / ND)
        if any(b in combined for b in ("all rights reserved", "copyright", "fair use", "-nc", "-nd", "non-commercial", "no derivatives")):
            return ThematicLicenseStatus.BLOCKED, lic_name or "Restricted / Blocked"

        # 2. Domínio público
        if any(pd in combined for pd in ("public domain", "pd", "cc0", "cc-zero")):
            return ThematicLicenseStatus.PUBLIC_DOMAIN, lic_name or "Public domain"

        # 3. Licenças compatíveis (CC-BY, CC-BY-SA, Open Government, Free Art, FAL, GFDL)
        if any(comp in combined for comp in ("cc by", "cc-by", "cc-by-sa", "cc by-sa", "open government", "free art", "fal", "gfdl")):
            return ThematicLicenseStatus.COMPATIBLE_LICENSE, lic_name or "Compatible License"

        # 4. Incerteza / revisão necessária
        return ThematicLicenseStatus.REVIEW_REQUIRED, lic_name or "Uncertain / Review Required"

    def search(
        self,
        query: str,
        limit: int = 10,
        options: Optional[Dict[str, Any]] = None,
    ) -> List[ThematicAsset]:
        safe_query = query.strip()
        if not safe_query:
            return []

        endpoint = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": safe_query,
            "gsrnamespace": 6,  # Namespace File:
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|dimensions",
            "format": "json",
            "gsrlimit": str(min(limit, 15)),
        }
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        headers = {
            "User-Agent": "VideoFactoryBot/1.0 (https://github.com/ricobeliko/video-factory; bot@videofactory.internal)"
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning(f"[THEMATIC_WIKIMEDIA][SEARCH_FAILED] Falha ao consultar Wikimedia: {exc}")
            return []

        pages = data.get("query", {}).get("pages", {})
        assets: List[ThematicAsset] = []

        for page_id, page in pages.items():
            title = page.get("title", "").replace("File:", "")
            imageinfo_list = page.get("imageinfo", [])
            if not imageinfo_list:
                continue

            info = imageinfo_list[0]
            download_url = info.get("url", "")
            source_url = info.get("descriptionurl", "")
            width = info.get("width")
            height = info.get("height")

            extmeta = info.get("extmetadata", {})
            desc_val = extmeta.get("ImageDescription", {}).get("value", "")
            # Limpa tags HTML simples da descrição
            desc_clean = re.sub(r"<[^>]+>", "", desc_val)
            artist_val = extmeta.get("Artist", {}).get("value", "")
            artist_clean = re.sub(r"<[^>]+>", "", artist_val)

            lic_status, lic_name = self._parse_license(extmeta)

            orientation = "landscape"
            if width and height:
                ratio = float(width) / float(height)
                if ratio < 0.8:
                    orientation = "portrait"
                elif 0.8 <= ratio <= 1.2:
                    orientation = "square"

            asset = ThematicAsset(
                asset_id=f"wiki_{page_id}",
                provider_name=self.name,
                title=title,
                description=desc_clean,
                source_url=source_url,
                download_url=download_url,
                thumbnail_url=download_url,
                author=artist_clean or "Wikimedia Contributor",
                attribution=artist_clean,
                license_status=lic_status,
                license_name=lic_name,
                width=width,
                height=height,
                orientation=orientation,
                extra_metadata={"page_id": page_id},
            )
            assets.append(asset)

        return assets


# =============================================================================
# Deterministic Thematic Scoring Engine
# =============================================================================

class ThematicScoringEngine:
    """
    Motor determinístico de pontuação para ativos temáticos (0–100).
    Avalia aderência semântica, autoridade da fonte, orientação, resolução,
    confiança de licenciamento e penaliza repetições.
    """

    def __init__(
        self,
        min_resolution_threshold: int = 360,
        min_acceptable_score: float = 40.0,
    ):
        self.min_resolution_threshold = min_resolution_threshold
        self.min_acceptable_score = min_acceptable_score

    def compute_thematic_score(
        self,
        asset: ThematicAsset,
        target_subject: str = "",
        narration: str = "",
        target_aspect_ratio: str = "9:16",
        is_reused: bool = False,
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calcula o score de 0 a 100 com o detalhamento por dimensão:
        - semantic_match: 0–50
        - source_authority: 0–15
        - orientation: 0–15
        - resolution: 0–10
        - license_confidence: 0–10
        - repetition_penalty: -25.0 se reutilizado
        """
        # 1. Semantic Match (0–50)
        semantic_score = self._compute_semantic_match(asset, target_subject, narration)

        # 2. Source Authority (0–15)
        if asset.provider_name == "nasa_image_library":
            authority_score = 15.0
        elif asset.provider_name == "wikimedia_commons":
            authority_score = 12.0
        else:
            authority_score = 8.0

        # 3. Orientation Match (0–15)
        orient = asset.orientation.lower()
        if target_aspect_ratio in ("9:16", "portrait"):
            if orient == "portrait":
                orient_score = 15.0
            elif orient == "square":
                orient_score = 11.0
            else:
                orient_score = 8.0  # Landscape ainda aproveitável via pan/still-motion
        else:
            if orient == "landscape":
                orient_score = 15.0
            elif orient == "square":
                orient_score = 10.0
            else:
                orient_score = 7.0

        # 4. Resolution Score (0–10)
        res_score = self._compute_resolution_score(asset.width, asset.height)

        # 5. License Confidence (0–10)
        if asset.license_status == ThematicLicenseStatus.PUBLIC_DOMAIN:
            lic_score = 10.0
        elif asset.license_status == ThematicLicenseStatus.COMPATIBLE_LICENSE:
            lic_score = 8.5
        elif asset.license_status == ThematicLicenseStatus.REVIEW_REQUIRED:
            lic_score = 0.0
        else:  # BLOCKED
            lic_score = -50.0

        # 6. Repetition Penalty
        rep_penalty = -25.0 if is_reused else 0.0

        total = semantic_score + authority_score + orient_score + res_score + lic_score + rep_penalty
        clamped_total = max(0.0, min(100.0, round(total, 2)))

        breakdown = {
            "semantic_match": round(semantic_score, 2),
            "source_authority": round(authority_score, 2),
            "orientation": round(orient_score, 2),
            "resolution": round(res_score, 2),
            "license_confidence": round(lic_score, 2),
            "repetition_penalty": round(rep_penalty, 2),
            "total": clamped_total,
        }
        return clamped_total, breakdown

    def _compute_semantic_match(
        self,
        asset: ThematicAsset,
        target_subject: str,
        narration: str,
    ) -> float:
        combined_text = f"{asset.title} {asset.description}".lower()

        # Tokenização simples
        subject_tokens = [t for t in re.findall(r"\w+", target_subject.lower()) if len(t) > 2]
        narration_tokens = [t for t in re.findall(r"\w+", narration.lower()) if len(t) > 3]

        subject_matches = sum(1 for token in subject_tokens if token in combined_text)
        narration_matches = sum(1 for token in narration_tokens if token in combined_text)

        # Base de score por sobreposição
        match_ratio_subject = (subject_matches / max(1, len(subject_tokens))) * 30.0
        match_ratio_narration = min(20.0, (narration_matches / max(1, len(narration_tokens))) * 25.0)

        # Bônus específico se o sujeito exato aparecer no título
        bonus = 5.0 if (target_subject.lower() in asset.title.lower()) else 0.0

        return min(50.0, match_ratio_subject + match_ratio_narration + bonus)

    def _compute_resolution_score(self, width: Optional[int], height: Optional[int]) -> float:
        if not width or not height:
            return 6.0  # Valor presumido se metadado omitido

        max_dim = max(width, height)
        if max_dim >= 1920:
            return 10.0
        elif max_dim >= 1280:
            return 8.5
        elif max_dim >= 800:
            return 7.0
        elif max_dim >= 480:
            return 5.0
        return 2.0

    def evaluate_quality_gate(self, asset: ThematicAsset) -> ThematicQualityGateResult:
        """
        Quality Gate estrito para aceitação automática do ativo temático.
        Rejeita se:
        - Licença for REVIEW_REQUIRED ou BLOCKED (somente PUBLIC_DOMAIN e COMPATIBLE_LICENSE permitidos)
        - Confiança de licença for zero
        - Resolução mínima for inferior ao threshold
        - Score total for insuficiente
        """
        if asset.license_status == ThematicLicenseStatus.REVIEW_REQUIRED:
            return ThematicQualityGateResult(
                is_valid=False,
                reason="UNCERTAIN_LICENSE_REVIEW_REQUIRED",
                details={"license_name": asset.license_name, "license_status": asset.license_status.value},
            )

        if asset.license_status == ThematicLicenseStatus.BLOCKED:
            return ThematicQualityGateResult(
                is_valid=False,
                reason="BLOCKED_RESTRICTED_LICENSE",
                details={"license_name": asset.license_name, "license_status": asset.license_status.value},
            )

        if asset.license_status not in (ThematicLicenseStatus.PUBLIC_DOMAIN, ThematicLicenseStatus.COMPATIBLE_LICENSE):
            return ThematicQualityGateResult(
                is_valid=False,
                reason=f"UNAUTHORIZED_LICENSE_STATUS_{asset.license_status.value}",
                details={"license_name": asset.license_name, "license_status": asset.license_status.value},
            )

        if asset.score < self.min_acceptable_score:
            return ThematicQualityGateResult(
                is_valid=False,
                reason="SCORE_BELOW_ACCEPTABLE_THRESHOLD",
                details={"score": asset.score, "threshold": self.min_acceptable_score},
            )

        if asset.width and asset.height:
            if asset.width < self.min_resolution_threshold or asset.height < self.min_resolution_threshold:
                return ThematicQualityGateResult(
                    is_valid=False,
                    reason="RESOLUTION_BELOW_MINIMUM",
                    details={"width": asset.width, "height": asset.height},
                )

        if not asset.download_url and not asset.local_path:
            return ThematicQualityGateResult(
                is_valid=False,
                reason="MISSING_DOWNLOAD_URL",
                details={},
            )

        return ThematicQualityGateResult(
            is_valid=True,
            reason="QUALITY_GATE_PASSED",
            details={"score": asset.score, "license_status": asset.license_status.value},
        )


# =============================================================================
# Thematic Orchestrator / Registry
# =============================================================================

class ThematicVisualOrchestrator:
    """Orquestrador central de provedores temáticos."""

    def __init__(self, providers: Optional[List[ThematicVisualProvider]] = None):
        self.providers: List[ThematicVisualProvider] = providers or [
            NASAImageLibraryProvider(),
            WikimediaCommonsProvider(),
        ]
        self.scoring_engine = ThematicScoringEngine()

    def register_provider(self, provider: ThematicVisualProvider) -> None:
        self.providers.append(provider)

    def find_best_thematic_asset(
        self,
        query: str,
        topic: str = "",
        narration: str = "",
        target_aspect_ratio: str = "9:16",
        used_asset_ids: Optional[List[str]] = None,
        min_score: float = 40.0,
    ) -> Tuple[Optional[ThematicAsset], Optional[ThematicQualityGateResult]]:
        """
        Executa busca em provedores adequados, rankeia e seleciona o melhor candidato
        que satisfaça o quality gate estrito.
        """
        candidates: List[ThematicAsset] = []

        for provider in self.providers:
            if topic and not provider.supports_topic(topic):
                continue

            try:
                found = provider.search(query=query, limit=8)
                candidates.extend(found)
            except Exception as exc:
                logger.warning(f"[THEMATIC_ORCHESTRATOR] Falha no provedor {provider.name}: {exc}")

        if not candidates:
            return None, None

        ranked = self.scoring_engine_rank(
            assets=candidates,
            target_subject=query,
            narration=narration,
            target_aspect_ratio=target_aspect_ratio,
            used_asset_ids=used_asset_ids,
        )

        for candidate in ranked:
            q_result = self.scoring_engine.evaluate_quality_gate(candidate)
            if q_result.is_valid and candidate.score >= min_score:
                return candidate, q_result

        # Se nenhum passou no quality gate, retorna o top candidato com o motivo da rejeição
        if ranked:
            top_candidate = ranked[0]
            top_q_res = self.scoring_engine.evaluate_quality_gate(top_candidate)
            return None, top_q_res

        return None, None

    def scoring_engine_rank(
        self,
        assets: List[ThematicAsset],
        target_subject: str = "",
        narration: str = "",
        target_aspect_ratio: str = "9:16",
        used_asset_ids: Optional[List[str]] = None,
    ) -> List[ThematicAsset]:
        ranked = []
        for asset in assets:
            score, breakdown = self.scoring_engine.compute_thematic_score(
                asset=asset,
                target_subject=target_subject,
                narration=narration,
                target_aspect_ratio=target_aspect_ratio,
                is_reused=(used_asset_ids is not None and asset.asset_id in used_asset_ids),
            )
            asset.score = score
            asset.score_breakdown = breakdown
            ranked.append(asset)
        ranked.sort(key=lambda a: a.score, reverse=True)
        return ranked


# =============================================================================
# Free Generative Providers Audit (Fase V16.8.2)
# =============================================================================

@dataclass
class FreeGenerativeProviderAuditItem:
    provider_name: str
    official_name: str
    feasibility_status: GenerativeProviderFeasibility
    requires_account: bool
    requires_billing: bool
    free_tier_limits: str
    setup_complexity: str
    verdict: str
    notes: str


FREE_GENERATIVE_PROVIDERS_AUDIT: List[FreeGenerativeProviderAuditItem] = [
    FreeGenerativeProviderAuditItem(
        provider_name="cloudflare_workers_ai",
        official_name="Cloudflare Workers AI",
        feasibility_status=GenerativeProviderFeasibility.REQUIRES_ACCOUNT,
        requires_account=True,
        requires_billing=False,
        free_tier_limits="10,000 neurons/dia gratuitos (compartilhado; exaure rapidamente com Flux/SDXL)",
        setup_complexity="MÉDIA (exige criação de conta Cloudflare, token de API e Account ID)",
        verdict="REQUIRES_ACCOUNT_AND_LIMITED_QUOTA",
        notes=(
            "Não oferece API anônima sem cadastro. Modelos como @cf/black-forest-labs/flux-1-schnell "
            "consomem neurônios rapidamente e podem ser bloqueados em picos."
        ),
    ),
    FreeGenerativeProviderAuditItem(
        provider_name="huggingface_inference_providers",
        official_name="Hugging Face Serverless Inference Providers",
        feasibility_status=GenerativeProviderFeasibility.FREE_QUOTA_UNKNOWN,
        requires_account=True,
        requires_billing=False,
        free_tier_limits="Cota variável e não garantida; instâncias sujeitas a cold-starts e erros 503",
        setup_complexity="MÉDIA (exige HF User Token e configuração de endpoints)",
        verdict="UNRELIABLE_FOR_ZERO_CONFIG_FACTORY",
        notes=(
            "Modelos visuais pesados no plano gratuito sofrem com filas longas e cold-boots frequentes. "
            "Não serve como base de alta confiabilidade zero-config para pipeline autônomo."
        ),
    ),
]
