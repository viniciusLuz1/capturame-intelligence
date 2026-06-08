"""
scraper/itens.py
================
Fase 3 – Coleta de itens por leilão.

Fluxo por leilão:
  1. GET /dashboard/provider/document/{code}  → HTML com resp_id e local de entrega
  2. Extrai resp_id da tag <input name="resp_id">
  3. Extrai local_entrega do texto "Local de entrega..."
  4. GET GetQuotesListProductsV3?quoteid={id}&respid={resp_id}  → JSON com itens
  5. Persiste em leilao_itens e atualiza leiloes.local_entrega

Autenticação via Playwright APIRequestContext (contexto vivo da Fase 2).
"""

import re
import time
from typing import Optional

from playwright.sync_api import APIRequestContext

from config.config import BASE_URL
from scraper.logger import get_logger

log = get_logger(__name__)

ENDPOINT_DOC = f"{BASE_URL}/dashboard/provider/document"
ENDPOINT_ITENS = f"{BASE_URL}/dashboard/provider/GetQuotesListProductsV3"
PAGE_SIZE = 100
RATE_LIMIT_S = 0.5

# Regex para extrair resp_id do HTML
RE_RESP_ID = re.compile(r'name=["\']resp_id["\'][^>]*value=["\'](\d+)["\']', re.IGNORECASE)
RE_RESP_ID_ALT = re.compile(r'value=["\'](\d+)["\'][^>]*name=["\']resp_id["\']', re.IGNORECASE)

# Regex para extrair local de entrega
RE_LOCAL_ENTREGA = re.compile(
    r'Local de entrega[^\n<]{0,600}',
    re.IGNORECASE | re.DOTALL,
)
RE_CIDADE_UF = re.compile(
    r'([A-ZÁÉÍÓÚ][a-záéíóúâêîôûãõ]+'
    r'(?:\s+(?:de|do|da|dos|das))?'
    r'(?:\s+[A-ZÁÉÍÓÚ][a-záéíóúâêîôûãõ]+)?)'
    r'\s+([A-Z]{2})\s+(\d{5}-?\d{3})',
)


class ItenScraper:
    """
    Coleta os itens de cada leilão usando APIRequestContext.

    Parâmetros
    ----------
    api : APIRequestContext
        Contexto de requisições Playwright já autenticado.
    limit_leiloes : int | None
        Limita o número de leilões processados (útil para testes).
    """

    def __init__(self, api: APIRequestContext, limit_leiloes: Optional[int] = None):
        self.api = api
        self.limit_leiloes = limit_leiloes

    def coletar_itens_todos(self, db) -> dict:
        """
        Coleta itens para todos os leilões sem itens no banco.
        Prioriza leilões abertos (status='open').
        Retorna estatísticas.
        """
        pendentes = db.get_leiloes_sem_itens()
        total = len(pendentes)
        log.info(f"[Itens] Leilões sem itens: {total:,}")

        if self.limit_leiloes:
            pendentes = pendentes[: self.limit_leiloes]
            log.info(f"[Itens] Limitado a {self.limit_leiloes} leilões para este run.")

        processados = 0
        itens_salvos = 0
        erros = 0

        for idx, (leilao_id, code) in enumerate(pendentes, 1):
            try:
                n_itens = self._processar_leilao(leilao_id, code, db)
                itens_salvos += n_itens
                processados += 1

                if idx % 10 == 0 or idx == len(pendentes):
                    log.info(
                        f"[Itens] Progresso: {idx}/{len(pendentes)} | "
                        f"itens salvos: {itens_salvos:,}"
                    )

            except Exception as exc:
                erros += 1
                log.warning(f"[Itens] Erro em leilao_id={leilao_id} code={code}: {exc}")

            time.sleep(RATE_LIMIT_S)

        db.commit()
        stats = {
            "processados": processados,
            "itens_salvos": itens_salvos,
            "erros": erros,
        }
        log.info(f"[Itens] Concluído: {stats}")
        return stats

    def _processar_leilao(self, leilao_id: int, code: str, db) -> int:
        """
        Processa um único leilão: extrai resp_id, local de entrega e itens.
        Retorna número de itens salvos.
        """
        # 1. Busca a página do documento
        resp = self.api.get(f"{ENDPOINT_DOC}/{code}", timeout=15000)
        if not resp.ok:
            log.debug(f"[Itens] HTTP {resp.status} para document/{code}")
            return 0

        html = resp.text()

        # 2. Extrai resp_id
        resp_id = self._extrair_resp_id(html)
        if not resp_id:
            log.debug(f"[Itens] resp_id não encontrado para leilao_id={leilao_id}")
            return 0

        # 3. Extrai local de entrega
        local, cidade, uf, cep = self._extrair_entrega(html)
        if local:
            db.update_leilao_entrega(leilao_id, local, cidade, uf, cep)

        # 4. Busca itens via GetQuotesListProductsV3
        itens = self._buscar_itens(leilao_id, resp_id)

        # 5. Persiste itens
        for item in itens:
            db.upsert_leilao_item(leilao_id, item)

        if itens:
            db.commit()

        log.debug(
            f"[Itens] leilao_id={leilao_id} | resp_id={resp_id} | "
            f"itens={len(itens)} | cidade={cidade or '-'}"
        )
        return len(itens)

    def _buscar_itens(self, leilao_id: int, resp_id: str) -> list:
        """Pagina pela API de itens e retorna todos."""
        start = 0
        total_disponivel = None
        itens = []

        while True:
            params = {
                "draw": (start // PAGE_SIZE) + 1,
                "start": start,
                "length": PAGE_SIZE,
                "search[value]": "",
                "search[regex]": "false",
                "order[0][column]": 0,
                "order[0][dir]": "asc",
                "quoteid": leilao_id,
                "respid": resp_id,
            }
            resp = self.api.get(ENDPOINT_ITENS, params=params, timeout=15000)
            if not resp.ok:
                break

            data = resp.json()
            if total_disponivel is None:
                total_disponivel = data.get("iTotalDisplayRecords", 0)

            batch = data.get("aaData", [])
            if not batch:
                break

            itens.extend(batch)
            start += PAGE_SIZE
            if start >= (total_disponivel or 0):
                break

        return itens

    @staticmethod
    def _extrair_resp_id(html: str) -> Optional[str]:
        m = RE_RESP_ID.search(html) or RE_RESP_ID_ALT.search(html)
        return m.group(1) if m else None

    @staticmethod
    def _extrair_entrega(html: str) -> tuple:
        """Retorna (local_texto, cidade, uf, cep)."""
        # Remove tags HTML para trabalhar com texto puro
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&[a-zA-Z#\d]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        m_local = RE_LOCAL_ENTREGA.search(text)
        if not m_local:
            return None, None, None, None

        local_texto = m_local.group(0)[:400].strip()

        # Extrai Cidade UF CEP dentro do local
        m_addr = RE_CIDADE_UF.search(local_texto)
        if m_addr:
            cidade = m_addr.group(1).strip()
            uf = m_addr.group(2)
            cep = m_addr.group(3)
        else:
            cidade = uf = cep = None

        return local_texto, cidade, uf, cep
