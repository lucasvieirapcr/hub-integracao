# 0001. Imagem `gvenzl/oracle-free` (variante full) para o Oracle local

- Status: aceito
- Data: 2026-11-26

## Contexto

O projeto precisa de um Oracle que suba com `docker compose up` numa máquina de 16 GB, rode
PL/SQL, utPLSQL e, na Fase 6, o tipo `VECTOR`. A especificação do projeto cita o "Oracle 23ai". Em outubro
de 2025 a Oracle renomeou essa linha para **Oracle AI Database 26ai**. A numeração técnica
continua 23.x (26ai = release 23.26), e os recursos usados aqui (`VECTOR`, `IF NOT EXISTS`,
`DB_DEVELOPER_ROLE`) estão presentes.

Limites da edição Free (valem para qualquer imagem): até 2 threads de CPU, **2 GB de RAM**
para o banco e 12 GB de dados de usuário. Na prática o container consome de 2,5 a 3 GB.

## Decisão

Usar `gvenzl/oracle-free:23.26.4-full`, com a versão fixada (nada de `latest`).

## Alternativas consideradas

| Opção | Por que não |
|---|---|
| Imagem oficial (`container-registry.oracle.com/database/free`) | Bem maior, primeira subida mais lenta e sem os recursos de conveniência abaixo. |
| `gvenzl/oracle-free` variante **slim** (0,85 GB) | Remove componentes opcionais do banco; risco de faltar algo para o utPLSQL ou para vetores. |
| Variante **faststart** (2,8 GB) | Banco já criado dentro da imagem: sobe em segundos, mas a imagem fica maior. Boa candidata para o CI da Fase 3. |
| Oracle XE 21c | Versão antiga, sem `VECTOR` e sem `IF NOT EXISTS`. |

A imagem do gvenzl é mantida por um funcionário da Oracle, é a mais usada em CI de projetos
Oracle de código aberto e traz `healthcheck.sh` (o `docker compose up --wait` sabe quando o
banco está pronto) e variáveis como `ORACLE_PASSWORD`.

## Consequências

- O primeiro `make up` baixa cerca de 2,2 GB e cria o banco (alguns minutos). As subidas seguintes reaproveitam o volume `oracle-data`.
- Reservar **8 GB para o Docker** (WSL2) cobre o Oracle e as APIs com folga até a Fase 3, quando entra o Airflow.
- Atualizar a versão do banco é uma mudança explícita de tag, revisada em PR.
- Por ser imagem de terceiro, há uma dependência de manutenção. Se for descontinuada, a troca pela oficial afeta só o `docker-compose.yml` e o healthcheck.
