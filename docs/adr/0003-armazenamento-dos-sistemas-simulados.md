# 0003. Cada API simulada guarda seus dados num SQLite próprio

- Status: aceito
- Data: 2026-11-26

## Contexto

A loja B2B, o CRM e o gateway de pagamento são sistemas de terceiros. O hub só deve
enxergá-los pelas APIs e webhooks, como aconteceria num cliente real. As APIs precisam
guardar estado (pedidos, clientes, pagamentos, outbox de webhooks), suportar paginação por
cursor sobre dezenas de milhares de registros e consumir pouca memória, porque o Oracle já
ocupa a maior parte.

## Decisão

Cada API usa um arquivo **SQLite** próprio, num volume Docker separado (`b2b-data`,
`crm-data`, `payments-data`). O acesso é pela biblioteca padrão `sqlite3`, em modo WAL, sem
ORM.

## Alternativas consideradas

| Opção | Por que não |
|---|---|
| Esquemas no próprio Oracle (`b2b`, `crm`) | Tentaria "integrar" lendo direto do banco da origem, o atalho que o projeto quer evitar. Também acopla a disponibilidade das APIs à do Oracle. |
| PostgreSQL num container | Funciona, mas é mais um serviço consumindo memória para guardar poucos dados. |
| Memória (dicionários Python) | Perde tudo ao reiniciar o container e não reproduz problemas reais de persistência. |

## Consequências

- Isolamento real: derrubar o Oracle não derruba as APIs, e vice-versa.
- Custo de memória desprezível (cerca de 100 MB por API).
- O SQLite aceita um escritor por vez. Para o volume de escrita do simulador isso é mais do
  que suficiente, mas não serviria para uma API de produção com alta concorrência.
- Valores monetários ficam em **centavos (inteiros)** nas APIs e em `NUMBER(…, 2)` no ERP.
  A diferença é proposital: na Fase 2 a integração precisa converter representações
  diferentes, como acontece de verdade.
