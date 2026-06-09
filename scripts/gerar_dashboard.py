"""
scripts/gerar_dashboard.py
===========================
Gera docs/index.html com o dashboard de dados do CapturaME Intelligence.
Publicado via GitHub Pages.
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


def build_nm_data(conn):
    """Constrói estrutura de busca por NM com histórico de propostas."""
    rows = conn.execute("""
        SELECT li.nm, li.nome, l.id_externo, l.data_criacao,
               COALESCE(l.cidade_entrega,''), COALESCE(l.uf_entrega,''),
               COALESCE(li.qnt,''), COALESCE(li.unidade,''),
               lr.posicao, COALESCE(lr.fornecedor,''),
               COALESCE(lr.valor_unitario,''), COALESCE(lr.valor_total,'')
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        JOIN leilao_resultados lr ON lr.leilao_id = li.leilao_id
            AND lr.item_nome = li.nome
        WHERE li.nm IS NOT NULL AND li.nm != 'None'
        ORDER BY li.nm, l.data_criacao DESC, lr.posicao ASC
    """).fetchall()

    data = {}
    for nm, nome, lid, dt, cidade, uf, qnt, un, pos, forn, vu, vt in rows:
        if nm not in data:
            data[nm] = {'n': nome or '', 'l': {}}
        leiloes = data[nm]['l']
        if lid not in leiloes:
            loc = f"{cidade}/{uf}" if cidade else (uf or '')
            leiloes[lid] = {'dt': dt or '', 'ci': loc, 'qt': qnt, 'un': un, 'pr': []}
        leiloes[lid]['pr'].append({
            'p': pos, 'f': forn, 'vu': vu, 'vt': vt
        })

    # Converte para listas ordenadas por data desc
    result = {}
    for nm, d in data.items():
        leiloes_list = sorted(d['l'].values(), key=lambda x: x['dt'], reverse=True)
        result[nm] = {'n': d['n'], 'l': leiloes_list}
    return result


def build_data(conn):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Cards
    total_leiloes    = query(conn, "SELECT COUNT(*) FROM leiloes")[0][0]
    abertos          = query(conn, "SELECT COUNT(*) FROM leiloes WHERE status='open'")[0][0]
    total_itens      = query(conn, "SELECT COUNT(*) FROM leilao_itens")[0][0]
    nms_unicos       = query(conn, "SELECT COUNT(DISTINCT nm) FROM leilao_itens WHERE nm IS NOT NULL AND nm!='None'")[0][0]
    leiloes_cobertos = query(conn, "SELECT COUNT(DISTINCT leilao_id) FROM leilao_itens")[0][0]
    total_propostas  = query(conn, "SELECT COUNT(*) FROM leilao_resultados")[0][0]
    leiloes_resultado= query(conn, "SELECT COUNT(DISTINCT leilao_id) FROM leilao_resultados")[0][0]

    # Status breakdown
    status_rows = query(conn, "SELECT status, COUNT(*) as n FROM leiloes GROUP BY status ORDER BY n DESC")
    status_labels = [r[0] or "outros" for r in status_rows]
    status_values = [r[1] for r in status_rows]

    # Leilões abertos + itens
    leiloes_abertos = query(conn, """
        SELECT l.id_externo, l.titulo, l.data_expiracao,
               l.cidade_entrega, l.uf_entrega,
               COUNT(li.id) as n_itens, l.reopen
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

    # Itens dos leilões abertos
    itens_recentes = query(conn, """
        SELECT l.titulo, li.nm, li.nome, li.qnt, li.unidade, li.marca, li.partnumber, li.total
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        WHERE l.status = 'open'
        ORDER BY l.id_externo DESC, li.id
        LIMIT 50
    """)

    # Cidades (leilões abertos)
    cidades = query(conn, """
        SELECT cidade_entrega, uf_entrega, COUNT(*) as n
        FROM leiloes
        WHERE cidade_entrega IS NOT NULL AND status='open'
        GROUP BY cidade_entrega, uf_entrega
        ORDER BY n DESC LIMIT 10
    """)

    # Itens por mês
    itens_por_mes = query(conn, """
        SELECT substr(l.data_criacao,7,4)||'-'||substr(l.data_criacao,4,2) AS periodo,
               COUNT(DISTINCT l.id_externo) AS qtd_leiloes,
               COUNT(li.id)                AS qtd_itens,
               COUNT(DISTINCT li.nm)       AS qtd_nms
        FROM leiloes l
        LEFT JOIN leilao_itens li ON li.leilao_id = l.id_externo
        WHERE l.data_criacao IS NOT NULL AND length(l.data_criacao) >= 10
        GROUP BY periodo ORDER BY periodo ASC
    """)

    # NMs novos por mês
    nms_novos_por_mes = query(conn, """
        SELECT substr(l.data_criacao,7,4)||'-'||substr(l.data_criacao,4,2) AS periodo,
               COUNT(DISTINCT li.nm) AS nms_novos
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        WHERE li.nm IS NOT NULL AND li.nm != 'None'
          AND l.data_criacao = (
              SELECT MIN(l2.data_criacao) FROM leilao_itens li2
              JOIN leiloes l2 ON l2.id_externo = li2.leilao_id
              WHERE li2.nm = li.nm)
        GROUP BY periodo ORDER BY periodo ASC
    """)

    # Ranking de fornecedores
    ranking = query(conn, """
        SELECT fornecedor,
               SUM(CASE WHEN posicao=1 THEN 1 ELSE 0 END) as vitorias,
               COUNT(DISTINCT leilao_id) as leiloes_part,
               COUNT(*) as total_propostas
        FROM leilao_resultados
        GROUP BY fornecedor
        ORDER BY vitorias DESC
        LIMIT 30
    """)

    # NM stats (para busca)
    nm_stats = query(conn, """
        SELECT li.nm, MAX(li.nome) as nome,
               COUNT(DISTINCT li.leilao_id) as ocorrencias,
               COUNT(DISTINCT CASE WHEN l.status='open' THEN li.leilao_id END) as abertos,
               GROUP_CONCAT(DISTINCT COALESCE(l.cidade_entrega||'/'||l.uf_entrega, '')) as cidades
        FROM leilao_itens li
        JOIN leiloes l ON l.id_externo = li.leilao_id
        WHERE li.nm IS NOT NULL AND li.nm != 'None'
        GROUP BY li.nm
        ORDER BY ocorrencias DESC
    """)

    # NM full data para busca
    nm_data = build_nm_data(conn)

    return {
        "now": now,
        "total_leiloes": total_leiloes,
        "abertos": abertos,
        "total_itens": total_itens,
        "nms_unicos": nms_unicos,
        "leiloes_cobertos": leiloes_cobertos,
        "total_propostas": total_propostas,
        "leiloes_resultado": leiloes_resultado,
        "status_labels": status_labels,
        "status_values": status_values,
        "leiloes_abertos": leiloes_abertos,
        "nms_recorrentes": nms_recorrentes,
        "itens_recentes": itens_recentes,
        "cidades": cidades,
        "itens_por_mes": itens_por_mes,
        "nms_novos_por_mes": nms_novos_por_mes,
        "ranking": ranking,
        "nm_stats": nm_stats,
        "nm_data": nm_data,
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

    def rows_ranking():
        linhas = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (forn, vit, part, props) in enumerate(d["ranking"], 1):
            taxa = f"{vit/part*100:.0f}%" if part else "—"
            medal = medals.get(i, str(i))
            badge = "bg-warning text-dark" if i == 1 else ("bg-secondary" if i == 2 else ("bg-danger" if i == 3 else "bg-light text-dark"))
            linhas.append(f"""
            <tr>
              <td class="text-center"><span class="badge {badge}">{medal}</span></td>
              <td class="fw-semibold">{forn or "—"}</td>
              <td class="text-center text-success fw-bold">{vit}</td>
              <td class="text-center">{part}</td>
              <td class="text-center text-muted">{taxa}</td>
            </tr>""")
        return "\n".join(linhas)

    status_colors = {
        "open": "#6f42c1", "close": "#6c757d",
        "cancel": "#dc3545", "temp": "#fd7e14",
    }
    chart_colors = json.dumps([status_colors.get(s, "#adb5bd") for s in d["status_labels"]])

    meses       = json.dumps([r[0] for r in d["itens_por_mes"]])
    qtd_leiloes = json.dumps([r[1] for r in d["itens_por_mes"]])
    qtd_itens   = json.dumps([r[2] for r in d["itens_por_mes"]])
    qtd_nms     = json.dumps([r[3] for r in d["itens_por_mes"]])
    nms_novos_labels = json.dumps([r[0] for r in d["nms_novos_por_mes"]])
    nms_novos_vals   = json.dumps([r[1] for r in d["nms_novos_por_mes"]])

    # NM search data
    nm_index_js = json.dumps([
        {"nm": r[0], "n": r[1] or "", "oc": r[2], "ab": r[3] or 0,
         "ci": [c for c in (r[4] or "").split(",") if c and c != "/"]}
        for r in d["nm_stats"]
    ], ensure_ascii=False)
    nm_data_js = json.dumps(d["nm_data"], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CapturaME Intelligence – Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    body {{ background:#f8f9fa; }}
    .card-metric {{ border-left:4px solid #6f42c1; }}
    .card-metric .display-5 {{ color:#6f42c1; font-weight:700; }}
    th {{ white-space:nowrap; }}
    .table-sm td, .table-sm th {{ padding:.3rem .5rem; font-size:.85rem; }}
    .section-title {{ border-left:3px solid #6f42c1; padding-left:.6rem; margin:1.5rem 0 .8rem; }}
    .btn-purple {{ background:#6f42c1; color:#fff; border-color:#6f42c1; }}
    .btn-purple:hover, .btn-purple.active {{ background:#5a32a3; border-color:#5a32a3; color:#fff; }}
    .winner-row {{ background:#d1fae5 !important; }}
    #searchResults .proposal-table {{ font-size:.82rem; }}
    .nm-suggestion {{ cursor:pointer; padding:.4rem .7rem; border-bottom:1px solid #eee; }}
    .nm-suggestion:hover {{ background:#f0e9ff; }}
    #suggestionBox {{ position:absolute; z-index:999; background:#fff; border:1px solid #ccc;
                      border-radius:0 0 .5rem .5rem; max-height:260px; overflow-y:auto; width:100%; }}
    .search-wrap {{ position:relative; }}
    #noResult {{ display:none; }}
    .leilao-block {{ border:1px solid #dee2e6; border-radius:.5rem; margin-bottom:.8rem; overflow:hidden; }}
    .leilao-header {{ background:#f3f0fa; padding:.5rem .8rem; cursor:pointer; display:flex; justify-content:space-between; align-items:center; }}
    .leilao-header:hover {{ background:#e9e3f5; }}
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
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm">
        <div class="card-body">
          <div class="text-muted small">Total Leilões</div>
          <div class="display-5">{d["total_leiloes"]:,}</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#198754;">
        <div class="card-body">
          <div class="text-muted small">Em Aberto</div>
          <div class="display-5" style="color:#198754;">{d["abertos"]:,}</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#0d6efd;">
        <div class="card-body">
          <div class="text-muted small">Itens Coletados</div>
          <div class="display-5" style="color:#0d6efd;">{d["total_itens"]:,}</div>
          <div class="text-muted small">{d["leiloes_cobertos"]:,} leilões</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#dc3545;">
        <div class="card-body">
          <div class="text-muted small">NMs Únicos</div>
          <div class="display-5" style="color:#dc3545;">{d["nms_unicos"]:,}</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#fd7e14;">
        <div class="card-body">
          <div class="text-muted small">Propostas</div>
          <div class="display-5" style="color:#fd7e14;">{d["total_propostas"]:,}</div>
          <div class="text-muted small">{d["leiloes_resultado"]:,} leilões</div>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-metric h-100 shadow-sm" style="border-color:#0dcaf0;">
        <div class="card-body">
          <div class="text-muted small">Fornecedores</div>
          <div class="display-5" style="color:#0dcaf0;">{len(d["ranking"]):,}+</div>
          <div class="text-muted small">com histórico</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Busca por Item/NM -->
  <div class="row g-3 mb-3">
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <h6 class="section-title">🔍 Busca por Item / NM</h6>
          <p class="text-muted small mb-2">Digite o código NM ou parte do nome do item para ver histórico de processos, preços e fornecedores.</p>
          <div class="row g-2 align-items-start">
            <div class="col-md-6 search-wrap">
              <input type="text" id="searchInput" class="form-control" placeholder="Ex: 547973 ou botina ou cabo elétrico...">
              <div id="suggestionBox"></div>
            </div>
            <div class="col-md-6 d-flex gap-2 align-items-center">
              <div class="btn-group btn-group-sm" id="filterBtns" style="display:none!important;">
                <button class="btn btn-outline-secondary active" onclick="filtrarResultado('todos',this)">Todos</button>
                <button class="btn btn-outline-secondary" onclick="filtrarResultado('vencedores',this)">Só vencedores</button>
                <button class="btn btn-outline-secondary" onclick="filtrarResultado('ano',this)">Último ano</button>
              </div>
            </div>
          </div>
          <div id="nmSummary" class="mt-3" style="display:none">
            <div class="d-flex flex-wrap gap-2 mb-2" id="nmCards"></div>
          </div>
          <div id="searchResults" class="mt-2"></div>
          <div id="noResult" class="text-muted text-center py-3">Nenhum item encontrado.</div>
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
              <div class="btn-group btn-group-sm">
                <button class="btn btn-outline-secondary active" onclick="filtrarPeriodo(3,this)">3 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(6,this)">6 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(12,this)">12 meses</button>
                <button class="btn btn-outline-secondary" onclick="filtrarPeriodo(999,this)">Tudo</button>
              </div>
              <div class="btn-group btn-group-sm">
                <button class="btn btn-purple active" onclick="toggleSerie('leiloes',this)">Leilões</button>
                <button class="btn btn-purple" onclick="toggleSerie('itens',this)">Itens</button>
                <button class="btn btn-purple" onclick="toggleSerie('nms',this)">NMs</button>
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

    <!-- Ranking de fornecedores -->
    <div class="col-12">
      <div class="card shadow-sm">
        <div class="card-body">
          <h6 class="section-title">🏆 Ranking de Fornecedores <small class="text-muted fw-normal">(por vitórias em leilões)</small></h6>
          <div class="table-responsive">
            <table class="table table-sm table-hover table-striped">
              <thead class="table-light">
                <tr><th>#</th><th>Fornecedor</th><th class="text-center">Vitórias</th><th class="text-center">Leilões Participados</th><th class="text-center">Taxa</th></tr>
              </thead>
              <tbody>{rows_ranking()}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Status + Cidades -->
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

    <!-- Últimos itens abertos -->
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
const todosMeses   = {meses};
const todosLeiloes = {qtd_leiloes};
const todosItens   = {qtd_itens};
const todosNMs     = {qtd_nms};

// ── Gráfico de período ──────────────────────────────────────────────
const periodoChart = new Chart(document.getElementById('periodoChart'), {{
  type: 'bar',
  data: {{
    labels: todosMeses,
    datasets: [
      {{ label:'Leilões',   data:todosLeiloes, backgroundColor:'rgba(111,66,193,0.7)', borderColor:'#6f42c1', borderWidth:1, hidden:false }},
      {{ label:'Itens',     data:todosItens,   backgroundColor:'rgba(13,110,253,0.7)',  borderColor:'#0d6efd', borderWidth:1, hidden:true  }},
      {{ label:'NMs únicos',data:todosNMs,     backgroundColor:'rgba(25,135,84,0.7)',   borderColor:'#198754', borderWidth:1, hidden:true  }},
    ]
  }},
  options: {{ responsive:true, plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ grid:{{ display:false }} }}, y:{{ beginAtZero:true }} }} }}
}});

function filtrarPeriodo(meses, btn) {{
  document.querySelectorAll('[onclick^="filtrarPeriodo"]').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const n = meses >= 999 ? todosMeses.length : meses;
  periodoChart.data.labels = todosMeses.slice(-n);
  periodoChart.data.datasets[0].data = todosLeiloes.slice(-n);
  periodoChart.data.datasets[1].data = todosItens.slice(-n);
  periodoChart.data.datasets[2].data = todosNMs.slice(-n);
  periodoChart.update();
}}

function toggleSerie(serie, btn) {{
  const idx = {{leiloes:0,itens:1,nms:2}}[serie];
  const meta = periodoChart.getDatasetMeta(idx);
  meta.hidden = !meta.hidden;
  btn.classList.toggle('active', !meta.hidden);
  periodoChart.update();
}}

// ── Status doughnut ─────────────────────────────────────────────────
new Chart(document.getElementById('statusChart'), {{
  type:'doughnut',
  data:{{ labels:{json.dumps(d["status_labels"])}, datasets:[{{ data:{json.dumps(d["status_values"])}, backgroundColor:{chart_colors}, borderWidth:2 }}] }},
  options:{{ plugins:{{ legend:{{ position:'bottom' }} }}, cutout:'60%' }}
}});

// ── NMs novos ───────────────────────────────────────────────────────
new Chart(document.getElementById('nmsNovosChart'), {{
  type:'line',
  data:{{ labels:{nms_novos_labels}, datasets:[{{ label:'NMs novos', data:{nms_novos_vals}, borderColor:'#dc3545', backgroundColor:'rgba(220,53,69,0.1)', fill:true, tension:0.3, pointRadius:3 }}] }},
  options:{{ responsive:true, plugins:{{ legend:{{ display:false }} }}, scales:{{ x:{{ grid:{{ display:false }} }}, y:{{ beginAtZero:true }} }} }}
}});

// ── Busca por NM ────────────────────────────────────────────────────
const NM_INDEX = {nm_index_js};
const NM_DATA  = {nm_data_js};

let activeFiltro = 'todos';
let activeNm = null;

const searchInput  = document.getElementById('searchInput');
const suggestionBox = document.getElementById('suggestionBox');
const searchResults = document.getElementById('searchResults');
const nmSummary    = document.getElementById('nmSummary');
const nmCards      = document.getElementById('nmCards');
const noResult     = document.getElementById('noResult');
const filterBtns   = document.getElementById('filterBtns');

searchInput.addEventListener('input', function() {{
  const q = this.value.trim().toLowerCase();
  suggestionBox.innerHTML = '';
  if (q.length < 2) {{ suggestionBox.style.display='none'; return; }}
  const matches = NM_INDEX.filter(x => x.nm.includes(q) || x.n.toLowerCase().includes(q)).slice(0,15);
  if (!matches.length) {{ suggestionBox.style.display='none'; return; }}
  suggestionBox.style.display = 'block';
  matches.forEach(x => {{
    const div = document.createElement('div');
    div.className = 'nm-suggestion';
    div.innerHTML = `<span class="font-monospace text-purple fw-semibold">${{x.nm}}</span>
      <span class="ms-2">${{x.n.slice(0,70)}}</span>
      <span class="ms-2 badge bg-secondary">${{x.oc}}x</span>
      ${{x.ab ? `<span class="badge bg-success ms-1">${{x.ab}} aberto(s)</span>` : ''}}`;
    div.onclick = () => selectNm(x);
    suggestionBox.appendChild(div);
  }});
}});

document.addEventListener('click', e => {{ if (!e.target.closest('.search-wrap')) suggestionBox.style.display='none'; }});

function selectNm(x) {{
  activeNm = x.nm;
  searchInput.value = x.nm + ' — ' + x.n;
  suggestionBox.style.display = 'none';
  activeFiltro = 'todos';
  document.querySelectorAll('#filterBtns .btn').forEach(b => b.classList.remove('active'));
  document.querySelector('#filterBtns .btn').classList.add('active');
  filterBtns.style.display = '';
  renderNm(x);
}}

function filtrarResultado(tipo, btn) {{
  activeFiltro = tipo;
  document.querySelectorAll('#filterBtns .btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const x = NM_INDEX.find(i => i.nm === activeNm);
  if (x) renderNm(x);
}}

function renderNm(x) {{
  noResult.style.display = 'none';
  searchResults.innerHTML = '';

  const data = NM_DATA[x.nm];
  const hoje = new Date();
  const umAnoAtras = new Date(hoje.getFullYear()-1, hoje.getMonth(), hoje.getDate());

  // Cards de resumo
  nmSummary.style.display = 'block';
  const cidades = [...new Set(x.ci.filter(Boolean))];
  nmCards.innerHTML = `
    <div class="card border-purple px-3 py-2">
      <div class="text-muted small">NM</div>
      <div class="fw-bold font-monospace" style="color:#6f42c1">${{x.nm}}</div>
    </div>
    <div class="card border-0 bg-light px-3 py-2">
      <div class="text-muted small">Aparições totais</div>
      <div class="fw-bold fs-5">${{x.oc}}x</div>
    </div>
    ${{x.ab ? `<div class="card border-success px-3 py-2">
      <div class="text-muted small">Em aberto</div>
      <div class="fw-bold fs-5 text-success">${{x.ab}}</div>
    </div>` : ''}}
    <div class="card border-0 bg-light px-3 py-2">
      <div class="text-muted small">Cidades</div>
      <div class="small">${{cidades.slice(0,5).join(', ') || '—'}}</div>
    </div>
  `;

  if (!data) {{
    searchResults.innerHTML = '<div class="text-muted small mt-2">Sem propostas disponíveis para este NM.</div>';
    return;
  }}

  // Filtra leilões
  let leiloes = data.l;
  if (activeFiltro === 'ano') {{
    leiloes = leiloes.filter(l => {{
      if (!l.dt) return false;
      const parts = l.dt.split('/');
      if (parts.length !== 3) return true;
      const d = new Date(parts[2], parts[1]-1, parts[0]);
      return d >= umAnoAtras;
    }});
  }}

  if (!leiloes.length) {{
    searchResults.innerHTML = '<div class="text-muted small mt-2">Nenhuma proposta no período selecionado.</div>';
    return;
  }}

  let html = '';
  leiloes.forEach((l, idx) => {{
    let propostas = l.pr;
    if (activeFiltro === 'vencedores') propostas = propostas.filter(p => p.p === 1);

    const vencedor = l.pr.find(p => p.p === 1);
    const nProps = l.pr.length;
    html += `
    <div class="leilao-block">
      <div class="leilao-header" onclick="toggleLeilao('lb${{idx}}')">
        <div>
          <span class="fw-semibold">${{l.dt || '—'}}</span>
          <span class="ms-2 text-muted small">${{l.ci || '—'}}</span>
          <span class="ms-2 badge bg-primary">${{l.qt}} ${{l.un}}</span>
        </div>
        <div class="d-flex align-items-center gap-2">
          ${{vencedor ? `<span class="badge bg-success">${{vencedor.f.slice(0,30)}} · ${{vencedor.vu}}</span>` : ''}}
          <span class="badge bg-secondary">${{nProps}} proposta${{nProps>1?'s':''}}</span>
          <span class="text-muted small" id="arr${{idx}}">▼</span>
        </div>
      </div>
      <div id="lb${{idx}}" style="display:none">
        <table class="table table-sm proposal-table mb-0">
          <thead class="table-light">
            <tr><th>#</th><th>Fornecedor</th><th>Valor Unitário</th><th>Valor Total</th></tr>
          </thead>
          <tbody>
            ${{propostas.map(p => `
              <tr class="${{p.p===1?'winner-row':''}}">
                <td class="text-center">${{p.p===1?'🥇':p.p}}</td>
                <td class="${{p.p===1?'fw-semibold':''}}">${{p.f}}</td>
                <td class="${{p.p===1?'text-success fw-bold':''}}">${{p.vu}}</td>
                <td class="${{p.p===1?'text-success fw-bold':''}}">${{p.vt}}</td>
              </tr>`).join('')}}
          </tbody>
        </table>
      </div>
    </div>`;
  }});

  searchResults.innerHTML = html;
  // Abre o primeiro automaticamente
  toggleLeilao('lb0');
}}

function toggleLeilao(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  const isOpen = el.style.display !== 'none';
  el.style.display = isOpen ? 'none' : 'block';
  const idx = id.replace('lb','');
  const arr = document.getElementById('arr'+idx);
  if (arr) arr.textContent = isOpen ? '▼' : '▲';
}}
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
