# 0005. Histórico em massa (array DML) e dia a dia pelos packages

- Status: aceito
- Data: 2026-11-26

## Contexto

O ERP precisa de histórico volumoso (cerca de 40 mil pedidos no perfil `dev` e alguns milhões
no `benchmark`) e, ao mesmo tempo, as regras de negócio em PL/SQL (preço por tabela, reserva
FEFO, faturamento por lote) precisam ser exercitadas de verdade. Chamar `create_order`,
`add_item`, `confirm_order` e `invoice_order` para cada pedido histórico significa várias
idas e voltas ao banco por pedido: horas no perfil `benchmark`.

Também é exigência do projeto que tudo seja reprodutível (seed fixa) e idempotente.

## Decisão

1. **Histórico (`make seed`):** o simulador calcula pedidos, preços e lotes em Python, com as
   mesmas regras dos packages, e grava em massa com `executemany` (array DML: milhares de
   linhas por ida ao banco). A carga começa com `pkg_admin.reset_data` e termina com
   `pkg_admin.sync_identities`. Rodar de novo produz exatamente o mesmo banco.
2. **Dia a dia (`make simulate`):** cada pedido passa pelos packages, então pode faltar
   estoque, o erro vai para `hub_audit.error_log` e o pedido é cancelado. O dia simulado é
   gravado em `erp.sim_runs` na mesma transação: repetir o comando não duplica nada.
3. **Determinismo por dia:** cada fluxo (pedidos do ERP, pedidos B2B, CRM, arquivo do
   fornecedor) tem um gerador derivado de `seed + nome do fluxo + data`. O dia X gera sempre
   o mesmo resultado, independentemente de quais dias foram gerados antes.

## Alternativas consideradas

- **Tudo pelos packages:** fiel, mas lento demais para milhões de pedidos.
- **Gerar o histórico dentro do Oracle (PL/SQL com `DBMS_RANDOM`):** rápido, mas duplicaria
  a lógica de geração em duas linguagens e dificultaria manter a mesma seed para o ERP, a
  loja e o gateway.
- **`SQL*Loader` / tabelas externas:** ótimos para cargas de arquivos, mas exigiriam
  gerar arquivos intermediários e copiá-los para o container.

## Consequências

- O histórico não tem `stock_movements` (o saldo inicial é uma fotografia no fim do
  histórico). Os movimentos existem a partir do primeiro dia simulado.
- As regras de preço e FEFO existem em dois lugares (Python para o histórico, PL/SQL para o
  dia a dia). Os testes de integração conferem que o dia simulado respeita a validade mínima
  e que nota e pedido batem. Se as regras divergirem, um teste falha.
- Pedidos B2B pagos aparecem na loja e no ERP (canal `B2B`, `external_order_ref`): é a
  duplicidade entre origens que o `dw` vai precisar resolver.
