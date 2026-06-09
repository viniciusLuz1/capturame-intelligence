"""
main.py
=======
CapturaME Intelligence – Fase 1 + Fase 2
=========================================
Ponto de entrada principal do sistema.

Fase 1: Login, descoberta de APIs e mapeamento da plataforma.
Fase 2: Coleta paginada de leilões e cotações via API (sem navegador).

Uso:
    python main.py           # Fase 1 + Fase 2
    python main.py --fase1   # Apenas Fase 1 (descoberta)
    python main.py --fase2   # Apenas Fase 2 (coleta, requer sessão salva)
"""

import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

from config.config import (
    BASE_URL,
    HEADLESS,
    TIMEOUT,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    USER_AGENT,
    STORAGE_STATE_PATH,
    TRACES_DIR,
    SCREENSHOTS_DIR,
    TRACE_SCREENSHOTS,
    TRACE_SNAPSHOTS,
    TRACE_SOURCES,
    CAPTURAME_USER,
    CAPTURAME_PASSWORD,
)
from scraper.logger import get_logger
from scraper.login import Authenticator, AuthenticationError
from scraper.network_monitor import NetworkMonitor
from scraper.analytics import AnalyticsEngine, DiscoveryData
from scraper.explorer import DashboardExplorer
from scraper.database import DatabaseManager
from scraper.leiloes import LeilaoScraper
from scraper.cotacoes import CotacaoScraper
from scraper.itens import ItenScraper
from scraper.resultados import ResultadoScraper

log = get_logger("main")


# ------------------------------------------------------------------ #
# Constantes internas
# ------------------------------------------------------------------ #

DISCOVERY_PAGES = [
    # Páginas a navegar após o login para mapear a estrutura
    BASE_URL,
    f"{BASE_URL}/leiloes",
    f"{BASE_URL}/leilao",
    f"{BASE_URL}/compras",
    f"{BASE_URL}/busca",
    f"{BASE_URL}/search",
    f"{BASE_URL}/itens",
    f"{BASE_URL}/dashboard",
]


# ------------------------------------------------------------------ #
# Funções auxiliares
# ------------------------------------------------------------------ #

def take_screenshot(page: Page, name: str) -> None:
    """Salva screenshot nomeado com timestamp."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOTS_DIR / f"{ts}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log.info(f"[Screenshot] {path.name}")
    except Exception as exc:
        log.warning(f"[Screenshot] Falha ao salvar '{name}': {exc}")


def navigate_safely(page: Page, url: str, discovery: DiscoveryData) -> bool:
    """
    Navega para uma URL e registra no DiscoveryData.
    Retorna True em sucesso, False em falha (não interrompe o fluxo).
    """
    try:
        log.info(f"[Nav] Navegando para: {url}")
        response = page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15000)

        # Registra somente se a página foi acessível (não 404 nem redirecionou para login)
        current_url = page.url
        if response and response.status < 400:
            discovery.visited_urls.append(current_url)
            try:
                title = page.title()
                discovery.page_titles[current_url] = title
            except Exception:
                pass
            return True
        else:
            log.debug(f"[Nav] {url} retornou status {response.status if response else 'N/A'} – ignorado.")
            return False

    except PlaywrightTimeout:
        log.warning(f"[Nav] Timeout ao acessar {url}")
        return False
    except Exception as exc:
        log.warning(f"[Nav] Erro ao acessar {url}: {exc}")
        return False


def validate_environment() -> bool:
    """
    Verifica pré-requisitos antes de iniciar.
    Retorna False e loga erros se algo estiver errado.
    """
    ok = True

    if not CAPTURAME_USER:
        log.error("❌ Variável CAPTURAME_USER não configurada no .env")
        ok = False

    if not CAPTURAME_PASSWORD:
        log.error("❌ Variável CAPTURAME_PASSWORD não configurada no .env")
        ok = False

    return ok


# ------------------------------------------------------------------ #
# Fluxo principal
# ------------------------------------------------------------------ #

def run(fase1_only: bool = False) -> int:
    """
    Executa o fluxo completo da Fase 1 (+ Fase 2 se fase1_only=False).
    Retorna 0 em sucesso, 1 em falha.
    """
    log.info("=" * 60)
    log.info("  CapturaME Intelligence – Fase 1")
    log.info(f"  Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # Valida ambiente
    if not validate_environment():
        log.error("Abortando: configure o arquivo .env antes de executar.")
        return 1

    discovery = DiscoveryData()
    trace_path = TRACES_DIR / f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        # Carrega storage_state se existir (sessão salva)
        context_options: dict = {
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            "user_agent": USER_AGENT,
            "ignore_https_errors": True,
        }

        if STORAGE_STATE_PATH.exists():
            context_options["storage_state"] = str(STORAGE_STATE_PATH)
            discovery.session_reused = True
            log.info("[Main] Storage state existente – será validado.")

        context: BrowserContext = browser.new_context(**context_options)

        # Ativa tracing
        context.tracing.start(
            screenshots=TRACE_SCREENSHOTS,
            snapshots=TRACE_SNAPSHOTS,
            sources=TRACE_SOURCES,
        )
        log.info("[Trace] Tracing Playwright ativado.")

        page: Page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        # Ativa monitoramento de rede
        monitor = NetworkMonitor(page, session_name="fase1_discovery")
        monitor.attach()

        try:
            # -------------------------------------------------------- #
            # Etapa 1 – Autenticação
            # -------------------------------------------------------- #
            log.info("[Main] Etapa 1: Autenticação")
            authenticator = Authenticator(context)
            authenticator.ensure_authenticated(page)
            discovery.login_success = True
            log.info("[Main] ✅ Autenticação concluída.")

            # Screenshot do estado autenticado inicial
            take_screenshot(page, "dashboard_autenticado")
            discovery.visited_urls.append(page.url)
            try:
                discovery.page_titles[page.url] = page.title()
            except Exception:
                pass

            # -------------------------------------------------------- #
            # Etapa 1b – Fase 2: coleta via API (sessão recém-autenticada)
            # -------------------------------------------------------- #
            args_set = set(sys.argv[1:])
            if not fase1_only:
                _run_fase2_with_context(context)
                if "--fase3" in args_set or "--all" in args_set:
                    _run_fase3_with_context(context)

            # -------------------------------------------------------- #
            # Etapa 2 – Mapeamento da estrutura (navegação por URL)
            # -------------------------------------------------------- #
            log.info("[Main] Etapa 2a: Mapeamento por URLs conhecidas")

            page.wait_for_timeout(2000)

            for url in DISCOVERY_PAGES:
                if url == BASE_URL:
                    continue
                navigate_safely(page, url, discovery)
                take_screenshot(page, f"discovery_{url.split('/')[-1] or 'root'}")
                page.wait_for_timeout(1000)

            # -------------------------------------------------------- #
            # Etapa 2b – Exploração profunda do dashboard
            # -------------------------------------------------------- #
            log.info("[Main] Etapa 2b: Exploração profunda do dashboard")

            # Volta para o dashboard antes de explorar
            page.goto(f"{BASE_URL}/dashboard/provider", timeout=TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=10000)

            explorer = DashboardExplorer(page)
            explored_urls = explorer.explore()

            for url in explored_urls:
                if url not in discovery.visited_urls:
                    discovery.visited_urls.append(url)
                    try:
                        title = page.title() if page.url == url else ""
                        if title:
                            discovery.page_titles[url] = title
                    except Exception:
                        pass

            take_screenshot(page, "pos_exploracao")
            log.info(f"[Main] Exploração concluída. URLs visitadas: {len(discovery.visited_urls)}")

        except AuthenticationError as exc:
            msg = f"Falha na autenticação: {exc}"
            log.error(f"[Main] ❌ {msg}")
            discovery.errors.append(msg)
            take_screenshot(page, "erro_autenticacao")

        except Exception as exc:
            msg = f"Erro inesperado: {exc}"
            log.exception(f"[Main] ❌ {msg}")
            discovery.errors.append(msg)
            take_screenshot(page, "erro_inesperado")

        finally:
            # -------------------------------------------------------- #
            # Etapa 3 – Salvar evidências e encerrar
            # -------------------------------------------------------- #
            log.info("[Main] Etapa 3: Salvando evidências")

            # Salva chamadas de rede
            network_file = monitor.save()
            log.info(f"[Main] Rede salva: {network_file}")

            # Transfere entradas do monitor para o DiscoveryData
            discovery.network_entries = monitor.get_all_entries()

            # Para tracing e salva
            try:
                context.tracing.stop(path=str(trace_path))
                log.info(f"[Trace] Salvo em: {trace_path}")
            except Exception as exc:
                log.warning(f"[Trace] Falha ao salvar trace: {exc}")

            # Gera relatório
            analytics = AnalyticsEngine(discovery)
            report_path = analytics.generate_report()
            log.info(f"[Main] Relatório gerado: {report_path}")

            # Encerra contexto e navegador
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    # Resumo final
    api_count = sum(1 for e in discovery.network_entries if e.is_api_candidate)
    log.info("=" * 60)
    log.info("  EXECUÇÃO CONCLUÍDA")
    log.info(f"  Login: {'✅' if discovery.login_success else '❌'}")
    log.info(f"  URLs visitadas: {len(discovery.visited_urls)}")
    log.info(f"  Candidatos a API: {api_count}")
    log.info(f"  Relatório: reports/discovery_report.md")
    log.info("=" * 60)

    return 0 if discovery.login_success else 1


# ------------------------------------------------------------------ #
# Fase 2 – Coleta de leilões e cotações (dentro da sessão do browser)
# ------------------------------------------------------------------ #

def _run_fase2_with_context(context: "BrowserContext") -> None:
    """
    Executa a Fase 2 usando o BrowserContext já autenticado da Fase 1.
    O context.request herda todos os cookies da sessão ativa.
    """
    log.info("=" * 60)
    log.info("  CapturaME Intelligence – Fase 2")
    log.info(f"  Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    db = DatabaseManager()
    stats = {}

    try:
        api = context.request

        log.info("[Fase2] Coletando leilões...")
        LeilaoScraper(api).coletar_todos(db=db)

        log.info("[Fase2] Coletando cotações...")
        CotacaoScraper(api).coletar_todas(db=db)

    except Exception as exc:
        log.exception(f"[Fase2] ❌ Erro: {exc}")
    finally:
        stats = db.get_stats()
        db.close()

    log.info("=" * 60)
    log.info("  FASE 2 CONCLUÍDA")
    log.info(f"  Leilões no banco:  {stats.get('leiloes', 0):,}")
    log.info(f"  Cotações no banco: {stats.get('cotacoes', 0):,}")
    log.info(f"  Banco de dados:    data/capturame.db")
    log.info("=" * 60)


# ------------------------------------------------------------------ #
# Fase 3 – Itens de leilões (dentro da sessão do browser)
# ------------------------------------------------------------------ #

def _run_fase3_with_context(context: "BrowserContext", limit: int = None) -> None:
    """
    Executa a Fase 3: coleta itens e local de entrega de cada leilão.
    Usa o BrowserContext já autenticado (context.request).
    """
    log.info("=" * 60)
    log.info("  CapturaME Intelligence – Fase 3")
    log.info(f"  Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    db = DatabaseManager()
    stats = {}

    try:
        api = context.request
        scraper = ItenScraper(api, limit_leiloes=limit)
        stats = scraper.coletar_itens_todos(db=db)

    except Exception as exc:
        log.exception(f"[Fase3] ❌ Erro: {exc}")
    finally:
        db_stats = db.get_stats()
        db.close()

    log.info("=" * 60)
    log.info("  FASE 3 CONCLUÍDA")
    log.info(f"  Leilões processados: {stats.get('processados', 0):,}")
    log.info(f"  Itens salvos:        {stats.get('itens_salvos', 0):,}")
    log.info(f"  Erros:               {stats.get('erros', 0):,}")
    log.info(f"  Total itens no banco:{db_stats.get('leilao_itens', 0):,}")
    log.info("=" * 60)


# ------------------------------------------------------------------ #
# Fase 4 – Resultados / Vencedores (dentro da sessão do browser)
# ------------------------------------------------------------------ #

def _run_fase4_with_context(context: "BrowserContext", limit: int = None) -> None:
    """
    Executa a Fase 4: coleta resultados (vencedores e todas as propostas) dos leilões fechados.
    """
    log.info("=" * 60)
    log.info("  CapturaME Intelligence – Fase 4 (Resultados)")
    log.info(f"  Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    db = DatabaseManager()
    stats = {}

    try:
        api = context.request
        scraper = ResultadoScraper(api, limit_leiloes=limit)
        stats = scraper.coletar_resultados_todos(db=db)

    except Exception as exc:
        log.exception(f"[Fase4] ❌ Erro: {exc}")
    finally:
        db_stats = db.get_stats()
        db.close()

    log.info("=" * 60)
    log.info("  FASE 4 CONCLUÍDA")
    log.info(f"  Leilões processados:  {stats.get('processados', 0):,}")
    log.info(f"  Propostas salvas:     {stats.get('propostas_salvas', 0):,}")
    log.info(f"  Erros:                {stats.get('erros', 0):,}")
    log.info(f"  Total no banco:       {db_stats.get('leilao_resultados', 0):,}")
    log.info("=" * 60)


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def run_coleta() -> int:
    """
    Modo --coleta: login + Fase 2 (atualiza listas) sem exploração.
    Ideal para GitHub Actions e execuções automáticas.
    """
    log.info("=" * 60)
    log.info("  CapturaME Intelligence – Modo Coleta")
    log.info(f"  Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    if not validate_environment():
        return 1

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context_options = {
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            "user_agent": USER_AGENT,
            "ignore_https_errors": True,
        }
        if STORAGE_STATE_PATH.exists():
            context_options["storage_state"] = str(STORAGE_STATE_PATH)

        context: BrowserContext = browser.new_context(**context_options)
        page: Page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        try:
            auth = Authenticator(context)
            auth.ensure_authenticated(page)
            log.info("[Coleta] Autenticado. Iniciando Fase 2...")
            _run_fase2_with_context(context)
        except Exception as exc:
            log.exception(f"[Coleta] Erro: {exc}")
            return 1
        finally:
            context.close()
            browser.close()

    return 0


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    args = set(sys.argv[1:])

    if "--fase1" in args:
        sys.exit(run(fase1_only=True))
    elif "--coleta" in args:
        sys.exit(run_coleta())
    elif "--fase3" in args or "--fase4" in args:
        # Fase 3 e/ou Fase 4 standalone (requer sessão salva)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context_options = {
                "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                "user_agent": USER_AGENT,
                "ignore_https_errors": True,
            }
            if STORAGE_STATE_PATH.exists():
                context_options["storage_state"] = str(STORAGE_STATE_PATH)
            context = browser.new_context(**context_options)
            page = context.new_page()
            auth = Authenticator(context)
            auth.ensure_authenticated(page)
            limit_str = next((a.split("=")[1] for a in args if a.startswith("--limit=")), None)
            limit = int(limit_str) if limit_str else None
            if "--fase3" in args:
                _run_fase3_with_context(context, limit=limit)
            if "--fase4" in args:
                _run_fase4_with_context(context, limit=limit)
            context.close()
            browser.close()
    else:
        sys.exit(run(fase1_only=False))
