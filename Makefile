# Receitas compatíveis com o cmd do Windows (sem grep/read).

ifeq ($(OS),Windows_NT)
  BOOTSTRAP_PY ?= py -3.12
  PYTHON := .venv/Scripts/python.exe
else
  BOOTSTRAP_PY ?= python3.12
  PYTHON := .venv/bin/python
endif

COMPOSE := docker compose
DAYS ?= 1
PROFILE ?=
PROFILE_ARG := $(if $(PROFILE),--profile $(PROFILE),)

.DEFAULT_GOAL := help
.PHONY: help install env up down ps logs db-setup utplsql test-plsql seed simulate \
        lint format typecheck test test-integration clean-volumes

help: ## Lista os comandos disponíveis
	@$(BOOTSTRAP_PY) scripts/make_tools.py help

install: ## Cria o .venv (Python 3.12) e instala dependências de desenvolvimento
	$(BOOTSTRAP_PY) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

env: ## Cria/atualiza o .env com segredos aleatórios locais (não sobrescreve valores)
	$(PYTHON) scripts/init_env.py

up: ## Sobe Oracle, SFTP e APIs e espera todos ficarem saudáveis
	$(COMPOSE) up -d --build --wait --wait-timeout 900

down: ## Para os containers (os dados ficam nos volumes)
	$(COMPOSE) down

ps: ## Estado dos containers
	$(COMPOSE) ps

logs: ## Acompanha os logs (Ctrl+C para sair)
	$(COMPOSE) logs -f --tail 100

db-setup: ## Cria/atualiza usuários, tabelas e packages no Oracle (idempotente)
	$(COMPOSE) exec -T oracle bash /opt/hub/database/setup.sh

utplsql: ## Baixa (com verificação SHA-256) e instala o utPLSQL no Oracle
	$(PYTHON) scripts/fetch_utplsql.py
	$(COMPOSE) cp .cache/utPLSQL oracle:/tmp/
	$(COMPOSE) exec -T oracle bash /opt/hub/database/tests/install_utplsql.sh

test-plsql: utplsql ## Roda os testes utPLSQL do ERP
	$(COMPOSE) exec -T oracle bash /opt/hub/database/tests/run_utplsql.sh

seed: db-setup ## Carga histórica do ERP, das APIs e do SFTP (PROFILE=dev|test|benchmark)
	$(PYTHON) -m simulator.cli $(PROFILE_ARG) seed

simulate: ## Simula os próximos dias de operação (DAYS=1)
	$(PYTHON) -m simulator.cli $(PROFILE_ARG) simulate --days $(DAYS)

lint: ## ruff (lint + formatação) e mypy
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy simulator source_systems scripts

format: ## Formata o código com ruff
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

typecheck: ## Só o mypy
	$(PYTHON) -m mypy simulator source_systems scripts

test: ## Testes unitários (pytest)
	$(PYTHON) -m pytest

test-integration: ## Testes contra os containers (ZERA o ERP para o perfil test)
	$(PYTHON) -m pytest -m integration --integration

clean-volumes: ## APAGA todos os dados locais (banco, SFTP, APIs). Pede confirmação.
	@$(BOOTSTRAP_PY) scripts/make_tools.py confirm "Isto apaga TODOS os volumes do projeto." && $(COMPOSE) down -v
