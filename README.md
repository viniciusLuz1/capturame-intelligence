# CapturaME Intelligence

Sistema de inteligência de mercado baseado nos dados da plataforma [CapturaME](https://www.capturame.com.br).

> **Fase atual:** 1 – Login, Descoberta da Estrutura e Preparação da Plataforma

---

## Visão Geral

O CapturaME Intelligence é um sistema modular e escalável projetado para:

- ✅ **Fase 1** – Login, descoberta de APIs internas e mapeamento da plataforma *(atual)*
- 🔜 **Fase 2** – Coleta automatizada de leilões
- 🔜 **Fase 3** – Captura de itens e detecção de reprocessos
- 🔜 **Fase 4** – Inteligência comercial e análise de tendências

---

## Pré-requisitos

- Python 3.12+
- macOS (testado) / Linux compatível
- Acesso à internet
- Conta válida no CapturaME

---

## Instalação

### 1. Clone o repositório

```bash
git clone <repositório>
cd capturame-intelligence
```

### 2. Crie o ambiente virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Instale o Playwright e os navegadores

```bash
playwright install chromium
```

> Instala apenas o Chromium (~150MB). Para instalar todos os navegadores: `playwright install`

---

## Configuração

### 5. Configure o arquivo `.env`

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais:

```env
CAPTURAME_USER=seu_email@exemplo.com
CAPTURAME_PASSWORD=sua_senha_aqui
HEADLESS=false
TIMEOUT=30000
```

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `CAPTURAME_USER` | E-mail ou usuário da conta CapturaME | — |
| `CAPTURAME_PASSWORD` | Senha da conta | — |
| `HEADLESS` | `true` = sem janela, `false` = com janela visível | `false` |
| `TIMEOUT` | Timeout global em milissegundos | `30000` |

> ⚠️ **Nunca** comite o arquivo `.env` no repositório. Ele está no `.gitignore`.

---

## Como Executar

```bash
source venv/bin/activate
python main.py
```

### O que acontece ao executar:

1. 🔐 Verifica se existe sessão salva (`data/auth/storage_state.json`)
2. 🌐 Abre navegador Chromium (com ou sem janela)
3. 🔑 Faz login (ou reutiliza sessão existente)
4. 📸 Salva screenshots em `screenshots/`
5. 📡 Monitora chamadas XHR/Fetch da plataforma
6. 🗺️ Navega pelas seções da plataforma para mapeamento
7. 💾 Salva sessão autenticada para próximas execuções
8. 📊 Gera `reports/discovery_report.md`
9. 📝 Registra tudo em `logs/app.log`

---

## Estrutura do Projeto

```
capturame-intelligence/
│
├── main.py                     # Ponto de entrada – orquestra todo o fluxo
│
├── config/
│   └── config.py               # Configurações centralizadas (URLs, paths, seletores)
│
├── scraper/
│   ├── login.py                # Autenticação e gerenciamento de sessão
│   ├── network_monitor.py      # Interceptação de XHR/Fetch e descoberta de APIs
│   ├── analytics.py            # Geração do relatório de descoberta
│   ├── database.py             # Modelos de dados (preparação Fase 2/3)
│   ├── leiloes.py              # Stub – coleta de leilões (Fase 2)
│   └── itens.py                # Stub – captura de itens (Fase 3)
│
├── data/
│   └── auth/
│       └── storage_state.json  # Sessão autenticada (gerado automaticamente)
│
├── screenshots/                # Screenshots com timestamp
├── logs/
│   ├── app.log                 # Log estruturado da aplicação
│   ├── network/                # Chamadas de rede em JSON
│   └── traces/                 # Traces do Playwright (.zip)
│
├── reports/
│   └── discovery_report.md     # Relatório de descoberta (gerado automaticamente)
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Saídas Geradas

### `reports/discovery_report.md`
Relatório completo contendo:
- URLs visitadas e títulos de página
- Chamadas XHR e Fetch capturadas
- Endpoints JSON identificados
- Candidatos a APIs internas
- Endpoints relacionados a leilões, itens e produtos
- Recomendações para as próximas fases

### `logs/network/*.json`
Cada execução gera um arquivo JSON com todas as requisições de rede capturadas, incluindo URL, método, headers, payload e resposta.

### `screenshots/*.png`
Screenshots automáticos nomeados com timestamp em cada etapa crítica.

### `logs/traces/*.zip`
Traces completos do Playwright para depuração. Visualize em:
```bash
playwright show-trace logs/traces/trace_*.zip
```

---

## Solução de Problemas

### `AuthenticationError: Credenciais não configuradas`
→ Verifique se o arquivo `.env` existe e contém `CAPTURAME_USER` e `CAPTURAME_PASSWORD`.

### `TimeoutError` durante o login
→ Aumente o valor de `TIMEOUT` no `.env` (ex: `60000`)  
→ Tente `HEADLESS=false` para ver o que está acontecendo no navegador.

### Elemento de login não encontrado
→ Abra `https://www.capturame.com.br/login` no navegador  
→ Inspecione os campos do formulário  
→ Atualize os seletores em `config/config.py` > `SELECTORS`

### Sessão expira constantemente
→ Delete `data/auth/storage_state.json` para forçar novo login  
→ Verifique se o site usa autenticação com expiração curta

### `playwright install` falha
```bash
pip install --upgrade playwright
playwright install chromium --with-deps
```

---

## Segurança

- Credenciais lidas **exclusivamente** de variáveis de ambiente
- `storage_state.json` (contém cookies/tokens) está no `.gitignore`
- Headers sensíveis (`Authorization`, `Cookie`) são sanitizados nos logs
- Senhas **nunca** aparecem em logs

---

## Roadmap

| Fase | Descrição | Status |
|------|-----------|--------|
| 1 | Login, descoberta, mapeamento | ✅ **Atual** |
| 2 | Coleta automatizada de leilões | 🔜 Planejado |
| 3 | Captura de itens + detecção de reprocessos | 🔜 Planejado |
| 4 | Inteligência comercial e alertas | 🔜 Planejado |

---

## Licença

Uso interno. Não distribuir.
