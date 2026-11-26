#!/usr/bin/env bash
# Cria/atualiza usuários, tabelas e packages. Roda dentro do container (make db-setup).
set -euo pipefail

: "${ERP_DB_PASSWORD:?defina ERP_DB_PASSWORD no .env}"
: "${HUB_DB_PASSWORD:?defina HUB_DB_PASSWORD no .env}"
DB_DIR="${HUB_DB_DIR:-/opt/hub/database}"
PDB="${ORACLE_PDB:-FREEPDB1}"

cd "$DB_DIR"

sqlplus -s -L / as sysdba <<SQL
whenever sqlerror exit failure rollback
whenever oserror exit failure
set define on verify off feedback off sqlblanklines on serveroutput on
alter session set container = ${PDB};

define erp_password = "${ERP_DB_PASSWORD}"
define hub_password = "${HUB_DB_PASSWORD}"

prompt == Usuários e esquemas
@admin/01_users.sql

prompt == hub_audit: log de erros
alter session set current_schema = hub_audit;
@audit/01_error_log.sql
@audit/02_pkg_error_log.sql

alter session set current_schema = sys;
@admin/02_grants.sql

prompt == erp: tabelas e packages
alter session set current_schema = erp;
@erp/01_tables.sql
@erp/02_pkg_admin.sql
@erp/03_pkg_pricing.sql
@erp/04_pkg_stock.sql
@erp/05_pkg_order.sql

alter session set current_schema = sys;
prompt == Verificando compilação
@admin/99_check_compilation.sql
prompt == Setup concluído
exit
SQL
