-- Fixtures dos testes do ERP (o utPLSQL faz rollback ao fim de cada teste).

create or replace package test_fixtures authid definer as
    function new_price_table(p_discount_pct in number default 0) return number;
    function new_warehouse return number;
    function new_customer(p_price_table_id in number, p_warehouse_id in number) return number;
    function new_product(p_list_price in number default 10) return number;
    function new_lot(p_product_id in number, p_expires_in_days in number) return number;
    procedure put_stock(p_warehouse_id in number, p_lot_id in number, p_qty in number);
end test_fixtures;
/

create or replace package body test_fixtures as

    function unique_suffix return varchar2 is
    begin
        return substr(rawtohex(sys_guid()), 1, 10);
    end unique_suffix;

    function new_price_table(p_discount_pct in number default 0) return number is
        l_id price_tables.price_table_id%type;
    begin
        insert into price_tables (name, discount_pct)
        values ('Teste ' || unique_suffix, p_discount_pct)
        returning price_table_id into l_id;
        return l_id;
    end new_price_table;

    function new_warehouse return number is
        l_id warehouses.warehouse_id%type;
    begin
        insert into warehouses (warehouse_code, name, city_ibge_code, state)
        values ('T' || substr(unique_suffix, 1, 9), 'CD de teste', 3550308, 'SP')
        returning warehouse_id into l_id;
        return l_id;
    end new_warehouse;

    function new_customer(p_price_table_id in number, p_warehouse_id in number) return number is
        l_id customers.customer_id%type;
    begin
        insert into customers (
            customer_code, legal_name, trade_name, cnpj, customer_type,
            city_ibge_code, state, price_table_id, warehouse_id
        ) values (
            'T' || unique_suffix, 'Cliente de Teste Ltda', 'Cliente de Teste', '11222333000181', 'PHARMACY',
            3550308, 'SP', p_price_table_id, p_warehouse_id
        )
        returning customer_id into l_id;
        return l_id;
    end new_customer;

    function new_product(p_list_price in number default 10) return number is
        l_id products.product_id%type;
    begin
        insert into products (
            product_code, description, category, active_ingredient, manufacturer, pack_size, list_price
        ) values (
            'T' || unique_suffix, 'Produto de teste', 'ANALGESICO', 'Teste', 'Fabricante Teste', 10, p_list_price
        )
        returning product_id into l_id;
        return l_id;
    end new_product;

    function new_lot(p_product_id in number, p_expires_in_days in number) return number is
        l_id lots.lot_id%type;
    begin
        insert into lots (product_id, lot_number, manufactured_on, expires_on)
        values (p_product_id, 'T' || unique_suffix, trunc(sysdate) - 400, trunc(sysdate) + p_expires_in_days)
        returning lot_id into l_id;
        return l_id;
    end new_lot;

    procedure put_stock(p_warehouse_id in number, p_lot_id in number, p_qty in number) is
    begin
        insert into stock (warehouse_id, lot_id, qty_on_hand, qty_reserved)
        values (p_warehouse_id, p_lot_id, p_qty, 0);
    end put_stock;

end test_fixtures;
/
