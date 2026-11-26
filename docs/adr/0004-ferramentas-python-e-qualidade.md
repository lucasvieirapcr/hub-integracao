# 0004. Ferramentas Python e de qualidade

- Status: aceito
- Data: 2026-11-26

## Contexto

O código será lido por recrutadores e engenheiros de dados, precisa rodar igual no Windows
(máquina do autor), no Linux (CI) e na VM da nuvem (Fase 6), e a especificação pede Python 3.12
tipado, `ruff`, testes e `sqlfluff` quando possível.

## Decisão

- **Ambiente:** `venv` + `pip` + `pyproject.toml` (padrão da linguagem, sem ferramenta extra).
- **Lint e formatação:** `ruff`, com regras de segurança (`S`), modernização (`UP`), bugs
  comuns (`B`) e nomes (`N`). O comprimento de linha fica a cargo do formatador.
- **Tipagem:** `mypy --strict` com o plugin do Pydantic.
- **Testes:** `pytest`. Os testes de integração (contra os containers) só rodam com a opção
  `--integration`, porque zeram o ERP.
- **Atalhos:** `Makefile`, com receitas que não dependem de shell Unix (no Windows o `make`
  pode usar o `cmd`). A lógica que exigiria shell fica em `scripts/make_tools.py`.
- **sqlfluff:** fora do CI na Fase 1. Avaliar de novo na Fase 3, para o SQL de `stg`, `dw` e
  `analytics`.

## Alternativas consideradas

- **uv ou Poetry:** mais rápidos e com lockfile nativo, mas exigem instalar outra ferramenta
  antes de começar. Para um projeto de portfólio, `pip` reduz o atrito de quem clona.
- **black + flake8 + isort:** três ferramentas para o que o `ruff` faz sozinho.
- **sqlfluff já na Fase 1:** testado com a versão 4.5 (dialeto Oracle). Ele não interpreta
  colunas virtuais (`generated always as (...) virtual`) nem parte do PL/SQL (cursor com
  `FOR UPDATE`/`WHERE CURRENT OF`). Para passar, seria preciso excluir justamente os
  trechos mais importantes. Os scripts do banco são validados pelo próprio Oracle: o
  `setup.sh` falha se qualquer objeto ficar inválido.

## Consequências

- Sem lockfile, versões novas de dependências podem entrar dentro das faixas do
  `pyproject.toml`. O CI pega quebras cedo. Se virar problema, adotar `pip-tools` ou `uv`.
- `mypy --strict` exige anotar tudo. É mais trabalho, mas pega erros antes de rodar e
  documenta o código.
