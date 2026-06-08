"""
scraper/explorer.py
===================
Exploração profunda do dashboard da CapturaME.

Após o login, navega pelos menus internos, clica em seções de leilões
e interage com listagens para forçar chamadas de API que não aparecem
em navegação simples por URL.
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from config.config import BASE_URL, TIMEOUT
from scraper.logger import get_logger

log = get_logger(__name__)

# Palavras-chave para identificar links relevantes de leilões
AUCTION_KEYWORDS = [
    "leilao", "leilão", "leiloes", "leilões",
    "pregao", "pregão", "compras", "aquisicao",
    "aquisição", "catalogo", "catálogo", "oferta",
]

# Seletores de paginação comuns
PAGINATION_SELECTORS = [
    "a[aria-label*='próxima']",
    "a[aria-label*='next']",
    "button[aria-label*='próxima']",
    "button[aria-label*='next']",
    "[class*='pagination'] a",
    "[class*='paginacao'] a",
    "a:has-text('Próxima')",
    "a:has-text('>')",
    "button:has-text('Próxima')",
    "li.page-item:not(.disabled) a.page-link[rel='next']",
]


class DashboardExplorer:
    """
    Navega pelo dashboard após login para descobrir APIs internas.

    Estratégia:
      1. Extrai todos os links de navegação da página atual
      2. Filtra links relacionados a leilões/compras
      3. Visita cada seção e aguarda atividade de rede
      4. Tenta paginação em listagens
      5. Abre o primeiro item de cada listagem para capturar APIs de detalhe
    """

    def __init__(self, page: Page):
        self.page = page
        self._visited: set[str] = set()

    def explore(self) -> list[str]:
        """
        Executa a exploração completa. Retorna lista de URLs visitadas.
        """
        log.info("[Explorer] Iniciando exploração profunda do dashboard.")

        # Registra URL inicial
        self._visited.add(self.page.url)

        # Passo 1: extrai links do dashboard atual
        nav_links = self._extract_all_links()
        log.info(f"[Explorer] {len(nav_links)} links encontrados no dashboard.")

        # Passo 2: visita seções de leilões
        auction_links = self._filter_auction_links(nav_links)
        log.info(f"[Explorer] {len(auction_links)} links relacionados a leilões/compras.")

        if not auction_links:
            log.warning("[Explorer] Nenhum link de leilão encontrado – explorando todos os links internos.")
            auction_links = [l for l in nav_links if l.startswith(BASE_URL)][:10]

        for link in auction_links:
            if link in self._visited:
                continue
            self._visit_and_interact(link)

        # Passo 3: tenta navegar em URLs conhecidas do padrão CapturaME
        self._probe_known_patterns()

        log.info(f"[Explorer] Exploração concluída. Total de URLs visitadas: {len(self._visited)}")
        return list(self._visited)

    # ---------------------------------------------------------------- #
    # Extração de links
    # ---------------------------------------------------------------- #

    def _extract_all_links(self) -> list[str]:
        """Extrai todos os hrefs de <a> da página atual."""
        try:
            hrefs = self.page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(h => h && !h.startsWith('javascript') && !h.startsWith('#'))"
            )
            # Mantém apenas links do domínio CapturaME
            internal = [h for h in hrefs if BASE_URL in h]
            unique = list(dict.fromkeys(internal))  # deduplicar preservando ordem
            return unique
        except Exception as exc:
            log.warning(f"[Explorer] Falha ao extrair links: {exc}")
            return []

    def _filter_auction_links(self, links: list[str]) -> list[str]:
        """Retorna links cujas URLs contêm palavras-chave de leilão."""
        result = []
        for link in links:
            link_lower = link.lower()
            if any(kw in link_lower for kw in AUCTION_KEYWORDS):
                result.append(link)
        return result

    # ---------------------------------------------------------------- #
    # Interação com páginas
    # ---------------------------------------------------------------- #

    def _visit_and_interact(self, url: str) -> None:
        """Navega para uma URL, aguarda rede, rola a página e tenta abrir o primeiro item."""
        log.info(f"[Explorer] Visitando: {url}")
        try:
            response = self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
            if response and response.status >= 400:
                log.debug(f"[Explorer] {url} → status {response.status}, pulando.")
                return

            self._wait_for_network()
            self._visited.add(self.page.url)

            # Rola para disparar lazy-loading
            self._scroll_page()
            self._wait_for_network(timeout=5000)

            # Tenta paginação
            self._try_paginate()

            # Abre o primeiro item da listagem
            self._open_first_item()

        except PlaywrightTimeout:
            log.warning(f"[Explorer] Timeout ao visitar {url}")
        except Exception as exc:
            log.warning(f"[Explorer] Erro ao visitar {url}: {exc}")

    def _scroll_page(self) -> None:
        """Rola a página em etapas para ativar lazy-loading."""
        try:
            self.page.evaluate("""
                () => new Promise(resolve => {
                    let pos = 0;
                    const step = () => {
                        pos += 400;
                        window.scrollTo(0, pos);
                        if (pos < document.body.scrollHeight) {
                            setTimeout(step, 300);
                        } else {
                            resolve();
                        }
                    };
                    step();
                })
            """)
            self.page.wait_for_timeout(500)
        except Exception:
            pass

    def _try_paginate(self) -> None:
        """Clica no botão de próxima página se existir, aguarda rede."""
        for selector in PAGINATION_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    log.info(f"[Explorer] Paginação encontrada: {selector}")
                    btn.click()
                    self._wait_for_network()
                    self._visited.add(self.page.url)
                    # Volta para a página 1 antes de continuar
                    self.page.go_back(timeout=TIMEOUT)
                    self._wait_for_network(timeout=5000)
                    return
            except Exception:
                continue

    def _open_first_item(self) -> None:
        """
        Tenta abrir o primeiro card/linha de listagem para capturar APIs de detalhe.
        Navega de volta após a captura.
        """
        item_selectors = [
            "[class*='card'] a",
            "[class*='item'] a",
            "[class*='leilao'] a",
            "[class*='leilão'] a",
            "table tbody tr:first-child a",
            "[class*='list'] li:first-child a",
            "[class*='result'] a:first-of-type",
        ]
        for selector in item_selectors:
            try:
                el = self.page.locator(selector).first
                if el.is_visible(timeout=1500):
                    href = el.get_attribute("href") or ""
                    if href and BASE_URL in href and href not in self._visited:
                        log.info(f"[Explorer] Abrindo primeiro item: {href}")
                        el.click()
                        self._wait_for_network()
                        self._visited.add(self.page.url)
                        self._scroll_page()
                        self._wait_for_network(timeout=4000)
                        self.page.go_back(timeout=TIMEOUT)
                        self._wait_for_network(timeout=5000)
                        return
            except Exception:
                continue

    # ---------------------------------------------------------------- #
    # Probing de padrões conhecidos
    # ---------------------------------------------------------------- #

    def _probe_known_patterns(self) -> None:
        """
        Testa URLs com padrões típicos de plataformas de leilão
        que podem não aparecer nos links de navegação.
        """
        candidates = [
            f"{BASE_URL}/dashboard/provider",
            f"{BASE_URL}/dashboard/leiloes",
            f"{BASE_URL}/dashboard/leilao",
            f"{BASE_URL}/dashboard/compras",
            f"{BASE_URL}/leiloes",
            f"{BASE_URL}/leiloes/ativos",
            f"{BASE_URL}/leiloes/encerrados",
            f"{BASE_URL}/leilao/lista",
            f"{BASE_URL}/compras/lista",
            f"{BASE_URL}/api/leiloes",
            f"{BASE_URL}/api/v1/leiloes",
            f"{BASE_URL}/api/leilao",
            f"{BASE_URL}/api/items",
            f"{BASE_URL}/api/produtos",
        ]

        log.info("[Explorer] Sondando padrões de URL conhecidos...")
        for url in candidates:
            if url in self._visited:
                continue
            try:
                response = self.page.goto(url, timeout=10000, wait_until="domcontentloaded")
                if response and response.status < 400:
                    self._wait_for_network(timeout=5000)
                    self._visited.add(self.page.url)
                    log.info(f"[Explorer] Acessível: {self.page.url}")
                    self._scroll_page()
                    self._wait_for_network(timeout=3000)
                else:
                    log.debug(f"[Explorer] {url} → {response.status if response else 'N/A'}")
            except PlaywrightTimeout:
                log.debug(f"[Explorer] Timeout: {url}")
            except Exception as exc:
                log.debug(f"[Explorer] Erro: {url} – {exc}")

    # ---------------------------------------------------------------- #
    # Utilitário
    # ---------------------------------------------------------------- #

    def _wait_for_network(self, timeout: int = 8000) -> None:
        """Aguarda a rede estabilizar (networkidle)."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except PlaywrightTimeout:
            pass
