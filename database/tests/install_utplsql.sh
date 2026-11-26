#!/usr/bin/env bash
# Instala o utPLSQL no esquema UT3. O fonte é copiado para /tmp/utPLSQL por `make utplsql`.
set -euo pipefail

: "${UT3_PASSWORD:?defina UT3_PASSWORD no .env}"
PDB="${ORACLE_PDB:-FREEPDB1}"
SRC=/tmp/utPLSQL/source

installed=$(sqlplus -s -L / as sysdba <<SQL
set heading off feedback off pagesize 0
alter session set container = ${PDB};
select count(*) from dba_users where username = 'UT3';
exit
SQL
)
if [[ "$(echo "$installed" | tr -d '[:space:]')" == "1" ]]; then
    echo "utPLSQL já instalado (esquema UT3)."
    exit 0
fi

cd "$SRC"
sqlplus -s -L / as sysdba <<SQL
whenever sqlerror exit failure
alter session set container = ${PDB};
@install_headless.sql ut3 "${UT3_PASSWORD}" users
exit
SQL
echo "utPLSQL instalado."
