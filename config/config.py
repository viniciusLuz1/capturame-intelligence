"""
config/config.py
================
Configurações centralizadas do CapturaME Intelligence.

Todas as constantes, caminhos, timeouts e flags devem ser
importados daqui – nunca dispersos pelo código.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ------------------------------------------------------------------ #
# Carrega variáveis do .env (se existir)
# ------------------------------------------------------------------ #
load_dotenv()

# ------------------------------------------------------------------ #
# Diretórios base
# ------------------------------------------------------------------ #
BASE_DIR: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path       = BASE_DIR / "data"
AUTH_DIR: Path       = DATA_DIR / "auth"
SCREENSHOTS_DIR: Path = BASE_DIR / "screenshots"
LOGS_DIR: Path       = BASE_DIR / "logs"
NETWORK_DIR: Path    = LOGS_DIR / "network"
TRACES_DIR: Path     = LOGS_DIR / "traces"
REPORTS_DIR: Path    = BASE_DIR / "reports"

# Garante que todos os diretórios existem
for _dir in (AUTH_DIR, SCREENSHOTS_DIR, LOGS_DIR, NETWORK_DIR, TRACES_DIR, REPORTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ #
# Arquivo de sessão
# ------------------------------------------------------------------ #
STORAGE_STATE_PATH: Path = AUTH_DIR / "storage_state.json"

# ------------------------------------------------------------------ #
# URL alvo
# ------------------------------------------------------------------ #
BASE_URL: str = "https://www.capturame.com.br"
LOGIN_URL: str = f"{BASE_URL}/login"

# ------------------------------------------------------------------ #
# Credenciais (lidas exclusivamente de variáveis de ambiente)
# ------------------------------------------------------------------ #
CAPTURAME_USER: str     = os.getenv("CAPTURAME_USER", "")
CAPTURAME_PASSWORD: str = os.getenv("CAPTURAME_PASSWORD", "")

# ------------------------------------------------------------------ #
# Configurações do navegador
# ------------------------------------------------------------------ #
HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"
TIMEOUT: int   = int(os.getenv("TIMEOUT", "30000"))   # ms

# Viewport padrão
VIEWPORT_WIDTH: int  = 1440
VIEWPORT_HEIGHT: int = 900

# User-Agent realista
USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ------------------------------------------------------------------ #
# Configurações de log
# ------------------------------------------------------------------ #
LOG_FILE: Path   = LOGS_DIR / "app.log"
LOG_FORMAT: str  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FMT: str = "%Y-%m-%d %H:%M:%S"

# ------------------------------------------------------------------ #
# Configurações de tracing Playwright
# ------------------------------------------------------------------ #
TRACE_SCREENSHOTS: bool = True
TRACE_SNAPSHOTS: bool   = True
TRACE_SOURCES: bool     = True

# ------------------------------------------------------------------ #
# Seletores da CapturaME
# (centralizados para facilitar manutenção quando o site mudar)
# ------------------------------------------------------------------ #
SELECTORS: dict = {
    # Campo de e-mail / usuário na tela de login
    "login_email":    "input[type='email'], input[name='email'], input[name='usuario'], input[placeholder*='mail']",
    # Campo de senha
    "login_password": "input[type='password']",
    # Botão de submit do formulário de login
    "login_submit":   "button[type='submit'], input[type='submit'], button:has-text('Entrar'), button:has-text('Login'), button:has-text('Acessar')",
    # Indicadores de login bem-sucedido (qualquer um destes presentes = autenticado)
    "auth_indicators": [
        "nav",
        "[class*='dashboard']",
        "[class*='usuario']",
        "[class*='perfil']",
        "[class*='logout']",
        "a[href*='logout']",
        "a[href*='sair']",
    ],
    # Indicadores de erro de login
    "login_error": [
        "[class*='error']",
        "[class*='erro']",
        "[class*='alert']",
        "p:has-text('inválido')",
        "p:has-text('incorreto')",
    ],
}

# ------------------------------------------------------------------ #
# Tipos de requisição de rede a monitorar
# ------------------------------------------------------------------ #
MONITORED_RESOURCE_TYPES: list[str] = ["xhr", "fetch"]

# Extensões/domínios a ignorar no monitor de rede (ruído)
IGNORED_URL_PATTERNS: list[str] = [
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".css",
    "google-analytics", "googletagmanager", "facebook", "hotjar",
    "doubleclick", "googlesyndication",
    # Widget de chat ao vivo – ruído sem relevância
    "tawk.to", "tawkto", "embed.tawk", "va.tawk",
    # Outros trackers
    "sentry.io", "amplitude.com", "segment.io", "mixpanel.com",
]
