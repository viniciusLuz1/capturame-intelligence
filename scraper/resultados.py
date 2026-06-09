"""
scraper/resultados.py
=====================
Fase 4 – Coleta de resultados (vencedores) por leilão fechado.

Fluxo por leilão:
  1. GET /dashboard/provider/result/document/{code}  → HTML com tabela de propostas
  2. Parse das tabelas: cada <table> = um item licitado
     - <thead> primeiro <th> = nome do item
     - <tbody> linhas ordenadas por preço (primeira = vencedor)
  3. Persiste em leilao_resultados

Apenas processa leilões com status='close' que ainda não têm resultado.
"""

import re
import time
from typing import Optional

from playwright.sync_api import APIRequestContext

from config.config import BASE_URL
from scraper.logger import get_logger

log = get_logger(__name__)

ENDPOINT_RESULTADO = f"{BASE_URL}/dashboard/provider/result/document"
RATE_LIMIT_S = 0.5

RE_TAG = re.compile(r'<[^>]+>')
RE_ENTITY = re.compile(r'&[a-zA-Z#\d]+;')
RE_TABLES = re.compile(r'<table[^>]*>(.*?)</table>', re.DOTALL | re.IGNORECASE)
RE_THEAD_TH = re.compile(r'<thead[^>]*>.*?<th[^>]*>(.*?)</th>', re.DOTALL | re.IGNORECASE)
RE_TBODY = re.compile(r'<tbody>(.*?)</tbody>', re.DOTALL | re.IGNORECASE)
RE_TR = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
RE_CELL = re.compile(r'<t[hd][^>]*>(.*?)</t[hd]>', re.DOTALL | re.IGNORECASE)

ENTITIES = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' ', '&quot;': '"'}


def _strip(html: str) -> str:
    text = RE_TAG.sub('', html)
    for ent, char in ENTITIES.items():
        text = text.replace(ent, char)
    text = RE_ENTITY.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip()


class ResultadoScraper:
    """Coleta resultados/vencedores dos leilões fechados."""

    def __init__(self, api: APIRequestContext, limit_leiloes: Optional[int] = None):
        self.api = api
        self.limit_leiloes = limit_leiloes

    def coletar_resultados_todos(self, db) -> dict:
        pendentes = db.get_leiloes_fechados_sem_resultado()
        total = len(pendentes)
        log.info(f"[Resultados] Leilões fechados sem resultado: {total:,}")

        if self.limit_leiloes:
            pendentes = pendentes[: self.limit_leiloes]

        processados = 0
        propostas_salvas = 0
        erros = 0

        for idx, (leilao_id, code) in enumerate(pendentes, 1):
            try:
                n = self._processar_leilao(leilao_id, code, db)
                propostas_salvas += n
                processados += 1

                if idx % 10 == 0 or idx == len(pendentes):
                    log.info(
                        f"[Resultados] Progresso: {idx}/{len(pendentes)} | "
                        f"propostas salvas: {propostas_salvas:,}"
                    )
            except Exception as exc:
                erros += 1
                log.warning(f"[Resultados] Erro em leilao_id={leilao_id}: {exc}")

            time.sleep(RATE_LIMIT_S)

        db.commit()
        return {"processados": processados, "propostas_salvas": propostas_salvas, "erros": erros}

    def _processar_leilao(self, leilao_id: int, code: str, db) -> int:
        resp = self.api.get(f"{ENDPOINT_RESULTADO}/{code}", timeout=15000)
        if not resp.ok:
            return 0

        html = resp.text()
        propostas = self._parsear_resultado(html)

        for p in propostas:
            db.upsert_leilao_resultado(leilao_id, p)

        if propostas:
            db.commit()

        log.debug(f"[Resultados] leilao_id={leilao_id} | propostas={len(propostas)}")
        return len(propostas)

    @staticmethod
    def _parsear_resultado(html: str) -> list:
        """
        Extrai todas as propostas do HTML de resultado.
        Retorna lista de dicts com item_nome, posicao, fornecedor,
        data_proposta, valor_unitario, valor_total.
        """
        # Remove scripts e styles antes de parsear
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        propostas = []

        for table_m in RE_TABLES.finditer(html):
            table_html = table_m.group(1)

            # Nome do item está no primeiro <th> do <thead>
            thead_m = RE_THEAD_TH.search(table_html)
            if not thead_m:
                continue
            item_nome = _strip(thead_m.group(1))
            if not item_nome or item_nome.lower() in ('valor unitário', 'valor total', ''):
                continue

            # Propostas nas linhas do <tbody>
            tbody_m = RE_TBODY.search(table_html)
            if not tbody_m:
                continue

            posicao = 0
            for tr_m in RE_TR.finditer(tbody_m.group(1)):
                cells = [_strip(c.group(1)) for c in RE_CELL.finditer(tr_m.group(1))]
                if len(cells) < 4:
                    continue
                posicao += 1
                propostas.append({
                    "item_nome":     item_nome,
                    "posicao":       posicao,
                    "fornecedor":    cells[0],
                    "data_proposta": cells[1],
                    "valor_unitario": cells[2],
                    "valor_total":   cells[3],
                })

        return propostas
