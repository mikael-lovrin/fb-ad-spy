# -*- coding: utf-8 -*-
"""
Fallback Apify — usa o actor curious_coder/facebook-ads-library-scraper.
Usar apenas quando a FB Graph API nativa não cobrir o caso de uso.
Custo: ~$0.50-2.00 por run.
"""

import logging
import requests
from datetime import datetime, timedelta
from core.config import APIFY_ACTOR_URL, DEFAULT_COUNTRY, DEFAULT_COUNT

logger = logging.getLogger(__name__)


class ApifyScraper:
    """
    Client para o Apify actor de Facebook Ads Library.

    Uso:
        scraper = ApifyScraper()
        ads = scraper.search(keywords=["blood sugar trick"], country="US", count=50)
    """

    def __init__(self, actor_url: str = APIFY_ACTOR_URL):
        if not actor_url:
            raise ValueError(
                "APIFY_ACTOR_URL não configurado.\n"
                "Adicione ao .env: APIFY_ACTOR_URL=https://api.apify.com/v2/actors/..."
            )
        self.actor_url = actor_url

    def search(
        self,
        keywords: list[str],
        country: str = DEFAULT_COUNTRY,
        count: int = DEFAULT_COUNT,
        active_status: str = "ACTIVE",
        lookback_days: int = 30,
        dedup_by_page: bool = True,
    ) -> list[dict]:
        """
        Executa o actor Apify e retorna anúncios crus.

        Args:
            keywords: Lista de termos de busca
            country: Código do país (BR, US, ALL)
            count: Número máximo de resultados
            active_status: ACTIVE, INACTIVE, ALL
            lookback_days: Janela de lookback em dias (padrão 30)
            dedup_by_page: Se True, retorna apenas 1 anúncio por page_id
                           (economiza tokens Claude — ver guia.pdf seção 4)

        Returns:
            Lista de dicts com dados brutos do Apify
        """
        date_min = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        date_max = datetime.now().strftime("%Y-%m-%d")

        all_ads: dict[str, dict] = {}      # dedup por ad_archive_id
        seen_pages: set[str] = set()       # dedup por page_id (quando dedup_by_page=True)

        for keyword in keywords:
            logger.info(f"[Apify] Buscando: '{keyword}' | país: {country} | {date_min} → {date_max}")

            payload = {
                "searchTerms": keyword,           # actor espera string, não lista
                "country": country if country != "ALL" else "",
                "activeStatus": active_status,
                "searchType": "keyword_exact_phrase",  # evita ads não-relevantes (guia.pdf §4)
                "adDeliveryDateMin": date_min,
                "adDeliveryDateMax": date_max,
                "totalRecordsRequired": min(count, 200),
            }

            try:
                resp = requests.post(
                    self.actor_url,
                    json=payload,
                    timeout=120,
                )
                resp.raise_for_status()
                ads = resp.json()

                if not isinstance(ads, list):
                    logger.warning(f"[Apify] Resposta inesperada: {type(ads)}")
                    continue

                for ad in ads:
                    ad_id = ad.get("adArchiveID") or ad.get("id") or ad.get("ad_archive_id")
                    page_id = str(ad.get("pageID") or ad.get("page_id") or "")

                    if not ad_id or str(ad_id) in all_ads:
                        continue
                    if dedup_by_page and page_id and page_id in seen_pages:
                        continue  # já temos um ad desta página — economiza tokens

                    ad["_keyword"] = keyword
                    ad["_collected_at"] = datetime.now().isoformat()
                    all_ads[str(ad_id)] = ad
                    if page_id:
                        seen_pages.add(page_id)

                logger.info(f"  → {len(ads)} anúncios retornados para '{keyword}'")

            except requests.exceptions.Timeout:
                logger.error(f"[Apify] Timeout ao buscar '{keyword}'")
            except requests.exceptions.RequestException as e:
                logger.error(f"[Apify] Erro na request: {e}")

        logger.info(f"[Apify] Total único: {len(all_ads)}")
        return list(all_ads.values())

    @staticmethod
    def normalize_ad(raw_ad: dict) -> dict:
        """
        Normaliza campo do Apify para o schema interno.
        O Apify usa nomes de campo diferentes da API oficial.
        """
        # O actor Apify pode retornar em diferentes formatos — mapeamento defensivo
        bodies = raw_ad.get("adCreativeBodies") or raw_ad.get("ad_creative_bodies") or []
        titles = raw_ad.get("adCreativeLinkTitles") or raw_ad.get("ad_creative_link_titles") or []

        start_date = raw_ad.get("startDate") or raw_ad.get("ad_delivery_start_time", "")
        stop_date = raw_ad.get("stopDate") or raw_ad.get("ad_delivery_stop_time", "")

        days_running = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                end_dt = (
                    datetime.fromisoformat(stop_date.replace("Z", "+00:00"))
                    if stop_date
                    else datetime.now().astimezone()
                )
                days_running = (end_dt - start_dt).days
            except Exception:
                pass

        return {
            "ad_archive_id": str(
                raw_ad.get("adArchiveID") or raw_ad.get("ad_archive_id") or raw_ad.get("id", "")
            ),
            "page_id": raw_ad.get("pageID") or raw_ad.get("page_id"),
            "page_name": raw_ad.get("pageName") or raw_ad.get("page_name"),
            "ad_snapshot_url": raw_ad.get("adSnapshotURL") or raw_ad.get("ad_snapshot_url"),
            "ad_body": " | ".join(bodies) if isinstance(bodies, list) else str(bodies),
            "ad_title": " | ".join(titles) if isinstance(titles, list) else str(titles),
            "ad_description": "",
            "ad_link_url": raw_ad.get("adCreativeLinkURL") or raw_ad.get("ad_link_url"),
            "start_date": start_date,
            "stop_date": stop_date,
            "days_running": days_running,
            "active_status": "ACTIVE" if not stop_date else "INACTIVE",
            "impressions_min": None,
            "impressions_max": None,
            "spend_min": None,
            "spend_max": None,
            "currency": raw_ad.get("currency"),
            "publisher_platforms": raw_ad.get("publisherPlatforms") or [],
            "keyword_found": raw_ad.get("_keyword"),
            "collected_at": raw_ad.get("_collected_at"),
            "_image_url": raw_ad.get("imageURL") or raw_ad.get("image_url", ""),
            "_video_url": raw_ad.get("videoURL") or raw_ad.get("video_url", ""),
            # Campos de análise (preenchidos depois)
            "ad_type": None,
            "industry": None,
            "hook": None,
            "text_summary": None,
            "image_analysis": None,
            "video_transcript": None,
            "video_analysis": None,
            "swipe_score": None,
        }
