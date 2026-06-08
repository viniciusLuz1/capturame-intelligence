"""
scraper/analytics.py
====================
Gera o relatório de descoberta (discovery_report.md) ao final da execução.

O relatório consolida:
  - URLs visitadas
  - Chamadas XHR e Fetch capturadas
  - Endpoints JSON identificados
  - Candidatos a APIs internas
  - Recomendações para fases futuras
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from config.config import REPORTS_DIR
from scraper.logger import get_logger
from scraper.network_monitor import NetworkEntry

log = get_logger(__name__)


@dataclass
class DiscoveryData:
    """Dados coletados durante a sessão de exploração."""
    visited_urls: list[str] = field(default_factory=list)
    network_entries: list[NetworkEntry] = field(default_factory=list)
    page_titles: dict[str, str] = field(default_factory=dict)   # url -> título
    execution_start: str = field(default_factory=lambda: datetime.now().isoformat())
    execution_end: Optional[str] = None
    login_success: bool = False
    session_reused: bool = False
    errors: list[str] = field(default_factory=list)


class AnalyticsEngine:
    """
    Motor de análise e geração de relatório de descoberta.

    Parâmetros
    ----------
    data : DiscoveryData
        Objeto preenchido durante a execução do scraper.
    """

    def __init__(self, data: DiscoveryData):
        self.data = data

    def generate_report(self) -> Path:
        """Gera e salva o relatório Markdown. Retorna o caminho do arquivo."""
        self.data.execution_end = datetime.now().isoformat()
        report_path = REPORTS_DIR / "discovery_report.md"
        content = self._build_markdown()
        report_path.write_text(content, encoding="utf-8")
        log.info(f"[Analytics] Relatório salvo em {report_path}")
        return report_path

    # ---------------------------------------------------------------- #
    # Construção do Markdown
    # ---------------------------------------------------------------- #

    def _build_markdown(self) -> str:
        sections = [
            self._section_header(),
            self._section_execution_summary(),
            self._section_visited_urls(),
            self._section_xhr_calls(),
            self._section_fetch_calls(),
            self._section_json_endpoints(),
            self._section_api_candidates(),
            self._section_auction_endpoints(),
            self._section_item_endpoints(),
            self._section_product_endpoints(),
            self._section_errors(),
            self._section_recommendations(),
        ]
        return "\n\n".join(sections)

    def _section_header(self) -> str:
        ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return (
            "# CapturaME Intelligence – Relatório de Descoberta\n\n"
            f"> **Gerado em:** {ts}  \n"
            f"> **Fase:** 1 – Login, Descoberta e Preparação  \n"
        )

    def _section_execution_summary(self) -> str:
        total = len(self.data.network_entries)
        xhr   = sum(1 for e in self.data.network_entries if e.resource_type == "xhr")
        fetch = sum(1 for e in self.data.network_entries if e.resource_type == "fetch")
        apis  = sum(1 for e in self.data.network_entries if e.is_api_candidate)
        json_r = sum(1 for e in self.data.network_entries if e.is_json_response)

        return (
            "## Resumo da Execução\n\n"
            f"| Item | Valor |\n"
            f"|------|-------|\n"
            f"| Início | {self.data.execution_start} |\n"
            f"| Fim | {self.data.execution_end or 'N/A'} |\n"
            f"| Login bem-sucedido | {'✅ Sim' if self.data.login_success else '❌ Não'} |\n"
            f"| Sessão reutilizada | {'✅ Sim' if self.data.session_reused else '🔄 Novo login'} |\n"
            f"| URLs visitadas | {len(self.data.visited_urls)} |\n"
            f"| Total de requisições capturadas | {total} |\n"
            f"| Requisições XHR | {xhr} |\n"
            f"| Requisições Fetch | {fetch} |\n"
            f"| Respostas JSON | {json_r} |\n"
            f"| Candidatos a API interna | {apis} |\n"
        )

    def _section_visited_urls(self) -> str:
        lines = ["## URLs Visitadas\n"]
        if not self.data.visited_urls:
            lines.append("_Nenhuma URL registrada._")
        else:
            for url in self.data.visited_urls:
                title = self.data.page_titles.get(url, "")
                lines.append(f"- `{url}`{f' – *{title}*' if title else ''}")
        return "\n".join(lines)

    def _section_xhr_calls(self) -> str:
        entries = [e for e in self.data.network_entries if e.resource_type == "xhr"]
        return self._format_entry_section("Chamadas XHR Encontradas", entries)

    def _section_fetch_calls(self) -> str:
        entries = [e for e in self.data.network_entries if e.resource_type == "fetch"]
        return self._format_entry_section("Chamadas Fetch Encontradas", entries)

    def _section_json_endpoints(self) -> str:
        entries = [e for e in self.data.network_entries if e.is_json_response]
        return self._format_entry_section("Endpoints JSON Encontrados", entries, show_body=True)

    def _section_api_candidates(self) -> str:
        entries = [e for e in self.data.network_entries if e.is_api_candidate]
        lines = ["## Possíveis APIs Internas\n"]
        if not entries:
            lines.append("_Nenhum candidato identificado nesta sessão._")
        else:
            lines.append(
                "As requisições abaixo foram classificadas como possíveis APIs internas "
                "com base no tipo de resposta (JSON) e/ou padrões na URL.\n"
            )
            for e in self._deduplicate_by_path(entries):
                lines.append(f"### `{e.method} {e.url}`")
                lines.append(f"- **Status:** {e.response_status}")
                lines.append(f"- **Tipo:** {e.resource_type}")
                if e.response_body:
                    snippet = e.response_body[:300].replace("\n", " ")
                    lines.append(f"- **Resposta (snippet):** `{snippet}...`")
                lines.append("")
        return "\n".join(lines)

    def _section_auction_endpoints(self) -> str:
        keywords = ["leilao", "leiloes", "auction", "lote", "lots"]
        entries = self._filter_by_keywords(keywords)
        return self._format_keyword_section("Possíveis Endpoints de Leilões", entries)

    def _section_item_endpoints(self) -> str:
        keywords = ["item", "itens", "items", "produto", "produtos"]
        entries = self._filter_by_keywords(keywords)
        return self._format_keyword_section("Possíveis Endpoints de Itens", entries)

    def _section_product_endpoints(self) -> str:
        keywords = ["detalhe", "detail", "descricao", "description", "ficha"]
        entries = self._filter_by_keywords(keywords)
        return self._format_keyword_section("Possíveis Endpoints de Detalhes de Produtos", entries)

    def _section_errors(self) -> str:
        lines = ["## Erros Registrados\n"]
        if not self.data.errors:
            lines.append("_Nenhum erro registrado._")
        else:
            for err in self.data.errors:
                lines.append(f"- ⚠️ {err}")
        return "\n".join(lines)

    def _section_recommendations(self) -> str:
        apis = [e for e in self.data.network_entries if e.is_api_candidate]
        has_apis = len(apis) > 0

        recs = [
            "## Recomendações para Fases Futuras\n",
        ]

        if has_apis:
            recs.append(
                "### ✅ APIs Internas Detectadas\n"
                "Foram identificadas chamadas que sugerem a existência de APIs internas. "
                "**Recomendação:** Investigar autenticação dessas APIs (token JWT, session cookie, etc.) "
                "para permitir coleta direta sem navegação visual na Fase 2.\n"
            )
        else:
            recs.append(
                "### ⚠️ Sem APIs Internas Detectadas\n"
                "Nenhuma API interna foi identificada nesta sessão. "
                "A coleta de dados na Fase 2 deverá ser feita via navegação visual (DOM scraping).\n"
            )

        recs.append(
            "### Fase 2 – Coleta de Leilões\n"
            "- Mapear a lista de leilões disponíveis\n"
            "- Implementar paginação\n"
            "- Extrair: ID, título, data, status, categoria\n"
            "- Armazenar em banco de dados relacional (SQLite para MVP → PostgreSQL para produção)\n"
        )

        recs.append(
            "### Fase 3 – Captura de Itens\n"
            "- Para cada leilão, capturar todos os itens\n"
            "- Extrair: descrição, quantidade, unidade, fabricante, modelo, NSN\n"
            "- Detectar reprocessos (mesmo item em múltiplos leilões)\n"
        )

        recs.append(
            "### Fase 4 – Inteligência de Mercado\n"
            "- Identificar fabricantes mais solicitados\n"
            "- Analisar tendências por categoria\n"
            "- Detectar padrões sazonais\n"
            "- Gerar alertas automáticos de oportunidades\n"
        )

        recs.append(
            "### Infraestrutura\n"
            "- Implementar scheduler (APScheduler ou cron) para execução diária\n"
            "- Adicionar banco de dados com schema versionado (Alembic)\n"
            "- Configurar alertas de falha por e-mail ou Telegram\n"
            "- Implementar proxy rotation para evitar bloqueios\n"
        )

        return "\n".join(recs)

    # ---------------------------------------------------------------- #
    # Utilitários
    # ---------------------------------------------------------------- #

    @staticmethod
    def _format_entry_section(title: str, entries: list[NetworkEntry], show_body: bool = False) -> str:
        lines = [f"## {title}\n"]
        if not entries:
            lines.append("_Nenhuma entrada registrada._")
            return "\n".join(lines)

        for e in entries:
            lines.append(f"- **`{e.method}`** `{e.url}` → status `{e.response_status}`")
            if show_body and e.response_body:
                snippet = e.response_body[:200].replace("\n", " ")
                lines.append(f"  - Resposta: `{snippet}...`")
        return "\n".join(lines)

    @staticmethod
    def _format_keyword_section(title: str, entries: list[NetworkEntry]) -> str:
        lines = [f"## {title}\n"]
        if not entries:
            lines.append("_Nenhum endpoint identificado por palavras-chave nesta sessão._")
        else:
            for e in entries:
                lines.append(f"- `{e.method} {e.url}` → {e.response_status}")
        return "\n".join(lines)

    def _filter_by_keywords(self, keywords: list[str]) -> list[NetworkEntry]:
        result = []
        for e in self.data.network_entries:
            url_lower = e.url.lower()
            if any(kw in url_lower for kw in keywords):
                result.append(e)
        return result

    @staticmethod
    def _deduplicate_by_path(entries: list[NetworkEntry]) -> list[NetworkEntry]:
        """Remove duplicatas mantendo uma entrada por path único."""
        seen: set[str] = set()
        unique = []
        for e in entries:
            path = urlparse(e.url).path
            key = f"{e.method}:{path}"
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique
