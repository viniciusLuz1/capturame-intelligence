"""
scripts/gerar_dashboard.py
===========================
Gera docs/index.html com o dashboard de dados do CapturaME Intelligence.
Publicado via GitHub Pages.

Uso:
    python scripts/gerar_dashboard.py
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.database import DB_PATH

DOCS_DIR = Path(__file__).parent.parent / "docs"
OUT_FILE = DOCS_DIR / "index.html"


def query(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def build_data(conn):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Cards
    total_leiloes   = query(conn, "SELECT COUNT(*) FROM leiloes")[0][0]
    abertos         = query(conn, "SELECT COUNT(*) FROM leiloes WHERE status='open'")[0][0]
    total_itens     = query(conn, "SELECT COUNT(*) FROM leilao_itens")[0][0]
    nms_unicos      = query(conn, "SELECT COUNT(DISTINCT nm) FROM leilao_itens WHERE nm IS NOT NULL AND nm!='None'")[0][0]
    leiloes_cobertos= query(conn, "SELECT COUNT(DISTINCT leilao_id) FROM leilao_itens")[0][0]

    # Status breakdown
    status_rows = query(conn, """
        SELECT status, COUNT(*) as n FROM leiloes GROUP BY status ORDER BY n DESC
    """)
    status_labels = [r[0] or "outros" for r in status_rows]
    status_values = [r[1] for r in status_rows]

    # Leilões abertos + itens
    leiloes_abertos = query(conn, """
        SELECT l.id_externo, l.titulo, l.data_expiracao,
               l.cidade_entrega, l.uf_entrega,
               COUNT(li.id) as n_itens,
               l.reopen
        FROM leiloes l
        LEFT JOIN leilao_itens li ON li.leilao_id = l.id_externo
        WHERE l.status = 'open'
        GROUP BY l.id_externo
        ORDER BY l.data_expiracao ASC
    """)

    # NMs mais recorrentes
    nms_recorrentes = query(conn, """
        SELECT li.nm, li.nome,
               COUNT(DISTINCT li.leilao_id) as qtd_leiloes,
               MIN(li.total) as menor_total,
               MAX(li.total) as maior_total
        FROM leilao_itens li
        WHERE li.nm IS NOT NULL AND li.nm != 'None'
        GROUP BY li.nm
        HAVING COUNT(DISTINCT li.leilao_id) > 1
        ORDER BY qtd_leiloes DESC
        LIMIT 20
    """)

    # Itens do último leilão aberto
    itens_recentes = query(conn, """
        SELECT l.titulo, li.nm, li.nome, li.qnt, li.unidade, li.marca, li.partnumber, li.total
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        WHERE l.status = 'open'
        ORDER BY l.id_externo DESC, li.id
        LIMIT 50
    """)

    # Cidades de entrega
    cidades = query(conn, """
        SELECT cidade_entrega, uf_entrega, COUNT(*) as n
        FROM leiloes
        WHERE cidade_entrega IS NOT NULL AND status='open'
        GROUP BY cidade_entrega, uf_entrega
        ORDER BY n DESC
        LIMIT 10
    """)

    return {
        "now": now,
        "total_leiloes": total_leiloes,
        "abertos": abertos,
        "total_itens": total_itens,
        "nms_unicos": nms_unicos,
        "leiloes_cobertos": leiloes_cobertos,
        "status_labels": status_labels,
        "status_values": status_values,
        "leiloes_abertos": leiloes_abertos,
        "nms_recorrentes": nms_recorrentes,
        "itens_recentes": itens_recentes,
        "cidades": cidades,
    }


def render(d):
    def rows_leiloes():
        linhas = []
        for r in d["leiloes_abertos"]:
            lid, titulo, exp, cidade, uf, n_itens, reopen = r
            loc = f"{cidade}/{uf}" if cidade else "—"
            reopen_txt = f'<span class="badge bg-warning text-dark">reabre {reopen[:10]}</span>' if reopen else ""
            linhas.append(f"""
            <tr>
              <td class="text-muted small">{lid}</td>
              <td>{titulo or "—"}</td>
              <td class="small">{exp or "—"}</td>
              <td class="small">{loc}</td>
              <td class="text-center"><span class="badge bg-primary">{n_itens}</span></td>
              <td>{reopen_txt}</td>
            </tr>""")
        return "\n".join(linhas)

    def rows_nms():
        linhas = []
        for r in d["nms_recorrentes"]:
            nm, nome, qtd, menor, maior = r
            linhas.append(f"""
            <tr>
              <td class="font-monospace small">{nm}</td>
              <td>{(nome or "")[:60]}</td>
              <td class="text-center"><span class="badge bg-danger">{qtd}x</span></td>
              <td class="small text-success">{menor or "—"}</td>
              <td class="small text-danger">{maior or "—"}</td>
            </tr>""")
        return "\n".join(linhas)

    def rows_itens():
        linhas = []
        for r in d["itens_recentes"]:
            titulo, nm, nome, qnt, un, marca, pn, total = r
            linhas.append(f"""
            <tr>
              <td class="small text-muted">{(titulo or "")[:30]}</td>
              <td class="font-monospace small">{nm or "—"}</td>
              <td>{(nome or "")[:55]}</td>
              <td class="text-center">{qnt or "—"}</td>
              <td class="text-center">{un or "—"}</td>
              <td class="small">{(marca or "—")[:25]}</td>
              <td class="small text-success fw-bold">{total or "—"}</td>
            </tr>""")
        return "\n".join(linhas)

    def rows_cidades():
        linhas = []
        for cidade, uf, n in d["cidades"]:
            linhas.append(f"<tr><td>{cidade}</td><td>{uf}</td><td class='text-center'><span class='badge bg-secondary'>{n}</span></td></tr>")
        return "\n".join(linhas)

    status_colors = {
        "open": "#6f42c1", "close": "#6c757d",
        "cancel": "#dc3545", "temp": "#fd7e14",
    }
    chart_colors = json.dumps([status_colors.get(s, "#adb5bd") for s in d["status_labels"]])

    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CapturaME Intelligence – Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    body {{ background: #f8f9fa; }}
    .card-metric {{ border-left: 4px solid #6f42c1; }}
    .card-metric .display-5 {{ color: #6f42c1; font-weight: 700; }}
    th {{ white-space: nowrap; }}
    .table-sm td, .table-sm th {{ padding: .3rem .5rem; font-size: .85rem; }}
    .section-title {{ border-left: 3px solid #6f42c1; padding-left: .6rem; margin: 1.5rem 0 .8rem; }}
  </style>
</head>
<body>
<nav class="navbar navbar-dark" style="background:#6f42c1;">
  <div class="container-fluid">
    <span class="navbar-brand fw-bold">⚡ CapturaME Intelligence</span>
    <span class="text-white-50 small">Atualizado: {d["now"]}</span>
  </div>
</nav>

<div class="container-fluid py-3">

  <!-- Cards -->
  <div class="row g-3 mb-3">
    <div class="col-6 col-md-3">
      <div class="card card-metric h-100 shadow-sm">
        <div class="card-body">
          <div class="text-muted small">Total Leilões</div>
          <div class="display-5">{d["total_leiloes"]:,}</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#198754;">
        <div class="card-body">
          <div class="text-muted small">Em Aberto</div>
          <div class="display-5" style="color:#198754;">{d["abertos"]:,}</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#0d6efd;">
        <div class="card-body">
          <div class="text-muted small">Itens Coletados</div>
          <div class="display-5" style="color:#0d6efd;">{d["total_itens"]:,}</div>
          <div class="text-muted small">{d["leiloes_cobertos"]:,} leilões cobertos</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#dc3545;">
        <div class="card-body">
          <div class="text-muted small">NMs Únicos</div>
          <div class="display-5" style="color:#dc3545;">{d["nms_unicos"]:,}</div>
        </div>
      </div>
    </div>
  </div>

  <div class="row g-3">

    <!-- Chart + Cidades -->
    <div class="col-md-4">
      <div class="card shadow-sm h-100">
        <div class="card-body">
          <h6 class="section-title">Leilões por Status</h6>
          <canvas id="statusChart" height="180"></canvas>
        </div>
      </div>
    </div>

    <div class="col-md-4">
      <div class="card shadow-sm h-100">
        <div class="card-body">
          <h6 class="section-title">Cidades de Entrega (abertos)</h6>
          <table class="table table-sm table-hover">
            <thead><tr><th>Cidade</th><th>UF</th><th>Leilões</th></tr></thead>
            <tbody>{rows_cidades()}</tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- NMs recorrentes -->
    <div class="col-md-4">
      <div class="card shadow-sm h-100">
        <div class="card-body">
          <h6 class="section-title">NMs Recorrentes (reprocessos)</h6>
          <table class="table table-sm table-hover">
            <thead><tr><th>NM</th><th>Item</th><th>Vezes</th><th>Mín</th><th>Máx</th></tr></thead>
            <tbody>{rows_nms()}</tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Leilões abertos -->
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <h6 class="section-title">Leilões Abertos ({d["abertos"]})</h6>
          <div class="table-responsive">
            <table class="table table-sm table-hover table-striped">
              <thead class="table-light">
                <tr><th>ID</th><th>Título</th><th>Expira</th><th>Entrega</th><th>Itens</th><th></th></tr>
              </thead>
              <tbody>{rows_leiloes()}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Últimos itens -->
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <h6 class="section-title">Itens dos Leilões Abertos (últimos 50)</h6>
          <div class="table-responsive">
            <table class="table table-sm table-hover">
              <thead class="table-light">
                <tr><th>Leilão</th><th>NM</th><th>Nome</th><th>Qtd</th><th>Un</th><th>Marca</th><th>Valor Est.</th></tr>
              </thead>
              <tbody>{rows_itens()}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
new Chart(document.getElementById('statusChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(d["status_labels"])},
    datasets: [{{ data: {json.dumps(d["status_values"])}, backgroundColor: {chart_colors}, borderWidth: 2 }}]
  }},
  options: {{ plugins: {{ legend: {{ position: 'bottom' }} }}, cutout: '60%' }}
}});
</script>
</body>
</html>"""


def main():
    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        sys.exit(1)

    DOCS_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    data = build_data(conn)
    conn.close()

    html = render(data)
    OUT_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard gerado: {OUT_FILE}")
    print(f"  Leilões: {data['total_leiloes']:,} | Abertos: {data['abertos']:,} | Itens: {data['total_itens']:,}")


if __name__ == "__main__":
    main()
