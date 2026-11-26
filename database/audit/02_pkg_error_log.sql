create or replace package pkg_error_log authid definer as
    -- Grava o erro em transação autônoma. Uso:
    --   hub_audit.pkg_error_log.log_error('PKG_X', 'PROC_Y', 'id=' || p_id, sqlcode, sqlerrm);
    --   raise;
    procedure log_error(
        p_package_name   in varchar2,
        p_procedure_name in varchar2,
        p_parameters     in varchar2,
        p_error_code     in number,
        p_error_message  in varchar2
    );
end pkg_error_log;
/

create or replace package body pkg_error_log as

    procedure log_error(
        p_package_name   in varchar2,
        p_procedure_name in varchar2,
        p_parameters     in varchar2,
        p_error_code     in number,
        p_error_message  in varchar2
    ) is
        pragma autonomous_transaction;
    begin
        insert into error_log (
            package_name, procedure_name, parameters,
            error_code, error_message, error_backtrace, call_stack
        ) values (
            substr(p_package_name, 1, 128),
            substr(p_procedure_name, 1, 128),
            substr(p_parameters, 1, 4000),
            p_error_code,
            substr(p_error_message, 1, 4000),
            substr(dbms_utility.format_error_backtrace, 1, 4000),
            substr(dbms_utility.format_call_stack, 1, 4000)
        );
        commit;
    exception
        when others then
            -- não mascarar o erro original do chamador
            rollback;
    end log_error;

end pkg_error_log;
/
