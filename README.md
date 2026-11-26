# Hub de Integração · Distribuidora Exemplo

> **Projeto educacional e de portfólio.** A "Distribuidora Exemplo" e todos os seus dados são
> fictícios; os sistemas de origem são simulados. As únicas fontes externas são APIs
> públicas, usadas dentro de seus limites.

Camada de integração, automação e estruturação de dados para uma distribuidora de
medicamentos cujos sistemas não conversam: ERP em Oracle com regras em PL/SQL, loja B2B com
API REST, CRM e gateway de pagamento que enviam webhooks e um fornecedor legado que manda CSV
por SFTP. O projeto é apresentado como uma entrega de consultoria: problema, diagnóstico,
arquitetura, implementação, resultados medidos e documentação para operação.

## Andamento

| Fase | Conteúdo | Status |
|---|---|---|
| 1 | Fundação e sistemas de origem simulados | ✅ concluída (aguardando validação com Docker) |
| 2 | Integrações (APIs, webhooks, SFTP, APIs públicas) | ⏳ |
| 3 | ELT, PL/SQL e orquestração (Airflow) | ⏳ |
| 4 | Gargalos e otimização com benchmark | ⏳ |
| 5 | Rotinas analíticas e observabilidade | ⏳ |
| 6 | Nuvem, base para IA e acabamento | ⏳ |

## Arquitetura

```
Loja B2B (REST)   CRM (webhooks)   Pagamentos (webhooks)   Fornecedor (SFTP/CSV)   APIs públicas
      │                 │                  │                       │                    │
      ▼                 └──────┬───────────┘                       ▼                    ▼
[api clients]          [webhook receiver]                    [file ingestion]      [public apis]
      └─────────────────────────┴───────────────┬───────────────────┴────────────────────┘
                                                ▼
                     Oracle: hub_raw ──► hub_stg ──► hub_dw (estrela)
                                ▲
                     ERP (erp) ─┘   packages PL/SQL: MERGE, lote, log de erros, auditoria
                                                ▼
                     [analytics] fechamento, conciliação, estoque e validade, relatório
                                                ▼
                     [ai_ready] camada curada, dicionário, linhagem, vetores
[airflow] orquestra tudo | [hub_ops/hub_audit] execuções, qualidade, linhagem ──► Prometheus ──► Grafana
```

Na Fase 1 existem os **sistemas de origem** (a linha de cima e o ERP) e a fundação do banco.

## Mapa vaga × projeto

| Requisito da vaga (Analista de Automação de Dados) | Onde aparece | Status |
|---|---|---|
| Rotinas de automação, pipelines e integrações entre sistemas e APIs | `source_systems/` (APIs com paginação, 429, webhooks HMAC, outbox); `integrations/` e `dags/` | Fase 1 ✅ origens · Fase 2 e 3 |
| ETL/ELT eficiente | Camadas `hub_raw` → `hub_stg` → `hub_dw`, incrementais e reprocessáveis | Fase 3 |
| Consultas e rotinas em bancos relacionais | `database/erp/` (packages de preço, estoque FEFO e pedidos) | Fase 1 ✅ |
| Identificar gargalos e propor soluções escaláveis | `docs/otimizacao.md`, `make benchmark` | Fase 4 |
| Modernização da arquitetura e suporte a IA | `ai_ready/`, dicionário de dados, linhagem, `VECTOR` | Fase 6 |
| Python para dados, automações e APIs | `simulator/` (gerador determinístico, carga em massa), FastAPI | Fase 1 ✅ |
| SQL e PL/SQL | Packages, `MERGE`, `FOR UPDATE`, transação autônoma, testes utPLSQL | Fase 1 ✅ · `BULK COLLECT`/`FORALL` na Fase 3 |
| Cloud | Oracle Cloud Free Tier | Fase 6 |
| Orquestradores | Apache Airflow + ADR comparando Prefect e cron | Fase 3 |
| Git e código limpo | GitHub Actions (ruff, mypy, pytest, build), ADRs, Conventional Commits | Fase 1 ✅ |

## Requisitos

| Item | Mínimo | Observação |
|---|---|---|
| Docker Desktop | 4.x com **WSL2** (Windows) | No Windows: `wsl --install --no-distribution` como administrador e reiniciar |
| Memória para o Docker | **8 GB** | Fase 1 usa ~3,5 GB (Oracle 2,5 a 3 GB + APIs ~300 MB + SFTP). Airflow (Fase 3) soma ~3 a 4 GB |
| Disco | ~10 GB livres | Imagem do Oracle ~2,2 GB + volume de dados |
| Python | 3.12 | |
| GNU Make | 4.x | No Windows: `winget install ezwinports.make` |

O Oracle Free limita o banco a 2 threads de CPU, 2 GB de RAM e 12 GB de dados (ver
[ADR 0001](docs/adr/0001-imagem-oracle.md)). Para limitar a VM do Docker no Windows, crie
`%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
memory=8GB
swap=4GB
```

## Como rodar

```bash
make install      # cria .venv e instala dependências
make env          # cria o .env com senhas e tokens aleatórios (só para uso local)
make up           # sobe Oracle, SFTP e APIs (primeira vez: alguns minutos)
make seed         # cria esquemas e packages e carrega o histórico (perfil dev: ~1 ano)
make simulate     # simula o próximo dia de operação (DAYS=7 para uma semana)
make test-plsql   # instala o utPLSQL e roda os testes do PL/SQL
make help         # todos os comandos
```

Perfis de volume (`PROFILE=` ou `SIM_PROFILE` no `.env`), definidos em
[`simulator/config.yaml`](simulator/config.yaml):

| Perfil | Histórico | Pedidos ERP | Pedidos B2B | Uso |
|---|---|---|---|---|
| `test` | 31 dias | 370 | 137 | testes automatizados |
| `dev` | 1 ano | 40,2 mil (161 mil itens) | 12,6 mil | dia a dia |
| `benchmark` | 2 anos | ~2,3 milhões (~9 milhões de itens) | ~635 mil | Fase 4 |

Os pedidos do ERP incluem os pedidos B2B pagos, que são replicados no ERP para faturamento.

Tudo é determinístico: mesma seed e mesmo perfil geram exatamente os mesmos dados.

## Sistemas de origem (Fase 1)

### ERP em Oracle (esquema `erp`)

Clientes, produtos com lote e validade, estoque por CD e lote, pedidos, itens, reservas por
lote e notas fiscais. As regras ficam em packages PL/SQL:

| Package | Responsabilidade |
|---|---|
| `pkg_pricing` | preço por tabela comercial e vigência (reajuste anual em abril) |
| `pkg_stock` | entrada, **reserva FEFO** com `SELECT ... FOR UPDATE`, liberação e baixa |
| `pkg_order` | ciclo `OPEN → CONFIRMED → INVOICED` (ou `CANCELLED`), nota fiscal por lote |
| `pkg_admin` | uso exclusivo do simulador: recarga determinística |
| `hub_audit.pkg_error_log` | log de erros em **transação autônoma** |

Explicação de cada conceito em [docs/conceitos-oracle.md](docs/conceitos-oracle.md).

### APIs simuladas (FastAPI)

| Sistema | Porta | Rotas | Comportamento |
|---|---|---|---|
| Loja B2B | 8001 | `GET /v1/products`, `/v1/orders`, `/v1/orders/{id}` | Bearer token, paginação por cursor, `updated_since`, **429 + Retry-After** |
| CRM | 8002 | `GET /v1/customers`, `/v1/customers/{code}` | webhooks `customer.created/updated` com HMAC, outbox e retry |
| Pagamentos | 8003 | `GET /v1/payments`, `/v1/payments/{id}` | webhooks `payment.approved/declined/refunded` com HMAC |

Documentação interativa em `http://localhost:800X/docs`. Exemplo:

```bash
curl -H "Authorization: Bearer $B2B_API_TOKEN" "http://localhost:8001/v1/orders?limit=2"
# {"data": [...], "next_cursor": "eyJ1Ijoi..."}  -> repita com ?cursor=... até vir null
```

Webhooks são assinados com `X-Signature: t=<timestamp>,v1=<HMAC-SHA256("<t>.<corpo>")>`.
Enquanto o receptor não existe (Fase 2), os eventos aguardam na outbox de cada sistema.

### Fornecedor legado (SFTP, porta 2222)

Arquivo diário `inbox/fornecedor_AAAAMMDD.csv`: separador `;`, vírgula decimal, datas
`dd/mm/aaaa`, CRLF. O envio grava com nome temporário e renomeia no fim, então quem lê nunca
pega um arquivo pela metade.

### Caos controlado

[`simulator/chaos.yaml`](simulator/chaos.yaml) liga, item a item, lentidão e queda das APIs,
eventos duplicados e fora de ordem, arquivo atrasado, coluna renomeada, encoding errado,
linhas inválidas e pedido pago que não chega ao ERP. Tudo começa **desligado**. Cada problema
injetado é registrado em `data/chaos/<sistema>.jsonl` para avaliar a detecção na Fase 5.

## Testes

| Comando | O que roda |
|---|---|
| `make lint` | ruff (lint e formatação) e mypy estrito |
| `make test` | 41 testes pytest: determinismo, paginação, 429, idempotência, HMAC, retry, caos |
| `make test-plsql` | utPLSQL: FEFO, validade mínima, reserva sem sobra parcial, preço por vigência, ciclo do pedido, log de erros |
| `make test-integration` | contra os containers: seed e simulação idempotentes, regras no banco, APIs, SFTP (**zera o ERP** para o perfil `test`) |

## Estrutura

```
simulator/         geração determinística, carga do ERP, simulação diária, caos, CLI
source_systems/    APIs FastAPI (b2b_store, crm, payments) e peças comuns
database/          setup.sh, usuários, ERP (tabelas e packages), log de erros, testes utPLSQL
scripts/           .env local, download do utPLSQL, apoio ao Makefile
tests/             unit/ e integration/
docs/              adr/, conceitos-oracle.md
```

## Decisões de arquitetura

Ver [docs/adr/](docs/adr/README.md): imagem do Oracle, nomes dos esquemas, armazenamento das
APIs simuladas, ferramentas de qualidade e estratégia de carga do ERP.
