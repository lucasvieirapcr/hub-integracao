-- Usuários/esquemas do projeto. Prefixo hub_: ver docs/adr/0002-nomes-dos-esquemas.md.

create user if not exists erp identified by "&erp_password"
    default tablespace users quota unlimited on users;
alter user erp identified by "&erp_password";
grant db_developer_role to erp;

create user if not exists hub_audit identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_audit identified by "&hub_password";
grant db_developer_role to hub_audit;

create user if not exists hub_raw identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_raw identified by "&hub_password";
grant db_developer_role to hub_raw;

create user if not exists hub_int identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_int identified by "&hub_password";
grant db_developer_role to hub_int;

create user if not exists hub_stg identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_stg identified by "&hub_password";
grant db_developer_role to hub_stg;

create user if not exists hub_dw identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_dw identified by "&hub_password";
grant db_developer_role to hub_dw;

create user if not exists hub_ops identified by "&hub_password"
    default tablespace users quota unlimited on users;
alter user hub_ops identified by "&hub_password";
grant db_developer_role to hub_ops;
