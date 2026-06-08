"""
scraper/logger.py
=================
Fábrica de loggers estruturados para o CapturaME Intelligence.

Uso:
    from scraper.logger import get_logger
    log = get_logger(__name__)
    log.info("Mensagem")
"""

import logging
import sys
from pathlib import Path

from config.config import LOG_FILE, LOG_FORMAT, LOG_DATE_FMT

_initialized = False


def _setup_root_logger() -> None:
    """Configura o logger raiz uma única vez."""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FMT)

    # Handler para arquivo
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # Handler para console (stdout)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    root.addHandler(fh)
    root.addHandler(ch)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger configurado para o módulo informado."""
    _setup_root_logger()
    return logging.getLogger(name)
