"""
scraper/leiloes.py
==================
Fase 2 - Coleta de leiloes da CapturaME.

Usa a API DataTables descoberta na Fase 1:
  GET /dashboard/provider/getauctionslistGetsV1

Autenticacao via Playwright APIRequestContext (reutiliza storage_state.json).
Paginacao automatica ate coletar todos os registros disponiveis.
"""

import time
from typing import Optional

from playwright.sync_api import APIRequestContext

from config.config import BASE_URL
from scraper.logger import get_logger

log = get_logger(__name__)

ENDPOINT = f"{BASE_URL}/dashboard/provider/getauctionslistGetsV1"
PAGE_SIZE = 100
RATE_LIMIT_S = 0.3


class LeilaoScraper:
    """
    Coleta todos os leiloes via API DataTables da CapturaME.

    Parametros
    ----------
    api : APIRequestContext
        Contexto de requisicoes Playwright ja autenticado.
    limit : int | None
        Limita o numero maximo de registros (util para testes).
    """

    def __init__(self, api: APIRequestContext, limit: Optional[int] = None):
        self.api = api
        self.limit = limit

    def coletar_todos(self, db=None) -> list:
        """
        Pagina pela API e retorna todos os leiloes.
        Se db for fornecido, faz upsert em tempo real.
        """
        start = 0
        total_disponivel = None
        coletados = []

        log.info(f"[Leiloes] Iniciando coleta. Endpoint: {BASE_URL}{ENDPOINT}")

        while True:
            params = self._build_params(start)
            try:
                resp = self.api.get(ENDPOINT, params=params)
                if not resp.ok:
                    log.error(f"[Leiloes] HTTP {resp.status} (start={start}): {resp.text()[:200]}")
                    break
                data = resp.json()
            except Exception as exc:
                log.error(f"[Leiloes] Erro na requisicao (start={start}): {exc}")
                break

            if total_disponivel is None:
                total_disponivel = data.get("iTotalDisplayRecords", 0)
                log.info(f"[Leiloes] Total disponivel: {total_disponivel:,}")

            batch = data.get("aaData", [])
            if not batch:
                break

            coletados.extend(batch)

            if db:
                for row in batch:
                    db.upsert_leilao(row)
                db.commit()

            log.info(f"[Leiloes] Coletados: {len(coletados):,} / {total_disponivel:,}")

            if self.limit and len(coletados) >= self.limit:
                coletados = coletados[: self.limit]
                break

            start += PAGE_SIZE
            if start >= total_disponivel:
                break

            time.sleep(RATE_LIMIT_S)

        log.info(f"[Leiloes] Coleta concluida. Total: {len(coletados):,} leiloes.")
        return coletados

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
