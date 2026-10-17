"""
app/services/quiz_assets.py
===========================
VIDEO FACTORY — FASE Q3: AUTOMATIZAÇÃO DE IMAGENS E ASSETS
Ambiente: DEV — D:\\Projetos\\MoneyPrinterTurbo

Automatiza a seleção, busca, deduplicação, preparação em resolução ideal
e registro de proveniência de imagens para quizzes produzidos pela Q2,
entregando os assets e o JSON prontos para a QuizEngine Q1.

Reutiliza integralmente a infraestrutura de provedores existente:
- Pexels Photo API (com rotação de API keys via material.py)
- Pixabay Photo API (com detecção passiva via material.has_material_api_keys)
- Acervo local e gerador de cartões estilizados de alta fidelidade como fallback
- Histórico persistente de deduplicação (storage/quiz_history/used_images.json)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from app.config import config
from app.services import material


@dataclass
class ImageProvenance:
    asset_id: str
    provider: str
    source_url: str
    creator_name: str
    creator_url: str
    license: str
    content_hash: str
    local_path: str
    resolution: Tuple[int, int]
    query: str
    question_id: str
    option_slot: str  # "top" ou "bottom"
    status: str = "READY"
    created_at: float = field(default_factory=time.time)


class QuizAssetManager:
    """
    Gerenciador de ativos visuais para Quiz Engine.
    Resolve imagens de cada pergunta com deduplicação rigorosa e proveniência auditável.
    """

    TARGET_RESOLUTION = (1200, 1066)  # Resolução ideal para Ken Burns zoompan em split 1080x960

    def __init__(
        self,
        history_dir: str = "storage/quiz_history",
        default_images_dir: str = "storage/poc_quiz/images_q3",
    ):
        self.history_dir = history_dir
        self.default_images_dir = default_images_dir
        self.used_images_file = os.path.join(history_dir, "used_images.json")

        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(self.default_images_dir, exist_ok=True)

        self.used_images_history: List[Dict[str, Any]] = self._load_used_images()

    def _load_used_images(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.used_images_file):
            try:
                with open(self.used_images_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[QUIZ_ASSETS] Erro ao carregar histórico de imagens: {e}")
        return []

    def _save_used_images(self) -> None:
        try:
            tmp_path = self.used_images_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.used_images_history, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.used_images_file)
        except Exception as e:
            logger.error(f"[QUIZ_ASSETS] Erro ao salvar histórico de imagens: {e}")

    def is_image_used(self, asset_id: str, content_hash: Optional[str] = None) -> bool:
        aid = str(asset_id).strip()
        for item in self.used_images_history:
            if str(item.get("asset_id", "")).strip() == aid and aid != "":
                return True
            if content_hash and item.get("content_hash") == content_hash:
                return True
        return False

    def record_used_image(
        self,
        asset_id: str,
        provider: str,
        content_hash: str,
        query: str,
        source_url: str = "",
    ) -> None:
        self.used_images_history.append({
            "asset_id": str(asset_id),
            "provider": provider,
            "content_hash": content_hash,
            "query": query,
            "source_url": source_url,
            "timestamp": time.time(),
        })
        self._save_used_images()

    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def prepare_image(
        image_bytes: bytes,
        target_size: Tuple[int, int] = TARGET_RESOLUTION,
    ) -> Image.Image:
        """
        Carrega imagem em Pillow, converte para RGB, aplica Aspect-Fill
        (redimensionamento proporcional + center crop) para garantir renderização perfeita.
        """
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        target_w, target_h = target_size
        img_w, img_h = img.size

        # Calcula escala para cobrir toda a área alvo (aspect fill)
        scale = max(target_w / img_w, target_h / img_h)
        new_w = max(1, round(img_w * scale))
        new_h = max(1, round(img_h * scale))

        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Center crop
        left = max(0, (new_w - target_w) // 2)
        top = max(0, (new_h - target_h) // 2)
        right = left + target_w
        bottom = top + target_h

        cropped = resized.crop((left, top, right, bottom))
        return cropped

    def _search_pexels(
        self,
        query: str,
        task_used_ids: Set[str],
    ) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """Busca imagens fotográficas no Pexels filtrando IDs já utilizados."""
        if not material.has_material_api_keys("pexels"):
            return None

        try:
            api_key = material.get_api_key("pexels_api_keys")
        except Exception as e:
            logger.warning(f"[QUIZ_ASSETS] Falha ao obter chave Pexels: {e}")
            return None

        headers = {
            "Authorization": api_key,
            "User-Agent": "VideoFactory-QuizEngine/1.0",
        }
        url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page=12&orientation=landscape"

        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                logger.warning(f"[QUIZ_ASSETS] Pexels retornou status {r.status_code} para query '{query}'")
                return None

            data = r.json()
            photos = data.get("photos", [])
            for p in photos:
                p_id = str(p.get("id"))
                if self.is_image_used(p_id) or p_id in task_used_ids:
                    continue

                # Seleciona melhor fonte de imagem (large2x ou large)
                src = p.get("src", {})
                img_url = src.get("large2x") or src.get("large") or src.get("original")
                if not img_url:
                    continue

                img_resp = requests.get(img_url, timeout=15)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    meta = {
                        "asset_id": p_id,
                        "provider": "pexels",
                        "source_url": p.get("url", ""),
                        "creator_name": p.get("photographer", "Pexels Contributor"),
                        "creator_url": p.get("photographer_url", ""),
                        "license": "Pexels Free to Use License",
                    }
                    return img_resp.content, meta

        except Exception as e:
            logger.warning(f"[QUIZ_ASSETS] Erro na busca Pexels para '{query}': {e}")

        return None

    def _search_pixabay(
        self,
        query: str,
        task_used_ids: Set[str],
    ) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """Busca imagens fotográficas no Pixabay filtrando IDs já utilizados."""
        if not material.has_material_api_keys("pixabay"):
            return None

        try:
            api_key = material.get_api_key("pixabay_api_keys")
        except Exception:
            return None

        url = (
            f"https://pixabay.com/api/?key={api_key}"
            f"&q={requests.utils.quote(query)}"
            f"&image_type=photo&orientation=horizontal&per_page=12"
        )

        try:
            r = requests.get(url, timeout=12)
            if r.status_code != 200:
                return None

            data = r.json()
            hits = data.get("hits", [])
            for h in hits:
                h_id = str(h.get("id"))
                if self.is_image_used(h_id) or h_id in task_used_ids:
                    continue

                img_url = h.get("largeImageURL") or h.get("webformatURL")
                if not img_url:
                    continue

                img_resp = requests.get(img_url, timeout=15)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    meta = {
                        "asset_id": h_id,
                        "provider": "pixabay",
                        "source_url": h.get("pageURL", ""),
                        "creator_name": h.get("user", "Pixabay Contributor"),
                        "creator_url": f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/",
                        "license": "Pixabay Content License (Free for commercial use)",
                    }
                    return img_resp.content, meta

        except Exception as e:
            logger.warning(f"[QUIZ_ASSETS] Erro na busca Pixabay para '{query}': {e}")

        return None

    def _create_fallback_card(
        self,
        title: str,
        theme_slot: str,
        target_size: Tuple[int, int] = TARGET_RESOLUTION,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Cria fallback visual de alta fidelidade estilizado com gradiente e tipografia
        quando nenhum provedor de stock footage retornar resultado novo.
        """
        width, height = target_size
        img = Image.new("RGB", (width, height), (20, 24, 34))
        draw = ImageDraw.Draw(img)

        # Paleta de acordo com o slot
        if theme_slot == "top":
            base_col = (145, 18, 32)
            grad_end = (60, 6, 12)
            frame_col = (255, 75, 85)
        else:
            base_col = (16, 55, 145)
            grad_end = (6, 20, 60)
            frame_col = (65, 155, 255)

        # Gradiente vertical suave
        for y in range(height):
            ratio = y / height
            r = int(base_col[0] * (1 - ratio) + grad_end[0] * ratio)
            g = int(base_col[1] * (1 - ratio) + grad_end[1] * ratio)
            b = int(base_col[2] * (1 - ratio) + grad_end[2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Moldura interna sutil
        margin = 36
        draw.rounded_rectangle(
            [margin, margin, width - margin, height - margin],
            radius=24,
            outline=frame_col,
            width=5,
        )

        # Tipografia
        font_path = "resource/fonts/BeVietnamPro-Bold.ttf"
        font = (
            ImageFont.truetype(font_path, 52)
            if os.path.exists(font_path)
            else ImageFont.load_default()
        )

        display_text = title[:45].upper()
        # Sombra do texto
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 3)]:
            draw.text((width // 2 + dx, height // 2 + dy), display_text, font=font, fill=(0, 0, 0), anchor="mm")
        draw.text((width // 2, height // 2), display_text, font=font, fill=(255, 255, 255), anchor="mm")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        raw_bytes = buf.getvalue()

        card_id = f"fallback_{hashlib.md5(title.encode()).hexdigest()[:8]}"
        meta = {
            "asset_id": card_id,
            "provider": "local_fallback",
            "source_url": "internal://video-factory/stylized-card",
            "creator_name": "Video Factory Engine",
            "creator_url": "",
            "license": "Internal Generated / Video Factory",
        }
        return raw_bytes, meta

    def resolve_option_image(
        self,
        query: str,
        title: str,
        slot: str,
        question_id: str,
        dest_filename: str,
        output_dir: str,
        task_used_ids: Set[str],
    ) -> ImageProvenance:
        """
        Resolve uma imagem para uma opção de quiz:
        1. Tenta Pexels (deduplicado).
        2. Tenta Pixabay se disponível (deduplicado).
        3. Se falhar, usa fallback visual estilizado.
        4. Redimensiona/recorta em 1200x1066.
        5. Salva em disco e registra proveniência.
        """
        dest_path = os.path.join(output_dir, dest_filename)

        raw_bytes: Optional[bytes] = None
        meta: Optional[Dict[str, Any]] = None

        # 1. Pexels
        if query:
            res = self._search_pexels(query, task_used_ids)
            if res:
                raw_bytes, meta = res

        # 2. Pixabay (se Pexels não encontrou)
        if not raw_bytes and query:
            res = self._search_pixabay(query, task_used_ids)
            if res:
                raw_bytes, meta = res

        # 3. Fallback estilizado
        if not raw_bytes:
            logger.info(f"[QUIZ_ASSETS] Aplicando fallback estilizado para '{title}' ({slot})")
            raw_bytes, meta = self._create_fallback_card(title, slot)

        assert raw_bytes is not None and meta is not None

        content_hash = self.calculate_sha256(raw_bytes)
        asset_id = meta["asset_id"]

        # 4. Prepara a imagem em resolução ideal (1200x1066)
        prepared_img = self.prepare_image(raw_bytes, self.TARGET_RESOLUTION)
        prepared_img.save(dest_path, "JPEG", quality=92, optimize=True)

        # 5. Registra nos usados da tarefa e persistência
        task_used_ids.add(asset_id)
        self.record_used_image(
            asset_id=asset_id,
            provider=meta["provider"],
            content_hash=content_hash,
            query=query,
            source_url=meta.get("source_url", ""),
        )

        provenance = ImageProvenance(
            asset_id=asset_id,
            provider=meta["provider"],
            source_url=meta.get("source_url", ""),
            creator_name=meta.get("creator_name", ""),
            creator_url=meta.get("creator_url", ""),
            license=meta.get("license", ""),
            content_hash=content_hash,
            local_path=dest_path.replace("\\", "/"),
            resolution=self.TARGET_RESOLUTION,
            query=query,
            question_id=question_id,
            option_slot=slot,
            status="READY",
        )
        return provenance

    def process_quiz(
        self,
        quiz_data: Dict[str, Any],
        output_images_dir: Optional[str] = None,
        output_json_path: Optional[str] = None,
        output_video_path: Optional[str] = None,
        output_thumbnail_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Recebe o JSON de quiz (da Q2), obtém e prepara todas as imagens necessárias,
        registra proveniência de cada asset e entrega o JSON pronto para a QuizEngine Q1.
        """
        if output_video_path:
            quiz_data["output_video_path"] = output_video_path
        if output_thumbnail_path:
            quiz_data["output_thumbnail_path"] = output_thumbnail_path

        img_dir = output_images_dir or self.default_images_dir
        os.makedirs(img_dir, exist_ok=True)

        task_used_ids: Set[str] = set()
        provenance_list: List[Dict[str, Any]] = []

        questions = quiz_data.get("questions", [])
        logger.info(f"[QUIZ_ASSETS] Iniciando resolução de imagens para {len(questions)} perguntas em '{img_dir}'")

        for idx, q in enumerate(questions, 1):
            q_id = q.get("id", f"q{idx}")

            # Top option
            top = q.get("top", {})
            top_query = top.get("image_query", "")
            top_title = top.get("title", f"Opção A {q_id}")
            top_filename = f"{q_id}_top.jpg"

            prov_top = self.resolve_option_image(
                query=top_query,
                title=top_title,
                slot="top",
                question_id=q_id,
                dest_filename=top_filename,
                output_dir=img_dir,
                task_used_ids=task_used_ids,
            )
            top["image_name"] = top_filename
            top["image_path"] = prov_top.local_path
            provenance_list.append(asdict(prov_top))

            # Bottom option
            bottom = q.get("bottom", {})
            bot_query = bottom.get("image_query", "")
            bot_title = bottom.get("title", f"Opção B {q_id}")
            bot_filename = f"{q_id}_bot.jpg"

            prov_bot = self.resolve_option_image(
                query=bot_query,
                title=bot_title,
                slot="bottom",
                question_id=q_id,
                dest_filename=bot_filename,
                output_dir=img_dir,
                task_used_ids=task_used_ids,
            )
            bottom["image_name"] = bot_filename
            bottom["image_path"] = prov_bot.local_path
            provenance_list.append(asdict(prov_bot))

        # Atualiza configurações de thumbnail com as opções da primeira pergunta
        if questions:
            first_q = questions[0]
            quiz_data["thumbnail_settings"] = {
                "top_option": {
                    "title": first_q.get("top", {}).get("title", ""),
                    "tag": first_q.get("top", {}).get("tag", "OPÇÃO A"),
                    "image_name": first_q.get("top", {}).get("image_name", "q1_top.jpg"),
                },
                "bottom_option": {
                    "title": first_q.get("bottom", {}).get("title", ""),
                    "tag": first_q.get("bottom", {}).get("tag", "OPÇÃO B"),
                    "image_name": first_q.get("bottom", {}).get("image_name", "q1_bot.jpg"),
                },
                "banner_text": quiz_data.get("quiz_title", "QUAL VOCÊ ESCOLHERIA?"),
            }

        quiz_data["images_dir"] = img_dir.replace("\\", "/")
        quiz_data["asset_provenance"] = provenance_list
        quiz_data["assets_ready"] = True
        quiz_data["assets_resolved_at"] = time.time()

        if output_json_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(quiz_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[QUIZ_ASSETS] JSON pronto para QuizEngine salvo em: {output_json_path}")

        return quiz_data
