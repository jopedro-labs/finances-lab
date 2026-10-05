# To Do

## Segurança — Ações Imediatas (CRÍTICO)

- [x] Revogar `refresh_token` Google Drive em https://myaccount.google.com/permissions e regenerar credenciais OAuth (`secrets/credentials.json`, `secrets/token.json`)
- [x] Revogar e regenerar a Gemini API Key em Google AI Studio
- [x] Regenerar o Discord Webhook URL (o URL anterior foi exposto)
- [x] Verificar histórico git para garantir que `.env` e `secrets/` nunca foram comitados: `git log --all --full-history -- .env secrets/`
- [x] Restringir scope OAuth de `drive` para `drive.file` em `src/infra/gdrive/auth.py:18`
- [x] Substituir `gemini_api_key`, `discord_webhook_url` e `smtp_password` em `src/config.py` de `str` para `SecretStr` do Pydantic
- [x] Injetar secrets como variáveis de ambiente no `daily-update.yml` em vez de escrever ficheiro `.env` no runner
- [x] Substituir f-strings com `# nosec` em `src/infra/database/finance_sql_extraction.py:82` por allowlist explícita de nomes de colunas
- [x] Adicionar respeito pelo header `Retry-After` no cliente JustETF (`src/infra/justetf/client.py`)
---

## Bugs e Correções

- [ ] **BUG-02** — Corrigir modelo Gemini de `gemini-3.6-flash` para `gemini-2.0-flash` em `src/config.py:31` e `.env.example` — modelo atual não existe e todas as chamadas AI falham
- [ ] **BUG-06** — Adicionar `raise typer.Exit(code=1)` no segundo `except` de `main_callback` em `main.py:110` — exceções não-`ValidationError` silenciadas permitem a app continuar sem configuração válida
- [ ] **BUG-09** — Corrigir crash em `src/cli/projection_presenter.py:24` quando `historical_cagr_pct` é `None` — usar `f"{result.historical_cagr_pct:.2%}" if result.historical_cagr_pct is not None else "N/A"`
- [ ] **BUG-07** — Substituir `Path("data/history.json")` por `DATA_DIR / "history.json"` em `src/core/snapshot.py:195` — path relativo ao CWD falha fora do root do projeto
- [ ] **BUG-04** — Substituir `sqlite3.connect()` manual por `get_db_context()` em `src/infra/database/finance_sql_extraction.py:65` e `:117`
- [ ] **BUG-08** — Remover `conn.commit()` interno de `initialize_database` em `src/infra/database/schema.py:148` — double commit com o context manager externo
- [ ] **BUG-11** — Substituir `__import__("json").dumps(...)` por `json.dumps(...)` em `src/core/repositories.py:494` — anti-padrão e penalidade de performance desnecessária
- [ ] **BUG-12** — Substituir `sqlite3.connect()` manual por `get_db_context()` em `src/cli/quality.py:121`
- [ ] **BUG-03** — Clarificar uso de `peak_price` como `high_52w` em `src/cli/opportunity.py:207` — semanticamente confuso e frágil
- [ ] **BUG-05** — Mover import de `GDriveService` para o topo de `src/core/snapshot.py` e usar `GDriveService` diretamente em vez do alias `GoogleDriveService`
- [x] **QA-07** — Corrigir typo "STATEGY" → "STRATEGY" em `src/cli/opportunity.py:549`

---

## Qualidade de Código e Arquitetura
1. fix/code-quality-minor — QA-07, QA-08, QA-09, QA-10, QA-12, QA-13 (tudo pequeno e seguro)
  2. fix/code-quality-db-patterns — QA-03, QA-04, QA-14 (normalização de DB e JSON loading)
  3. fix/code-quality-architecture — QA-01, QA-02, QA-11, QA-15 (refactoring mais profundo, QA-05 incluído ou separado)

- [x] **QA-01** — Extrair loop de retry com backoff exponencial para método privado `_execute_with_retry` em `src/infra/ai/client.py` — lógica copiada 3 vezes nos métodos `analyze_portfolio_batch`, `analyze_asset`, `analyze_asset_async`
- [x] **QA-02** — Passar `monthly_contribution` como parâmetro em `src/infra/report_generator.py:97` em vez de hardcoded `500.0`
- [x] **QA-03** — Normalizar uso de `get_db_context()` em `src/infra/database/finance_sql_extraction.py` — inconsistência com o resto do projeto
- [x] **QA-04** — Depreciar `calculate_portfolio_exposure` em `src/core/analysis.py` e redirecionar para `ExposureEngine` — lógica duplicada com `src/core/exposure.py`
- [x] **QA-05** — Refatorar `src/config.py` para usar lazy initialization — `Settings` instanciada a nível de módulo dificulta testes e falha no `import`
- [x] **QA-08** — Mover função `_f` para fora do loop em `src/cli/opportunity.py:420` — redefinida em cada iteração desnecessariamente
- [x] **QA-09** — Adicionar comentário explícito em `src/core/snapshot.py:63` onde `provider.get_details(asset)` é chamado apenas pelo side effect de popular o cache
- [x] **QA-10** — Substituir `!= 1.0` por `abs(total_weight - 1.0) > 1e-9` na validação de pesos em `src/config.py:191` e `:225`
- [x] **QA-11** — Substituir logger custom em `src/utils/logger/logger.py` por módulo `logging` standard com Rich handler — ANSI codes hardcoded não funcionam em CI sem TTY
- [x] **QA-12** — Adicionar warning em `src/core/snapshot.py:52` quando portfólio está vazio antes de retornar snapshot vazio
- [x] **QA-13** — Definir `OUTPUT_DIR = BASE_DIR / "output"` em `src/config.py` e substituir todos os `Path("output")` hardcoded em `src/cli/opportunity.py:43`, `src/cli/quality.py:30`, `src/utils/graphics/allocation.py:16`, `src/utils/graphics/portfolio_charts.py:76`
- [x] **QA-14** — Normalizar loading de ficheiros JSON entre `src/cli/quality.py:293` e `src/cli/opportunity.py` — estruturas diferentes aceites inconsistentemente
- [x] **QA-15** — Refatorar `ParquetHistoryRepository.save_snapshot` em `src/core/repositories.py:284` para append incremental em vez de carregar todo o histórico — atualmente O(n) em memória

---

## Novas Funcionalidades

- [ ] **FEAT-01** — Adicionar rate limiting e cache com TTL curto (15-30 min) para chamadas yfinance — reduz latência e aumenta fiabilidade nos comandos `opportunity` e `dashboard`
- [ ] **FEAT-02** — Suporte a múltiplos brokers/contas no portfólio — adicionar campo `broker` ao `Asset`, calcular métricas por conta (complexidade: média)
- [ ] **FEAT-03** — Modo paper trading `--dry-run` no `opportunity_evaluation` — simula buy/sell sem persistir, mostra portfólio hipotético resultante (complexidade: média)
- [ ] **FEAT-04** — Alertas proativos Discord/email quando limites de exposição são violados — o código de validação e notificação já existe, só falta ligar (complexidade: baixa)
- [ ] **FEAT-05** — Guardar histórico de exposição sectorial/geográfica em nova tabela `exposure_history` para visualizar deriva de alocação no dashboard (complexidade: média)
- [ ] **FEAT-06** — Exportação de snapshots e métricas para Google Sheets via API — visualização em tempo real sem gerar HTML (complexidade: média)
- [ ] **FEAT-07** — Cálculo de CGT e simulação fiscal — dado `average_buy_price` e valor atual, calcular ganho de capital e estimar imposto (28% PT) (complexidade: baixa)
- [ ] **FEAT-08** — Suporte a dividendos no cálculo de ROI total return — nova tabela `dividends` e inclusão no cálculo de performance (complexidade: média)
- [ ] **FEAT-09** — Benchmark comparison vs S&P 500 / MSCI World no dashboard e relatório HTML — yfinance já suporta `^GSPC` (complexidade: baixa)
- [ ] **FEAT-10** — Modo `--offline` que usa dados SQLite quando APIs falham — resiliência para job diário em CI/CD (complexidade: baixa)
- [ ] **FEAT-11** — Thresholds de qualidade (Tier A/B/C) configuráveis via `.env` em vez de hardcoded em `src/core/analysis.py:269` (complexidade: baixa)
- [ ] **FEAT-12** — Dado `--invest 1000`, calcular distribuição monetária concreta por asset baseada no gap de alocação e ranking — torna recomendações diretamente acionáveis (complexidade: baixa)