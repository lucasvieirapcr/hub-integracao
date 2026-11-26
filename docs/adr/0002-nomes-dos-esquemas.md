# 0002. Esquemas com prefixo `hub_`

- Status: aceito
- Data: 2026-11-26

## Contexto

A especificação do projeto propõe os esquemas `raw`, `int`, `stg`, `dw`, `ops` e `audit`. No Oracle,
esquema é usuário, e o nome do usuário segue as regras de identificador:

- `RAW` e `AUDIT` são **palavras reservadas** (estão na lista de reservadas do SQL do Oracle).
  Só funcionariam entre aspas (`"RAW".tabela`), em todo SQL, para sempre.
- `INT` não é reservada, mas é nome de tipo de dado (sinônimo de `INTEGER`). Funciona,
  porém `int.webhook_inbox` confunde quem lê.

## Decisão

Todos os esquemas do hub ganham o prefixo `hub_`: `hub_raw`, `hub_int`, `hub_stg`,
`hub_dw`, `hub_ops` e `hub_audit`. O ERP, que simula um sistema de origem e não faz parte do
hub, continua `erp`.

## Alternativas consideradas

- **Nomes com aspas** (`"RAW"`): frágil; uma consulta esquecida sem aspas quebra.
- **Renomear só os problemáticos** (`raw_layer`, `audit_log`, `int` mantido): resolve, mas
  deixa a nomenclatura irregular.
- **Sufixo** (`raw_hub`): equivalente, mas o prefixo agrupa os esquemas do projeto quando
  listados em ordem alfabética.

## Consequências

- Nomes previsíveis e sem aspas. O prefixo também separa visualmente o hub (`hub_*`) da
  origem (`erp`).
- Os nomes das tabelas da especificação continuam os mesmos, só o esquema muda (por exemplo,
  `hub_int.webhook_inbox` e `hub_audit.error_log`).
- No ambiente local todos os `hub_*` compartilham uma senha (`HUB_DB_PASSWORD`). Na nuvem
  (Fase 6) cada um terá credencial própria.
