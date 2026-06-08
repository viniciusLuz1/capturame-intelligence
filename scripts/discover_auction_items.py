"""
scripts/discover_auction_items.py
==================================
Script de descoberta: abre a página de detalhe de um leilão e captura
todos os endpoints de rede chamados.

Objetivo: descobrir qual API retorna os itens (produtos) de um leilão
e se há informação de cidade de entrega.

Uso:
    python scripts/discover_auction_items.py [auction_code]

Se auction_code não for informado, usa o primeiro leilão 'open' do banco.
"""

import json
import sys
import time
from pathlib import Path

# Garante que o raiz do projeto está no path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

from config.config import BASE_URL, TIMEOUT, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, USER_AGENT, STORAGE_STATE_PATH
from scraper.logger import get_logger
from scraper.login import Authenticator
from scraper.database import DatabaseManager, DB_PATH

log = get_logger("discover_auction_items")


def get_test_auction() -> tuple:
    """Retorna (id_externo, code) de um leilão aberto do banco."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT id_externo, code FROM leiloes WHERE status='open' ORDER BY id_externo DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        row = conn.execute(
            "SELECT id_externo, code FROM leiloes ORDER BY id_externo DESC LIMIT 1"
        ).fetchone()
    return row


def main():
    if len(sys.argv) > 1:
        auction_code = sys.argv[1]
        auction_id = None
    else:
        result = get_test_auction()
        if not result:
            log.error("Nenhum leilão encontrado no banco.")
            sys.exit(1)
        auction_id, auction_code = result

    log.info(f"Descoberta de itens para leilão: id={auction_id}, code={auction_code}")

    if not STORAGE_STATE_PATH.exists():
        log.error(f"storage_state.json não encontrado em {STORAGE_STATE_PATH}.")
        log.error("Execute 'python main.py --fase1' primeiro para fazer login.")
        sys.exit(1)

    captured_calls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            user_agent=USER_AGENT,
            ignore_https_errors=True,
            storage_state=str(STORAGE_STATE_PATH),
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        # Garante autenticação
        auth = Authenticator(context)
        auth.ensure_authenticated(page)
        log.info("Autenticado com sucesso.")

        # Captura todas as requisições XHR/fetch
        def on_request(request):
            url = request.url
            if "capturame.com.br" in url and not any(skip in url for skip in [
                "tawk.to", "analytics", "sentry", "amplitude", ".css", ".js", ".png", ".ico", ".woff"
            ]):
                captured_calls.append({
                    "method": request.method,
                    "url": url,
                    "type": request.resource_type,
                })
                log.info(f"  → {request.method} {url[:120]}")

        page.on("request", on_request)

        # 1. Navega para a lista de leilões
        log.info(f"\n{'='*60}\n1. Navegando para lista de leilões...\n{'='*60}")
        page.goto(f"{BASE_URL}/dashboard/provider/acutions", timeout=TIMEOUT, wait_until="domcontentloaded")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        time.sleep(2)

        # 2. Tenta clicar em um leilão específico pela lista
        log.info(f"\n{'='*60}\n2. Procurando leilão {auction_code} na lista...\n{'='*60}")

        # Tenta encontrar e clicar no leilão pelo código
        clicked = False
        for selector in [
            f"td:has-text('{auction_code}')",
            f"tr:has-text('{auction_code}')",
            f"[data-id='{auction_id}']",
            "table tbody tr:first-child td:first-child",
            "table tbody tr:first-child",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    log.info(f"  Clicando com seletor: {selector}")
                    el.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            log.warning("  Não foi possível clicar pelo seletor. Tentando clique duplo na primeira linha...")
            try:
                page.locator("table tbody tr").first.click()
                clicked = True
            except Exception as e:
                log.warning(f"  Falha: {e}")

        if clicked:
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(3)

        # 3. Tenta também a URL direta do documento
        log.info(f"\n{'='*60}\n3. Navegando direto para URL do documento...\n{'='*60}")
        doc_urls = [
            f"{BASE_URL}/dashboard/provider/list/documents/auctionsgest",
            f"{BASE_URL}/dashboard/provider/document/{auction_code}",
            f"{BASE_URL}/dashboard/provider/acution/{auction_code}",
            f"{BASE_URL}/dashboard/provider/auction/{auction_code}",
        ]

        for url in doc_urls:
            log.info(f"  Tentando: {url}")
            try:
                page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(2)

                # Verifica se parece uma página de conteúdo (não 404)
                current = page.url
                if "/login" not in current and "/404" not in current:
                    log.info(f"  Página carregada: {current}")
                    # Tenta clicar no primeiro item da lista, se houver
                    try:
                        page.locator("table tbody tr").first.click(timeout=3000)
                        page.wait_for_load_state("networkidle", timeout=10000)
                        time.sleep(3)
                    except Exception:
                        pass
                    break
            except Exception as e:
                log.debug(f"  Erro em {url}: {e}")

        # 4. Tenta chamada direta com padrões de nomes conhecidos
        log.info(f"\n{'='*60}\n4. Testando endpoints de itens conhecidos...\n{'='*60}")
        api = context.request

        candidate_endpoints = [
            f"/dashboard/provider/GetAuctionListProductsV1?auctionid={auction_id}",
            f"/dashboard/provider/GetAuctionListProductsV2?auctionid={auction_id}",
            f"/dashboard/provider/GetAuctionListProductsV3?auctionid={auction_id}",
            f"/dashboard/provider/getauctionsitemsGets?auctionid={auction_id}",
            f"/dashboard/provider/getauctionitemsGets?auctionid={auction_id}",
            f"/dashboard/provider/getauctionproductsGets?auctionid={auction_id}",
            f"/dashboard/provider/GetAuctionProductsV1?auctionid={auction_id}",
            f"/dashboard/provider/GetAuctionProductsV3?auctionid={auction_id}",
            f"/get_obs?code={auction_code}",
            f"/dashboard/provider/document/items?code={auction_code}",
            f"/dashboard/provider/acution/items?code={auction_code}",
            f"/dashboard/provider/acution/products?auctionid={auction_id}",
        ]

        for path in candidate_endpoints:
            url = f"{BASE_URL}{path}"
            try:
                resp = api.get(url, timeout=8000)
                status = resp.status
                if status < 400:
                    body = resp.text()
                    log.info(f"  ✅ HTTP {status}: {url}")
                    log.info(f"     Resposta ({len(body)} bytes): {body[:300]}")
                else:
                    log.debug(f"  ✗ HTTP {status}: {path}")
            except Exception as e:
                log.debug(f"  ✗ Erro em {path}: {e}")

        browser.close()

    # 5. Relatório final
    log.info(f"\n{'='*60}\nRELATÓRIO DE CHAMADAS CAPTURADAS ({len(captured_calls)} total)\n{'='*60}")

    api_calls = [c for c in captured_calls if c["type"] in ("xhr", "fetch", "other")]
    log.info(f"\nChamadas XHR/Fetch ({len(api_calls)}):")
    for c in api_calls:
        log.info(f"  {c['method']} {c['url'][:140]}")

    # Salva resultado
    out_path = Path("data/discovery_auction_items.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "auction_id": auction_id,
            "auction_code": auction_code,
            "captured_calls": captured_calls,
        }, f, ensure_ascii=False, indent=2)

    log.info(f"\nResultado salvo em: {out_path}")


if __name__ == "__main__":
    main()
