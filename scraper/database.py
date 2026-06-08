"""
scraper/database.py
===================
Persistência em SQLite para as Fases 2 e 3.

Tabelas:
  - leiloes      : leilões capturados da aba Leilão
  - cotacoes     : cotações capturadas da aba Cotação
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

from config.config import DATA_DIR
from scraper.logger import get_logger

log = get_logger(__name__)

DB_PATH: Path = DATA_DIR / "capturame.db"


class DatabaseManager:
    """Gerencia conexão SQLite e operações de upsert."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        log.info(f"[DB] Banco de dados: {db_path}")

    # ---------------------------------------------------------------- #
    # Schema
    # ---------------------------------------------------------------- #

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS leiloes (
                id_externo      INTEGER PRIMARY KEY,
                code            TEXT,
                titulo          TEXT,
                status          TEXT,
                status_resp     TEXT,
                data_criacao    TEXT,
                data_expiracao  TEXT,
                reopen          TEXT,
                capturado_em    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cotacoes (
                id_externo      INTEGER PRIMARY KEY,
                code            TEXT,
                titulo          TEXT,
                status_resp     TEXT,
                data_criacao    TEXT,
                data_expiracao  TEXT,
                capturado_em    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leilao_itens (
                id              INTEGER PRIMARY KEY,
                leilao_id       INTEGER NOT NULL,
                nm              TEXT,
                lote            TEXT,
                nome            TEXT,
                qnt             TEXT,
                unidade         TEXT,
                marca           TEXT,
                partnumber      TEXT,
                total           TEXT,
                valorunitario   TEXT,
                capturado_em    TEXT NOT NULL,
                FOREIGN KEY(leilao_id) REFERENCES leiloes(id_externo)
            );

            CREATE INDEX IF NOT EXISTS idx_leiloes_status   ON leiloes(status);
            CREATE INDEX IF NOT EXISTS idx_leiloes_exp      ON leiloes(data_expiracao);
            CREATE INDEX IF NOT EXISTS idx_cotacoes_status  ON cotacoes(status_resp);
            CREATE INDEX IF NOT EXISTS idx_itens_leilao     ON leilao_itens(leilao_id);
        """)
        # Adiciona colunas de entrega na tabela leiloes se não existirem
        for col in ["local_entrega", "cidade_entrega", "uf_entrega", "cep_entrega"]:
            try:
                self.conn.execute(f"ALTER TABLE leiloes ADD COLUMN {col} TEXT")
            except Exception:
                pass  # coluna já existe
        self.conn.commit()
        self.conn.commit()

    # ---------------------------------------------------------------- #
    # Leilões
    # ---------------------------------------------------------------- #

    def upsert_leilao(self, row: dict) -> None:
        self.conn.execute("""
            INSERT INTO leiloes
                (id_externo, code, titulo, status, status_resp,
                 data_criacao, data_expiracao, reopen, capturado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id_externo) DO UPDATE SET
                titulo         = excluded.titulo,
                status         = excluded.status,
                status_resp    = excluded.status_resp,
                data_expiracao = excluded.data_expiracao,
                reopen         = excluded.reopen,
                capturado_em   = excluded.capturado_em
        """, (
            row.get("id"),
            row.get("code"),
            row.get("titulo"),
            row.get("status"),
            row.get("status_resp"),
            row.get("created_at"),
            row.get("data_hora_exp"),
            row.get("reopen"),
            datetime.now().isoformat(),
        ))

    def count_leiloes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM leiloes").fetchone()[0]

    # ---------------------------------------------------------------- #
    # Cotações
    # ---------------------------------------------------------------- #

    def upsert_cotacao(self, row: dict) -> None:
        self.conn.execute("""
            INSERT INTO cotacoes
                (id_externo, code, titulo, status_resp,
                 data_criacao, data_expiracao, capturado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id_externo) DO UPDATE SET
                titulo         = excluded.titulo,
                status_resp    = excluded.status_resp,
                data_expiracao = excluded.data_expiracao,
                capturado_em   = excluded.capturado_em
        """, (
            row.get("id"),
            row.get("code"),
            row.get("titulo"),
            row.get("status_resp"),
            row.get("created_at"),
            row.get("data_hora_exp"),
            datetime.now().isoformat(),
        ))

    def count_cotacoes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cotacoes").fetchone()[0]

    # ---------------------------------------------------------------- #
    # Itens de leilão (Fase 3)
    # ---------------------------------------------------------------- #

    def upsert_leilao_item(self, leilao_id: int, row: dict) -> None:
        self.conn.execute("""
            INSERT INTO leilao_itens
                (id, leilao_id, nm, lote, nome, qnt, unidade,
                 marca, partnumber, total, valorunitario, capturado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                nome          = excluded.nome,
                qnt           = excluded.qnt,
                unidade       = excluded.unidade,
                marca         = excluded.marca,
                partnumber    = excluded.partnumber,
                total         = excluded.total,
                valorunitario = excluded.valorunitario,
                capturado_em  = excluded.capturado_em
        """, (
            row.get("id"),
            leilao_id,
            row.get("cod"),
            row.get("lote"),
            row.get("name"),
            row.get("qnt"),
            row.get("unt"),
            row.get("brand"),
            row.get("partnumber"),
            row.get("total"),
            row.get("valorunitario"),
            datetime.now().isoformat(),
        ))

    def update_leilao_entrega(self, leilao_id: int, local: str, cidade: str, uf: str, cep: str) -> None:
        self.conn.execute("""
            UPDATE leiloes SET
                local_entrega  = ?,
                cidade_entrega = ?,
                uf_entrega     = ?,
                cep_entrega    = ?
            WHERE id_externo = ?
        """, (local, cidade, uf, cep, leilao_id))

    def get_leiloes_sem_itens(self, status_filter: Optional[str] = None) -> list:
        """Retorna leilões que ainda não tiveram seus itens coletados."""
        query = """
            SELECT l.id_externo, l.code
            FROM leiloes l
            WHERE NOT EXISTS (
                SELECT 1 FROM leilao_itens li WHERE li.leilao_id = l.id_externo
            )
        """
        if status_filter:
            query += f" AND l.status = '{status_filter}'"
        query += " ORDER BY CASE l.status WHEN 'open' THEN 0 ELSE 1 END, l.id_externo DESC"
        return self.conn.execute(query).fetchall()

    def count_leilao_itens(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM leilao_itens").fetchone()[0]

    # ---------------------------------------------------------------- #
    # Utilitários
    # ---------------------------------------------------------------- #

    def commit(self) -> None:
        self.conn.commit()

    def get_stats(self) -> dict:
        return {
            "leiloes":       self.count_leiloes(),
            "cotacoes":      self.count_cotacoes(),
            "leilao_itens":  self.count_leilao_itens(),
        }

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
