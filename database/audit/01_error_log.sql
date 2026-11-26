-- Log de erros dos packages PL/SQL.
create table if not exists error_log (
    error_id         number generated always as identity,
    logged_at        timestamp(6)   default sys_extract_utc(systimestamp) not null,
    db_user          varchar2(128)  default sys_context('USERENV', 'SESSION_USER') not null,
    package_name     varchar2(128)  not null,
    procedure_name   varchar2(128)  not null,
    parameters       varchar2(4000),
    error_code       number,
    error_message    varchar2(4000),
    error_backtrace  varchar2(4000),
    call_stack       varchar2(4000),
    constraint pk_error_log primary key (error_id)
);

create index if not exists ix_error_log_logged_at on error_log (logged_at);

comment on table error_log is 'Erros capturados nos packages PL/SQL. Gravado por pkg_error_log em transação autônoma.';
comment on column error_log.logged_at is 'Momento do erro (UTC).';
comment on column error_log.parameters is 'Parâmetros da chamada que falhou, no formato nome=valor.';
comment on column error_log.error_code is 'SQLCODE: negativo para erros Oracle; -20000 a -20999 para erros de negócio.';
comment on column error_log.error_backtrace is 'Linha exata onde o erro nasceu (DBMS_UTILITY.FORMAT_ERROR_BACKTRACE).';
comment on column error_log.call_stack is 'Cadeia de chamadas até o log (DBMS_UTILITY.FORMAT_CALL_STACK).';
