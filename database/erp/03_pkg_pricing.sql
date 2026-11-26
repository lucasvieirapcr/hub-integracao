create or replace package pkg_pricing authid definer as
    e_product_not_found exception;
    pragma exception_init(e_product_not_found, -20001);
    e_customer_not_found exception;
    pragma exception_init(e_customer_not_found, -20002);

    -- Preço da tabela do cliente vigente na data; sem preço na tabela, usa o de lista.
    function get_unit_price(
        p_customer_id in customers.customer_id%type,
        p_product_id  in products.product_id%type,
        p_on_date     in date default trunc(sysdate)
    ) return number;
end pkg_pricing;
/

create or replace package body pkg_pricing as

    c_package constant varchar2(30) := 'PKG_PRICING';

    function get_unit_price(
        p_customer_id in customers.customer_id%type,
        p_product_id  in products.product_id%type,
        p_on_date     in date default trunc(sysdate)
    ) return number is
        l_price_table_id customers.price_table_id%type;
        l_list_price     products.list_price%type;
        l_table_price    price_table_items.unit_price%type;
    begin
        begin
            select price_table_id into l_price_table_id from customers where customer_id = p_customer_id;
        exception
            when no_data_found then
                raise_application_error(-20002, 'Cliente não encontrado: ' || p_customer_id);
        end;

        begin
            select list_price into l_list_price from products where product_id = p_product_id;
        exception
            when no_data_found then
                raise_application_error(-20001, 'Produto não encontrado: ' || p_product_id);
        end;

        -- vigência mais recente; NULL se não houver
        select max(unit_price) keep (dense_rank last order by valid_from)
          into l_table_price
          from price_table_items
         where price_table_id = l_price_table_id
           and product_id = p_product_id
           and valid_from <= p_on_date
           and (valid_to is null or valid_to >= p_on_date);

        return coalesce(l_table_price, l_list_price);
    exception
        when others then
            hub_audit.pkg_error_log.log_error(
                c_package, 'GET_UNIT_PRICE',
                'customer_id=' || p_customer_id || ', product_id=' || p_product_id
                    || ', on_date=' || to_char(p_on_date, 'YYYY-MM-DD'),
                sqlcode, sqlerrm
            );
            raise;
    end get_unit_price;

end pkg_pricing;
/
