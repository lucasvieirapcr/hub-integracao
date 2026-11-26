create or replace package test_pkg_pricing authid definer as
    --%suite(pkg_pricing: preço por tabela comercial)
    --%suitepath(erp)

    --%test(Usa o preço da tabela do cliente vigente na data)
    procedure uses_price_table_on_date;

    --%test(Sem preço na tabela, usa o preço de lista)
    procedure falls_back_to_list_price;

    --%test(Produto inexistente gera erro -20001)
    --%throws(-20001)
    procedure unknown_product_raises;
end test_pkg_pricing;
/

create or replace package body test_pkg_pricing as

    procedure uses_price_table_on_date is
        l_table    number := test_fixtures.new_price_table(5);
        l_wh       number := test_fixtures.new_warehouse;
        l_customer number := test_fixtures.new_customer(l_table, l_wh);
        l_product  number := test_fixtures.new_product(20);
    begin
        insert into price_table_items (price_table_id, product_id, valid_from, valid_to, unit_price)
        values (l_table, l_product, date '2026-01-01', date '2026-03-31', 18.00);
        insert into price_table_items (price_table_id, product_id, valid_from, valid_to, unit_price)
        values (l_table, l_product, date '2026-04-01', null, 19.00);

        ut.expect(pkg_pricing.get_unit_price(l_customer, l_product, date '2026-03-31')).to_equal(18);
        ut.expect(pkg_pricing.get_unit_price(l_customer, l_product, date '2026-04-01')).to_equal(19);
    end uses_price_table_on_date;

    procedure falls_back_to_list_price is
        l_table    number := test_fixtures.new_price_table;
        l_wh       number := test_fixtures.new_warehouse;
        l_customer number := test_fixtures.new_customer(l_table, l_wh);
        l_product  number := test_fixtures.new_product(42.50);
    begin
        ut.expect(pkg_pricing.get_unit_price(l_customer, l_product, date '2026-05-10')).to_equal(42.5);
    end falls_back_to_list_price;

    procedure unknown_product_raises is
        l_table    number := test_fixtures.new_price_table;
        l_wh       number := test_fixtures.new_warehouse;
        l_customer number := test_fixtures.new_customer(l_table, l_wh);
        l_price    number;
    begin
        l_price := pkg_pricing.get_unit_price(l_customer, -1);
    end unknown_product_raises;

end test_pkg_pricing;
/
