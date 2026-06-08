"""
scraper/login.py
================
Gerencia autenticação na plataforma CapturaME.

Responsabilidades:
  - Verificar existência de sessão salva e válida
  - Executar fluxo de login visual (via Playwright)
  - Persistir storage_state.json após login bem-sucedido
  - Validar que a autenticação foi concluída

Uso:
    authenticator = Authenticator(browser, context)
    success = authenticator.ensure_authenticated(page)
"""

import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

from config.config import (
    BASE_URL,
    LOGIN_URL,
    CAPTURAME_USER,
    CAPTURAME_PASSWORD,
    STORAGE_STATE_PATH,
    TIMEOUT,
    SELECTORS,
    SCREENSHOTS_DIR,
)
from scraper.logger import get_logger

log = get_logger(__name__)


class AuthenticationError(Exception):
    """Levantada quando o login falha ou a sessão não pode ser validada."""


class Authenticator:
    """
    Gerencia o ciclo de vida da autenticação na CapturaME.

    Parâmetros
    ----------
    context : BrowserContext
        Contexto Playwright já criado (com ou sem storage_state).
    """

    def __init__(self, context: BrowserContext):
        self.context = context

    # ---------------------------------------------------------------- #
    # API pública
    # ---------------------------------------------------------------- #

    def ensure_authenticated(self, page: Page) -> bool:
        """
        Garante que a sessão está autenticada.

        Fluxo:
          1. Tenta reutilizar sessão salva.
          2. Se inválida ou inexistente, executa login completo.
          3. Salva nova sessão.

        Retorna True em caso de sucesso, levanta AuthenticationError em falha.
        """
        self._validate_credentials()

        if self._has_saved_session():
            log.info("[Auth] Sessão salva encontrada – tentando reutilizar...")
            if self._validate_session(page):
                log.info("[Auth] Sessão reutilizada com sucesso.")
                return True
            log.warning("[Auth] Sessão expirada ou inválida – realizando novo login.")

        # Login completo
        self._do_login(page)
        self._save_session()
        return True

    # ---------------------------------------------------------------- #
    # Helpers internos
    # ---------------------------------------------------------------- #

    def _validate_credentials(self) -> None:
        """Garante que as credenciais foram configuradas no .env."""
        if not CAPTURAME_USER or not CAPTURAME_PASSWORD:
            raise AuthenticationError(
                "Credenciais não configuradas. "
                "Defina CAPTURAME_USER e CAPTURAME_PASSWORD no arquivo .env"
            )

    def _has_saved_session(self) -> bool:
        """Verifica se existe um arquivo de sessão salvo e não vazio."""
        if not STORAGE_STATE_PATH.exists():
            return False
        try:
            data = json.loads(STORAGE_STATE_PATH.read_text(encoding="utf-8"))
            return bool(data.get("cookies") or data.get("origins"))
        except (json.JSONDecodeError, Exception):
            return False

    def _validate_session(self, page: Page) -> bool:
        """
        Navega até o dashboard e verifica se ainda está logado.
        Retorna True se autenticado, False se redirecionou para login.
        """
        try:
            page.goto(f"{BASE_URL}/dashboard/provider", timeout=TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=TIMEOUT)

            # Se redirecionou para /login, sessão expirou
            if "/login" in page.url.lower() or "/entrar" in page.url.lower():
                return False

            # Verifica presença de indicadores de autenticação
            for selector in SELECTORS["auth_indicators"]:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        return True
                except Exception:
                    continue

            return False
        except PlaywrightTimeout:
            log.warning("[Auth] Timeout ao validar sessão.")
            return False

    def _do_login(self, page: Page) -> None:
        """
        Executa o fluxo completo de login na CapturaME.

        Passos:
          1. Navega para a URL de login
          2. Aguarda o formulário carregar
          3. Preenche e-mail e senha
          4. Submete o formulário
          5. Aguarda redirecionamento
          6. Valida sucesso
        """
        log.info(f"[Auth] Iniciando login em {LOGIN_URL}")
        self._take_screenshot(page, "01_pre_login")

        try:
            page.goto(LOGIN_URL, timeout=TIMEOUT, wait_until="domcontentloaded")
        except PlaywrightTimeout:
            # Tenta a URL base caso /login não exista
            log.warning("[Auth] /login não respondeu, tentando URL base...")
            page.goto(BASE_URL, timeout=TIMEOUT, wait_until="domcontentloaded")

        page.wait_for_load_state("networkidle", timeout=TIMEOUT)
        self._take_screenshot(page, "02_login_page")

        # Localiza campo de e-mail
        email_field = self._find_element(page, SELECTORS["login_email"], "campo e-mail")
        email_field.click()
        email_field.fill(CAPTURAME_USER)
        log.debug("[Auth] E-mail preenchido.")

        # Localiza campo de senha
        password_field = self._find_element(page, SELECTORS["login_password"], "campo senha")
        password_field.click()
        password_field.fill(CAPTURAME_PASSWORD)
        log.debug("[Auth] Senha preenchida.")

        self._take_screenshot(page, "03_form_filled")

        # Submete o formulário
        submit_btn = self._find_element(page, SELECTORS["login_submit"], "botão submit")
        submit_btn.click()
        log.info("[Auth] Formulário submetido.")

        # Aguarda redirect para fora de /login (SPA pode demorar)
        try:
            page.wait_for_url(
                lambda url: "/login" not in url.lower() and "/entrar" not in url.lower(),
                timeout=TIMEOUT,
            )
            log.info(f"[Auth] Redirecionado para: {page.url}")
        except PlaywrightTimeout:
            log.warning("[Auth] Nenhum redirect detectado – verificando estado da página.")

        # Aguarda estabilizar
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            pass

        self._take_screenshot(page, "04_post_login")

        # Verifica erros visíveis (apenas se ainda estiver na página de login)
        if "/login" in page.url.lower():
            self._check_login_errors(page)

        # Confirma autenticação
        if not self._is_authenticated(page):
            raise AuthenticationError(
                "Login aparentemente falhou – nenhum indicador de autenticação encontrado. "
                f"URL atual: {page.url}"
            )

        log.info(f"[Auth] Login realizado com sucesso. URL: {page.url}")
        self._take_screenshot(page, "05_authenticated_dashboard")

    def _is_authenticated(self, page: Page) -> bool:
        """Verifica presença de elementos que indicam sessão autenticada."""
        # Se ainda está em URL de login, definitivamente falhou
        current = page.url.lower()
        if "/login" in current or "/entrar" in current or "/signin" in current:
            return False

        for selector in SELECTORS["auth_indicators"]:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=3000):
                    return True
            except Exception:
                continue
        return True  # Assume autenticado se saiu da página de login

    def _check_login_errors(self, page: Page) -> None:
        """Verifica mensagens de erro no formulário e levanta exceção se encontrar."""
        SUCCESS_KEYWORDS = ("sucesso", "success", "bem-vindo", "welcome", "logged in")
        for selector in SELECTORS["login_error"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    msg = el.inner_text().strip()
                    if any(kw in msg.lower() for kw in SUCCESS_KEYWORDS):
                        log.debug(f"[Auth] Mensagem de sucesso ignorada: '{msg[:60]}'")
                        continue
                    raise AuthenticationError(f"Erro de login detectado: '{msg}'")
            except AuthenticationError:
                raise
            except Exception:
                continue

    def _find_element(self, page: Page, selector: str, label: str):
        """
        Localiza elemento na página com tratamento de erro descritivo.
        Suporta seletores compostos separados por vírgula.
        """
        parts = [s.strip() for s in selector.split(",")]
        for part in parts:
            try:
                el = page.locator(part).first
                if el.is_visible(timeout=5000):
                    log.debug(f"[Auth] Elemento '{label}' encontrado com seletor: {part}")
                    return el
            except Exception:
                continue

        # Último recurso: tenta encontrar visualmente
        raise AuthenticationError(
            f"Elemento '{label}' não encontrado na página. "
            f"Seletores tentados: {selector}"
        )

    def _save_session(self) -> None:
        """Persiste o storage_state atual no arquivo JSON."""
        try:
            self.context.storage_state(path=str(STORAGE_STATE_PATH))
            log.info(f"[Auth] Sessão salva em {STORAGE_STATE_PATH}")
        except Exception as exc:
            log.error(f"[Auth] Falha ao salvar sessão: {exc}")

    @staticmethod
    def _take_screenshot(page: Page, name: str) -> None:
        """Salva screenshot com timestamp."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"{ts}_{name}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            log.info(f"[Screenshot] Salva: {path.name}")
        except Exception as exc:
            log.warning(f"[Screenshot] Falha ao salvar '{name}': {exc}")
