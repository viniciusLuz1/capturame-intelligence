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

    # Itens por mês (baseado na data_criacao do leilão — formato DD/MM/YYYY)
    itens_por_mes = query(conn, """
        SELECT
            substr(l.data_criacao, 7, 4) || '-' || substr(l.data_criacao, 4, 2) AS periodo,
            COUNT(DISTINCT l.id_externo)  AS qtd_leiloes,
            COUNT(li.id)                  AS qtd_itens,
            COUNT(DISTINCT li.nm)         AS qtd_nms
        FROM leiloes l
        LEFT JOIN leilao_itens li ON li.leilao_id = l.id_externo
        WHERE l.data_criacao IS NOT NULL AND length(l.data_criacao) >= 10
        GROUP BY periodo
        ORDER BY periodo ASC
    """)

    # Itens por semana
    itens_por_semana = query(conn, """
        SELECT
            substr(l.data_criacao, 7, 4) || '-' ||
            printf('%02d', (
                (CAST(substr(l.data_criacao, 1, 2) AS INTEGER) +
                 (CAST(substr(l.data_criacao, 4, 2) AS INTEGER) - 1) * 30) / 7
            )) AS semana,
            substr(l.data_criacao, 7, 4) AS ano,
            substr(l.data_criacao, 4, 2) AS mes,
            substr(l.data_criacao, 1, 2) AS dia,
            COUNT(DISTINCT l.id_externo) AS qtd_leiloes,
            COUNT(li.id)                 AS qtd_itens,
            COUNT(DISTINCT li.nm)        AS qtd_nms
        FROM leiloes l
        LEFT JOIN leilao_itens li ON li.leilao_id = l.id_externo
        WHERE l.data_criacao IS NOT NULL AND length(l.data_criacao) >= 10
        GROUP BY ano, mes, dia
        ORDER BY ano, mes, dia
    """)

    # NMs: primeiras aparições por mês (quando cada NM apareceu pela 1a vez)
    nms_novos_por_mes = query(conn, """
        SELECT
            substr(l.data_criacao, 7, 4) || '-' || substr(l.data_criacao, 4, 2) AS periodo,
            COUNT(DISTINCT li.nm) AS nms_novos
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        WHERE li.nm IS NOT NULL AND li.nm != 'None'
          AND l.data_criacao = (
              SELECT MIN(l2.data_criacao)
              FROM leilao_itens li2
              JOIN leiloes l2 ON l2.id_externo = li2.leilao_id
              WHERE li2.nm = li.nm
          )
        GROUP BY periodo
        ORDER BY periodo ASC
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
        "itens_por_mes": itens_por_mes,
        "nms_novos_por_mes": nms_novos_por_mes,
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

    # Dados do gráfico de período
    meses       = json.dumps([r[0] for r in d["itens_por_mes"]])
    qtd_leiloes = json.dumps([r[1] for r in d["itens_por_mes"]])
    qtd_itens   = json.dumps([r[2] for r in d["itens_por_mes"]])
    qtd_nms     = json.dumps([r[3] for r in d["itens_por_mes"]])
    nms_novos_labels = json.dumps([r[0] for r in d["nms_novos_por_mes"]])
    nms_novos_vals   = json.dumps([r[1] for r in d["nms_novos_por_mes"]])

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

    <!-- Gráfico por período -->
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
            <h6 class="section-title mb-0">Itens por Período</h6>
            <div class="d-flex gap-2">
              <div class="btn-group btn-group-sm" role="group">
                <button class="btn btn-outline-secondary active" onclick="filtrarPeriodo(3,this)">3 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(6,this)">6 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(12,this)">12 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(999,this)">Tudo</button>
              </div>
              <div class="btn-group btn-group-sm" role="group">
                <button class="btn btn-purple active" id="btnLeiloes" onclick="toggleSerie('leiloes',this)">Leilões</button>
                <button class="btn btn-purple" id="btnItens" onclick="toggleSerie('itens',this)">Itens</button>
                <button class="btn btn-purple" id="btnNMs" onclick="toggleSerie('nms',this)">NMs</button>
              </div>
            </div>
          </div>
          <canvas id="periodoChart" height="80"></canvas>
        </div>
      </div>
    </div>

    <!-- NMs novos por mês -->
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <h6 class="section-title">NMs Novos por Mês <small class="text-muted fw-normal">(primeira aparição)</small></h6>
          <canvas id="nmsNovosChart" height="60"></canvas>
        </div>
      </div>
    </div>

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

<style>
  .btn-purple {{ background:#6f42c1; color:#fff; border-color:#6f42c1; }}
  .btn-purple:hover, .btn-purple.active {{ background:#5a32a3; border-color:#5a32a3; color:#fff; }}
</style>
<script>
// Dados completos de período
const todosMeses    = {meses};
const todosLeiloes  = {qtd_leiloes};
const todosItens    = {qtd_itens};
const todosNMs      = {qtd_nms};

// Estado dos toggles
const seriesVisiveis = {{ leiloes: true, itens: false, nms: false }};

const periodoCtx = document.getElementById('periodoChart');
const periodoChart = new Chart(periodoCtx, {{
  type: 'bar',
  data: {{
    labels: todosMeses,
    datasets: [
      {{
        label: 'Leilões',
        data: todosLeiloes,
        backgroundColor: 'rgba(111,66,193,0.7)',
        borderColor: '#6f42c1',
        borderWidth: 1,
        hidden: false,
      }},
      {{
        label: 'Itens',
        data: todosItens,
        backgroundColor: 'rgba(13,110,253,0.7)',
        borderColor: '#0d6efd',
        borderWidth: 1,
        hidden: true,
      }},
      {{
        label: 'NMs únicos',
        data: todosNMs,
        backgroundColor: 'rgba(25,135,84,0.7)',
        borderColor: '#198754',
        borderWidth: 1,
        hidden: true,
      }},
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{ beginAtZero: true }},
    }}
  }}
}});

function filtrarPeriodo(meses, btn) {{
  document.querySelectorAll('[onclick^="filtrarPeriodo"]').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const n = meses >= 999 ? todosMeses.length : meses;
  const labels = todosMeses.slice(-n);
  periodoChart.data.labels = labels;
  periodoChart.data.datasets[0].data = todosLeiloes.slice(-n);
  periodoChart.data.datasets[1].data = todosItens.slice(-n);
  periodoChart.data.datasets[2].data = todosNMs.slice(-n);
  periodoChart.update();
}}

function toggleSerie(serie, btn) {{
  const map = {{ leiloes: 0, itens: 1, nms: 2 }};
  const idx = map[serie];
  const meta = periodoChart.getDatasetMeta(idx);
  meta.hidden = !meta.hidden;
  btn.classList.toggle('active', !meta.hidden);
  periodoChart.update();
}}

// NMs novos por mês
new Chart(document.getElementById('nmsNovosChart'), {{
  type: 'line',
  data: {{
    labels: {nms_novos_labels},
    datasets: [{{
      label: 'NMs novos',
      data: {nms_novos_vals},
      borderColor: '#dc3545',
      backgroundColor: 'rgba(220,53,69,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{ beginAtZero: true }},
    }}
  }}
}});

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
