# -*- coding: utf-8 -*-
"""
Coleta de anúncios via Facebook Ad Library API (Graph API oficial).
Esta é a opção PRIMÁRIA — gratuita, sem intermediários.

Documentação: https://developers.facebook.com/docs/marketing-api/reference/ads-archive/

Limitações conhecidas:
- Rate limit: ~200 req/hora por token
- Campos disponíveis mais limitados que scraping
- Vídeos: retorna URL do thumbnail, não do vídeo direto
- Requer token com permissão ads_read
"""

import time
import requests
import logging
from datetime import datetime, timedelta
from typing import Optional

from core.config import (
    FB_ACCESS_TOKEN, FB_ADS_ARCHIVE_URL, DEFAULT_COUNTRY,
    DEFAULT_ACTIVE_STATUS, DEFAULT_COUNT
)

logger = logging.getLogger(__name__)

# Campos disponíveis na API oficial
# Referência: https://developers.facebook.com/docs/marketing-api/reference/ads-archive/
AD_FIELDS = ",".join([
    "id",
    "ad_archive_id",
    "page_id",
    "page_name",
    "ad_snapshot_url",
    "ad_creative_bodies",
    "ad_creative_link_captions",
    "ad_creative_link_descriptions",
    "ad_creative_link_titles",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "impressions",
    "spend",
    "currency",
    "demographic_distribution",
    "region_distribution",
    "ad_creative_link_url",
    "bylines",
    "publisher_platforms",
    "estimated_audience_size",
])


class FacebookAdLibraryAPI:
    """
    Client para a Facebook Ad Library API.
    
    Uso:
        client = FacebookAdLibraryAPI()
        ads = client.search(keywords=["blood sugar trick"], country="US", count=100)
    """

    def __init__(self, access_token: str = FB_ACCESS_TOKEN):
        if not access_token:
            raise ValueError(
                "FB_ACCESS_TOKEN não configurado.\n"
                "1. Acesse https://developers.facebook.com/tools/explorer/\n"
                "2. Gere token com permissão ads_read\n"
                "3. Adicione ao .env: FB_ACCESS_TOKEN=seu_token"
            )
        self.token = access_token
        self.session = requests.Session()

    def _request(self, params: dict, retries: int = 3) -> dict:
        """Faz request com retry automático em rate limit."""
        params["access_token"] = self.token

        for attempt in range(retries):
            try:
                resp = self.session.get(FB_ADS_ARCHIVE_URL, params=params, timeout=30)

                # Rate limit
                if resp.status_code == 429:
                    wait = 60 * (attempt + 1)
                    logger.warning(f"Rate limit atingido. Aguardando {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout na tentativa {attempt + 1}")
                time.sleep(5)
            except requests.exceptions.RequestException as e:
                logger.error(f"Erro na request: {e}")
                if attempt == retries - 1:
                    raise

        return {}

    def search(
        self,
        keywords: list[str],
        country: str = DEFAULT_COUNTRY,
        active_status: str = DEFAULT_ACTIVE_STATUS,
        count: int = DEFAULT_COUNT,
        ad_type: str = "ALL",
        date_min: Optional[str] = None,
        date_max: Optional[str] = None,
        media_type: str = "ALL",
    ) -> list[dict]:
        """
        Busca anúncios na Ad Library para uma lista de keywords.
        Faz uma request por keyword e agrega os resultados.

        Args:
            keywords: Lista de termos de busca
            country: Código do país (BR, US, ALL)
            active_status: ACTIVE, INACTIVE, ALL
            count: Número máximo de anúncios por keyword
            ad_type: ALL, POLITICAL_AND_ISSUE_ADS
            date_min: Data mínima de veiculação (YYYY-MM-DD)
            date_max: Data máxima de veiculação (YYYY-MM-DD)
            media_type: ALL, IMAGE, VIDEO, MEME, NONE

        Returns:
            Lista de dicts com dados dos anúncios, deduplicada por ad_archive_id
        """
        if not date_min:
            # Default: últimos 30 dias
            date_min = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not date_max:
            date_max = datetime.now().strftime("%Y-%m-%d")

        all_ads: dict[str, dict] = {}  # keyed by ad_archive_id para dedup

        for keyword in keywords:
            logger.info(f"Buscando: '{keyword}' | país: {country} | status: {active_status}")

            params = {
                "search_terms": keyword,
                "ad_reached_countries": [country] if country != "ALL" else [],
                "ad_active_status": active_status,
                "ad_type": ad_type,
                "ad_delivery_date_min": date_min,
                "ad_delivery_date_max": date_max,
                "media_type": media_type,
                "fields": AD_FIELDS,
                "limit": min(count, 500),  # API limita a 500 por request
            }

            # Remove parâmetros vazios
            params = {k: v for k, v in params.items() if v}

            ads_fetched = 0
            next_cursor = None

            while ads_fetched < count:
                if next_cursor:
                    params["after"] = next_cursor

                data = self._request(params)

                if "error" in data:
                    err = data["error"]
                    logger.error(f"Erro da API: {err.get('message')} (code: {err.get('code')})")
                    # Erro 200 = permissão insuficiente no token
                    if err.get("code") == 200:
                        logger.error(
                            "Token sem permissão ads_read. "
                            "Gere um novo em https://developers.facebook.com/tools/explorer/"
                        )
                    break

                ads = data.get("data", [])
                if not ads:
                    break

                for ad in ads:
                    ad_id = ad.get("ad_archive_id") or ad.get("id")
                    if ad_id and ad_id not in all_ads:
                        ad["_keyword"] = keyword  # tag da keyword que encontrou
                        ad["_collected_at"] = datetime.now().isoformat()
                        all_ads[ad_id] = ad
                        ads_fetched += 1

                # Paginação
                paging = data.get("paging", {})
                next_cursor = paging.get("cursors", {}).get("after")
                if not next_cursor or not paging.get("next"):
                    break

                # Respeita rate limit
                time.sleep(0.5)

            logger.info(f"  → {ads_fetched} anúncios encontrados para '{keyword}'")

        logger.info(f"Total único coletado: {len(all_ads)} anúncios")
        return list(all_ads.values())

    def get_page_ads_count(self, page_id: str) -> int:
        """
        Retorna o número total de anúncios ativos de uma página.
        Útil para estimar escala de um anunciante.
        """
        params = {
            "search_page_ids": [page_id],
            "ad_active_status": "ACTIVE",
            "fields": "id",
            "limit": 1,
        }
        data = self._request(params)
        # A API não retorna contagem direta — usamos o paging summary
        return data.get("paging", {}).get("total_count", 0)

    @staticmethod
    def normalize_ad(raw_ad: dict) -> dict:
        """
        Normaliza um anúncio da API para o schema interno do projeto.
        Schema compatível com o que o Apify retorna (para intercambialidade).
        """
        bodies = raw_ad.get("ad_creative_bodies") or []
        titles = raw_ad.get("ad_creative_link_titles") or []
        descriptions = raw_ad.get("ad_creative_link_descriptions") or []

        start_date = raw_ad.get("ad_delivery_start_time", "")
        stop_date = raw_ad.get("ad_delivery_stop_time", "")

        # Calcula dias rodando
        days_running = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(stop_date.replace("Z", "+00:00")) if stop_date else datetime.now().astimezone()
                days_running = (end_dt - start_dt).days
            except Exception:
                pass

        return {
            "ad_archive_id": raw_ad.get("ad_archive_id") or raw_ad.get("id"),
            "page_id": raw_ad.get("page_id"),
            "page_name": raw_ad.get("page_name"),
            "ad_snapshot_url": raw_ad.get("ad_snapshot_url"),
            "ad_body": " | ".join(bodies),
            "ad_title": " | ".join(titles),
            "ad_description": " | ".join(descriptions),
            "ad_link_url": raw_ad.get("ad_creative_link_url"),
            "start_date": start_date,
            "stop_date": stop_date,
            "days_running": days_running,
            "active_status": "ACTIVE" if not stop_date else "INACTIVE",
            "impressions_min": raw_ad.get("impressions", {}).get("lower_bound"),
            "impressions_max": raw_ad.get("impressions", {}).get("upper_bound"),
            "spend_min": raw_ad.get("spend", {}).get("lower_bound"),
            "spend_max": raw_ad.get("spend", {}).get("upper_bound"),
            "currency": raw_ad.get("currency"),
            "publisher_platforms": raw_ad.get("publisher_platforms", []),
            "keyword_found": raw_ad.get("_keyword"),
            "collected_at": raw_ad.get("_collected_at"),
            # Campos de análise (preenchidos depois pelo analysis/)
            "ad_type": None,
            "industry": None,
            "hook": None,
            "text_summary": None,
            "image_analysis": None,
            "video_transcript": None,
            "video_analysis": None,
            "swipe_score": None,
        }


def test_token() -> bool:
    """Verifica se o token está válido e tem permissões corretas."""
    try:
        client = FacebookAdLibraryAPI()
        # Busca simples de 1 anúncio para testar
        result = client.search(
            keywords=["blood sugar"],
            country="US",
            count=1,
        )
        logger.info(f"Token válido. Teste retornou {len(result)} anúncio(s).")
        return True
    except ValueError as e:
        logger.error(str(e))
        return False
    except Exception as e:
        logger.error(f"Erro ao testar token: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_token()
