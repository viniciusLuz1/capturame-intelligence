"""
scraper/cotacoes.py
===================
Fase 2 - Coleta de cotacoes da CapturaME.

Usa a API DataTables descoberta na Fase 1:
  GET /dashboard/provider/getquoteslistGets

Autenticacao via Playwright APIRequestContext (reutiliza storage_state.json).
Paginacao automatica ate coletar todos os registros disponiveis.
"""

import time
from typing import Optional

from playwright.sync_api import APIRequestContext

from config.config import BASE_URL
from scraper.logger import get_logger

log = get_logger(__name__)

ENDPOINT = f"{BASE_URL}/dashboard/provider/getquoteslistGets"
PAGE_SIZE = 100
RATE_LIMIT_S = 0.3


class CotacaoScraper:
    """
    Coleta todas as cotacoes via API DataTables da CapturaME.

    Parametros
    ----------
    api : APIRequestContext
        Contexto de requisicoes Playwright ja autenticado.
    limit : int | None
        Limita o numero maximo de registros.
    """

    def __init__(self, api: APIRequestContext, limit: Optional[int] = None):
        self.api = api
        self.limit = limit

    def coletar_todas(self, db=None) -> list:
        """
        Pagina pela API e retorna todas as cotacoes.
        Se db for fornecido, faz upsert em tempo real.
        """
        start = 0
        total_disponivel = None
        coletadas = []

        log.info(f"[Cotacoes] Iniciando coleta. Endpoint: {BASE_URL}{ENDPOINT}")

        while True:
            params = self._build_params(start)
            try:
                resp = self.api.get(ENDPOINT, params=params)
                if not resp.ok:
                    log.error(f"[Cotacoes] HTTP {resp.status} (start={start}): {resp.text()[:200]}")
                    break
                data = resp.json()
            except Exception as exc:
                log.error(f"[Cotacoes] Erro na requisicao (start={start}): {exc}")
                break

            if total_disponivel is None:
                total_disponivel = data.get("iTotalDisplayRecords", 0)
                log.info(f"[Cotacoes] Total disponivel: {total_disponivel:,}")

            batch = data.get("aaData", [])
            if not batch:
                break

            coletadas.extend(batch)

            if db:
                for row in batch:
                    db.upsert_cotacao(row)
                db.commit()

            log.info(f"[Cotacoes] Coletadas: {len(coletadas):,} / {total_disponivel:,}")

            if self.limit and len(coletadas) >= self.limit:
                coletadas = coletadas[: self.limit]
                break

            start += PAGE_SIZE
            if start >= total_disponivel:
                break

            time.sleep(RATE_LIMIT_S)

        log.info(f"[Cotacoes] Coleta concluida. Total: {len(coletadas):,} cotacoes.")
        return coletadas

    def _build_params(self, start: int) -> dict:
        return {
            "draw": (start // PAGE_SIZE) + 1,
            "start": start,
            "length": PAGE_SIZE,
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": 0,
            "order[0][dir]": "asc",
            "meustatus": "",
            "titulo": "",
        }
