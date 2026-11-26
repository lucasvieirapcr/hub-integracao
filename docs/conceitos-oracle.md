# Conceitos de Oracle e PL/SQL usados no projeto

Guia de estudo: cada conceito aparece aqui na primeira vez em que é usado no código, com o
porquê e onde encontrá-lo.

## Fase 1

### Esquema = usuário
No Oracle, criar o usuário `erp` cria também o esquema `erp`, o "dono" das tabelas
(`erp.orders`). Separar camadas em esquemas permite dar a cada processo só o acesso de que
ele precisa. Arquivo: `database/admin/01_users.sql`.

### CDB e PDB
O Oracle moderno é um contêiner (CDB, chamado `FREE`) com bancos plugáveis dentro (PDB,
chamado `FREEPDB1`). Os dados da aplicação ficam no PDB; por isso o `setup.sh` faz
`alter session set container = FREEPDB1` e as conexões usam o serviço `FREEPDB1`.

### `DB_DEVELOPER_ROLE`
Papel criado no 23ai/26ai com os privilégios típicos de desenvolvimento (criar tabelas,
views, packages, tipos), sem poderes de administrador. Substitui a lista manual de `GRANT`s.

### `IF NOT EXISTS`
`create table if not exists` (23ai/26ai) deixa o script reexecutável: na segunda vez, o
Oracle simplesmente não faz nada. Atenção: se a tabela já existe com outra estrutura, ela
**não** é alterada.

### Coluna virtual
`line_amount ... generated always as (round(quantity * unit_price, 2)) virtual` não ocupa
espaço: é calculada na leitura e nunca fica dessincronizada de quantidade e preço.
Arquivo: `database/erp/01_tables.sql`.

### Package (especificação + corpo)
Um package agrupa procedimentos relacionados.
- A **especificação** (`create package`) é o contrato público: o que pode ser chamado,
  constantes e exceções.
- O **corpo** (`create package body`) é a implementação, inclusive rotinas privadas.

Quem chama depende só da especificação: dá para mudar o corpo sem invalidar os
chamadores. Também é possível esconder detalhes (as funções `lock_order` e
`require_status` do `pkg_order` não existem fora dele). Arquivos: `database/erp/0*_pkg_*.sql`.

### `%TYPE` e `%ROWTYPE`
`l_price customers.price_table_id%type` declara a variável com o tipo da coluna. Se a
coluna mudar de `NUMBER(10)` para `NUMBER(12)`, o código acompanha sem edição.
`orders%rowtype` é um registro com todas as colunas da tabela.

### Exceções nomeadas e `RAISE_APPLICATION_ERROR`
Erros de negócio usam códigos de -20000 a -20999. `pragma exception_init(e_insufficient_stock,
-20101)` dá um nome ao código, e quem chama pode escrever
`when pkg_stock.e_insufficient_stock then` em vez de comparar números.

| Código | Exceção | Significado |
|---|---|---|
| -20001 / -20002 | `pkg_pricing.e_product_not_found` / `e_customer_not_found` | cadastro inexistente |
| -20101 | `pkg_stock.e_insufficient_stock` | estoque insuficiente para a reserva |
| -20102 | `pkg_stock.e_invalid_quantity` | quantidade nula, zero, negativa ou fracionada |
| -20201 | `pkg_order.e_invalid_status` | operação não permitida no status atual |
| -20202 | `pkg_order.e_empty_order` | confirmar pedido sem itens |
| -20203 | `pkg_order.e_order_not_found` | pedido inexistente |

### `SAVEPOINT` e `ROLLBACK TO`
Os packages **não fazem COMMIT**: quem chama decide quando confirmar. Cada procedimento marca
um ponto de salvamento no início e, se der erro, desfaz só o próprio trabalho
(`rollback to sp_confirm_order`), sem apagar o que o chamador fez antes.

### Transação autônoma (`pragma autonomous_transaction`)
O `pkg_error_log.log_error` roda numa transação independente e faz `commit` só do log. Se o
pedido der erro e for desfeito, o registro do erro continua gravado. Sem isso, o rollback
apagaria a prova do problema. Arquivo: `database/audit/02_pkg_error_log.sql`.

### `DBMS_UTILITY.FORMAT_ERROR_BACKTRACE`
Devolve a linha exata onde o erro nasceu, mesmo depois de passar por vários `raise`.
`SQLERRM` diz o quê; o backtrace diz onde.

### `SELECT ... FOR UPDATE` e `WHERE CURRENT OF`
A reserva FEFO lê os saldos com `for update`, que trava essas linhas até o fim da transação.
Dois pedidos disputando o mesmo lote não reservam a mesma unidade: o segundo espera o
primeiro terminar. `where current of c_lots` atualiza exatamente a linha que o cursor acabou
de ler. Arquivo: `database/erp/04_pkg_stock.sql`.

### FEFO
*First expired, first out*: sai primeiro o lote que vence primeiro, ignorando lotes com
menos de 30 dias de validade. Reduz perda por vencimento, uma exigência de boas práticas
de distribuição.

### `MERGE`
"Atualiza se existe, insere se não existe" num único comando atômico. Na Fase 1 aparece em
`receive_stock` (cria ou soma saldo) e em `release_order`/`ship_order` (atualiza vários
saldos de uma vez, em vez de um loop). Na Fase 3 é a base da sincronização `stg` → `dw`.

### `MAX(...) KEEP (DENSE_RANK LAST ORDER BY ...)`
"O valor da linha mais recente." Em `pkg_pricing`, pega o preço da vigência mais nova.
Como é uma agregação, devolve `NULL` (e não erro) quando não há linha.

### `DBMS_ASSERT`
Valida nomes usados em SQL dinâmico (`execute immediate 'truncate table ' || nome`),
protegendo contra injeção de SQL. Arquivo: `database/erp/02_pkg_admin.sql`.

### `IDENTITY ... START WITH LIMIT VALUE`
Depois de inserir IDs explícitos (carga histórica), faz a identidade continuar do maior valor
existente, evitando colisão de chave na próxima inserção pelo package.

### Array DML (`executemany`)
Do lado Python: o `python-oracledb` envia milhares de linhas numa única ida ao banco. É o
equivalente, no cliente, ao `FORALL` do PL/SQL (que aparece na Fase 3).
