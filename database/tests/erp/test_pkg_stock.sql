create or replace package test_pkg_stock authid definer as
    --%suite(pkg_stock: estoque por lote e reserva FEFO)
    --%suitepath(erp)

    --%test(Reserva consome primeiro o lote que vence primeiro)
    procedure reserve_consumes_earliest_expiry_first;

    --%test(Ignora lotes com validade abaixo da mínima)
    procedure reserve_skips_short_shelf_life;

    --%test(Falta de estoque gera erro -20101 e não deixa reserva parcial)
    procedure insufficient_stock_leaves_no_partial_reservation;

    --%test(Entrada de estoque cria o saldo e depois soma)
    procedure receive_creates_then_adds;

    --%test(Quantidade zero ou negativa gera erro -20102)
    --%throws(-20102)
    procedure invalid_quantity_raises;
end test_pkg_stock;
/

create or replace package body test_pkg_stock as

    g_wh      number;
    g_product number;
    g_order   number;

    procedure setup_order(p_qty in number) is
        l_table    number := test_fixtures.new_price_table;
        l_customer number;
    begin
        g_wh := test_fixtures.new_warehouse;
        g_product := test_fixtures.new_product(10);
        l_customer := test_fixtures.new_customer(l_table, g_wh);
        g_order := pkg_order.create_order(l_customer, g_wh, 'PHONE');
        pkg_order.add_item(g_order, g_product, p_qty);
    end setup_order;

    function reserved_in(p_lot_id in number) return number is
        l_qty number;
    begin
        select qty_reserved into l_qty from stock where warehouse_id = g_wh and lot_id = p_lot_id;
        return l_qty;
    end reserved_in;

    procedure reserve_consumes_earliest_expiry_first is
        l_late  number;
        l_early number;
    begin
        setup_order(8);
        l_late := test_fixtures.new_lot(g_product, 200);
        l_early := test_fixtures.new_lot(g_product, 60);
        test_fixtures.put_stock(g_wh, l_late, 10);
        test_fixtures.put_stock(g_wh, l_early, 5);

        pkg_stock.reserve_fefo(g_order, 1, g_wh, g_product, 8);

        ut.expect(reserved_in(l_early)).to_equal(5);
        ut.expect(reserved_in(l_late)).to_equal(3);
        ut.expect(pkg_stock.available_qty(g_wh, g_product)).to_equal(7);
    end reserve_consumes_earliest_expiry_first;

    procedure reserve_skips_short_shelf_life is
        l_short number;
        l_ok    number;
    begin
        setup_order(4);
        l_short := test_fixtures.new_lot(g_product, pkg_stock.c_min_shelf_life_days - 5);
        l_ok := test_fixtures.new_lot(g_product, 365);
        test_fixtures.put_stock(g_wh, l_short, 100);
        test_fixtures.put_stock(g_wh, l_ok, 10);

        pkg_stock.reserve_fefo(g_order, 1, g_wh, g_product, 4);

        ut.expect(reserved_in(l_short)).to_equal(0);
        ut.expect(reserved_in(l_ok)).to_equal(4);
    end reserve_skips_short_shelf_life;

    procedure insufficient_stock_leaves_no_partial_reservation is
        l_lot      number;
        l_raised   boolean := false;
        l_allocs   number;
    begin
        setup_order(50);
        l_lot := test_fixtures.new_lot(g_product, 200);
        test_fixtures.put_stock(g_wh, l_lot, 10);

        begin
            pkg_stock.reserve_fefo(g_order, 1, g_wh, g_product, 50);
        exception
            when pkg_stock.e_insufficient_stock then
                l_raised := true;
        end;

        select count(*) into l_allocs from order_item_allocations where order_id = g_order;
        ut.expect(l_raised).to_be_true();
        ut.expect(reserved_in(l_lot)).to_equal(0);
        ut.expect(l_allocs).to_equal(0);
    end insufficient_stock_leaves_no_partial_reservation;

    procedure receive_creates_then_adds is
        l_lot number;
        l_qty number;
    begin
        g_wh := test_fixtures.new_warehouse;
        g_product := test_fixtures.new_product;
        l_lot := test_fixtures.new_lot(g_product, 300);

        pkg_stock.receive_stock(g_wh, l_lot, 100);
        pkg_stock.receive_stock(g_wh, l_lot, 50);

        select qty_on_hand into l_qty from stock where warehouse_id = g_wh and lot_id = l_lot;
        ut.expect(l_qty).to_equal(150);
    end receive_creates_then_adds;

    procedure invalid_quantity_raises is
        l_lot number;
    begin
        g_wh := test_fixtures.new_warehouse;
        g_product := test_fixtures.new_product;
        l_lot := test_fixtures.new_lot(g_product, 300);
        pkg_stock.receive_stock(g_wh, l_lot, 0);
    end invalid_quantity_raises;

end test_pkg_stock;
/
