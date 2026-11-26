# Registros de decisão de arquitetura (ADRs)

Cada decisão técnica relevante tem um registro curto: o contexto, o que foi decidido, as
alternativas consideradas e as consequências (inclusive as ruins).

| ADR | Decisão | Fase |
|---|---|---|
| [0001](0001-imagem-oracle.md) | Imagem `gvenzl/oracle-free` (26ai, variante full) para o Oracle local | 1 |
| [0002](0002-nomes-dos-esquemas.md) | Esquemas com prefixo `hub_` | 1 |
| [0003](0003-armazenamento-dos-sistemas-simulados.md) | Cada API simulada guarda seus dados num SQLite próprio | 1 |
| [0004](0004-ferramentas-python-e-qualidade.md) | venv + pip, ruff, mypy estrito, pytest; sqlfluff só na Fase 3 | 1 |
| [0005](0005-carga-historica-e-simulacao-diaria.md) | Histórico em massa (array DML) e dia a dia pelos packages | 1 |

## Modelo

```markdown
# NNNN. Título

- Status: proposto | aceito | substituído por NNNN
- Data: AAAA-MM-DD

## Contexto
## Decisão
## Alternativas consideradas
## Consequências
```
