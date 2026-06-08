"""
scraper/network_monitor.py
==========================
Monitora e persiste chamadas XHR/Fetch realizadas pelo navegador.

Objetivo:
  Descobrir APIs internas da CapturaME que permitam coletas diretas
  sem navegação visual nas fases seguintes.

Uso:
    monitor = NetworkMonitor(page)
    monitor.attach()
    # ... navegar ...
    monitor.save()
    endpoints = monitor.get_api_candidates()
"""

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, Request, Response

from config.config import NETWORK_DIR, IGNORED_URL_PATTERNS, MONITORED_RESOURCE_TYPES
from scraper.logger import get_logger

log = get_logger(__name__)


@dataclass
class NetworkEntry:
    """Representa uma chamada de rede capturada."""
    timestamp: str
    url: str
    method: str
    resource_type: str
    request_headers: dict
    request_post_data: Optional[str]
    response_status: Optional[int]
    response_headers: dict
    response_body: Optional[str]
    is_json_response: bool = False
    is_api_candidate: bool = False


class NetworkMonitor:
    """
    Intercepta requisições XHR e Fetch durante a navegação Playwright.

    Parâmetros
    ----------
    page : Page
        Instância da página Playwright já aberta.
    session_name : str
        Prefixo para nomear os arquivos de saída.
    """

    def __init__(self, page: Page, session_name: str = "session"):
        self.page = page
        self.session_name = session_name
        self._entries: list[NetworkEntry] = []
        self._response_map: dict[str, Response] = {}

    # ---------------------------------------------------------------- #
    # API pública
    # ---------------------------------------------------------------- #

    def attach(self) -> None:
        """Registra os handlers de request e response na página."""
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        log.info("[NetworkMonitor] Monitoramento de rede ativado.")

    def save(self) -> Path:
        """Persiste todas as entradas capturadas em JSON."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = NETWORK_DIR / f"{self.session_name}_{ts}.json"

        payload = {
            "session": self.session_name,
            "captured_at": ts,
            "total_requests": len(self._entries),
            "api_candidates": sum(1 for e in self._entries if e.is_api_candidate),
            "entries": [asdict(e) for e in self._entries],
        }

        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"[NetworkMonitor] {len(self._entries)} requisições salvas → {out_path}")
        return out_path

    def get_api_candidates(self) -> list[NetworkEntry]:
        """Retorna entradas classificadas como possíveis APIs internas."""
        return [e for e in self._entries if e.is_api_candidate]

    def get_all_entries(self) -> list[NetworkEntry]:
        return list(self._entries)

    # ---------------------------------------------------------------- #
    # Handlers internos
    # ---------------------------------------------------------------- #

    def _on_request(self, request: Request) -> None:
        if not self._should_capture(request):
            return

        headers = self._sanitize_headers(dict(request.headers))
        post_data: Optional[str] = None
        try:
            post_data = request.post_data
        except Exception:
            pass

        entry = NetworkEntry(
            timestamp=datetime.now().isoformat(),
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            request_headers=headers,
            request_post_data=post_data,
            response_status=None,
            response_headers={},
            response_body=None,
        )
        self._entries.append(entry)

    def _on_response(self, response: Response) -> None:
        request = response.request
        if not self._should_capture(request):
            return

        # Localiza a entrada correspondente (última com mesma URL+método)
        entry = self._find_pending_entry(request.url, request.method)
        if entry is None:
            return

        entry.response_status = response.status
        entry.response_headers = dict(response.headers)

        content_type = response.headers.get("content-type", "")
        if "json" in content_type or "javascript" in content_type:
            entry.is_json_response = True
            try:
                body = response.body()
                entry.response_body = body.decode("utf-8", errors="replace")[:4096]  # limita tamanho
            except Exception:
                pass

        entry.is_api_candidate = self._classify_as_api(entry)

        if entry.is_api_candidate:
            log.debug(f"[NetworkMonitor] API candidata: {entry.method} {entry.url}")

    # ---------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------- #

    def _should_capture(self, request: Request) -> bool:
        """Filtra requisições irrelevantes (imagens, fontes, trackers)."""
        if request.resource_type not in MONITORED_RESOURCE_TYPES:
            return False
        url_lower = request.url.lower()
        for pattern in IGNORED_URL_PATTERNS:
            if pattern in url_lower:
                return False
        return True

    def _find_pending_entry(self, url: str, method: str) -> Optional[NetworkEntry]:
        """Retorna a entrada mais recente sem response para aquela URL+método."""
        for entry in reversed(self._entries):
            if entry.url == url and entry.method == method and entry.response_status is None:
                return entry
        return None

    @staticmethod
    def _sanitize_headers(headers: dict) -> dict:
        """Remove valores sensíveis (Authorization, Cookie) dos headers logados."""
        sensitive = {"authorization", "cookie", "set-cookie", "x-auth-token"}
        return {
            k: ("[REDACTED]" if k.lower() in sensitive else v)
            for k, v in headers.items()
        }

    @staticmethod
    def _classify_as_api(entry: NetworkEntry) -> bool:
        """
        Classifica a requisição como candidata a API interna.

        Critérios:
        - Resposta JSON
        - URL contém padrões típicos de API (/api/, /v1/, /v2/, /graphql, etc.)
        - Método não é GET de recurso estático
        """
        if entry.is_json_response:
            return True

        api_patterns = [
            r"/api/", r"/v\d+/", r"/graphql", r"/rest/",
            r"\.json", r"/services/", r"/endpoint",
            r"/leiloes?", r"/leilao", r"/itens?", r"/produtos?",
            r"/search", r"/busca", r"/auth", r"/token",
        ]
        url_lower = entry.url.lower()
        for pattern in api_patterns:
            if re.search(pattern, url_lower):
                return True

        return False
