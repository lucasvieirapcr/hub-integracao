#!/usr/bin/env bash
# Compila e roda os testes utPLSQL do ERP. Sai com erro se algum teste falhar.
set -euo pipefail

: "${ERP_DB_PASSWORD:?defina ERP_DB_PASSWORD no .env}"
DB_DIR="${HUB_DB_DIR:-/opt/hub/database}"
PDB="${ORACLE_PDB:-FREEPDB1}"
REPORT=/tmp/utplsql_report.txt

cd "$DB_DIR"

sqlplus -s -L / as sysdba <<SQL
whenever sqlerror exit failure
set feedback off
alter session set container = ${PDB};
grant select on hub_audit.error_log to erp;
exit
SQL

sqlplus -s -L /nolog <<SQL | tee "$REPORT"
whenever sqlerror exit failure
connect erp/"${ERP_DB_PASSWORD}"@//localhost:1521/${PDB}
set define off feedback off sqlblanklines on serveroutput on size unlimited linesize 200
@tests/erp/test_fixtures.sql
@tests/erp/test_pkg_pricing.sql
@tests/erp/test_pkg_stock.sql
@tests/erp/test_pkg_order.sql

declare
    l_invalid pls_integer;
begin
    select count(*) into l_invalid from user_objects where status = 'INVALID';
    if l_invalid > 0 then
        raise_application_error(-20999, l_invalid || ' objeto(s) inválido(s) no esquema ERP');
    end if;
end;
/

exec ut.run('erp', ut_documentation_reporter(), a_color_console => false);
exit
SQL

if grep -Eq '[0-9]+ tests?, 0 failed, 0 errored' "$REPORT"; then
    echo "utPLSQL: todos os testes passaram."
else
    echo "utPLSQL: há testes falhando (veja o relatório acima)." >&2
    exit 1
fi
