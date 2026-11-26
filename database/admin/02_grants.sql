-- O ERP grava erros só pelo package (sem acesso direto à tabela).
grant execute on hub_audit.pkg_error_log to erp;
