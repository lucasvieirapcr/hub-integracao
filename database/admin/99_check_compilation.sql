-- Falha o setup se algum objeto ficou INVALID (erro de compilação gera só aviso).
column owner format a10
column name format a30
column text format a80
select owner, name, type, line, position, text
  from dba_errors
 where owner in ('ERP', 'HUB_AUDIT')
 order by owner, name, type, sequence;

declare
    l_invalid pls_integer;
begin
    select count(*)
      into l_invalid
      from dba_objects
     where owner in ('ERP', 'HUB_AUDIT')
       and status = 'INVALID';
    if l_invalid > 0 then
        raise_application_error(-20999, l_invalid || ' objeto(s) inválido(s); veja a lista acima');
    end if;
end;
/
