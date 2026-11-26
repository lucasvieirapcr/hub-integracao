create or replace package test_pkg_order authid definer as
    --%suite(pkg_order: ciclo de vida do pedido)
    --%suitepath(erp)

    --%test(Fluxo completo: criar, confirmar e faturar dá baixa no lote certo)
    procedure full_flow_invoices_by_lot;

    --%test(Cancelar pedido confirmado devolve a reserva)
    procedure cancel_confirmed_releases_stock;

    --%test(Faturar pedido não confirmado gera erro -20201)
    --%throws(-20201)
    procedure invoice_open_order_raises;

    --%test(Confirmar sem estoque mantém o pedido OPEN e grava o erro no log)
    procedure failed_confirmation_is_logged;
end test_pkg_order;
/

create or replace package body test_pkg_order as

    g_wh       number;
    g_product  number;
    g_customer number;
    g_lot      number;

    procedure setup_scenario(p_stock in number) is
    begin
        g_wh := test_fixtures.new_warehouse;
        g_customer := test_fixtures.new_customer(test_fixtures.new_price_table, g_wh);
        g_product := test_fixtures.new_product(12.5);
        g_lot := test_fixtures.new_lot(g_product, 300);
        test_fixtures.put_stock(g_wh, g_lot, p_stock);
    end setup_scenario;

    function order_status(p_order_id in number) return varchar2 is
        l_status orders.status%type;
    begin
        select status into l_status from orders where order_id = p_order_id;
        return l_status;
    end order_status;

    procedure full_flow_invoices_by_lot is
        l_order     number;
        l_invoice   number;
        l_on_hand   number;
        l_reserved  number;
        l_inv_lot   number;
        l_inv_total number;
    begin
        setup_scenario(100);
        l_order := pkg_order.create_order(g_customer, g_wh, 'PHONE');
        pkg_order.add_item(l_order, g_product, 4);
        pkg_order.confirm_order(l_order);
        l_invoice := pkg_order.invoice_order(l_order);

        select qty_on_hand, qty_reserved into l_on_hand, l_reserved
          from stock where warehouse_id = g_wh and lot_id = g_lot;
        select max(lot_id) into l_inv_lot from invoice_items where invoice_id = l_invoice;
        select total_amount into l_inv_total from invoices where invoice_id = l_invoice;

        ut.expect(order_status(l_order)).to_equal('INVOICED');
        ut.expect(l_on_hand).to_equal(96);
        ut.expect(l_reserved).to_equal(0);
        ut.expect(l_inv_lot).to_equal(g_lot);
        ut.expect(l_inv_total).to_equal(50); -- 4 x 12,50 (preço de lista, tabela vazia)
    end full_flow_invoices_by_lot;

    procedure cancel_confirmed_releases_stock is
        l_order    number;
        l_reserved number;
    begin
        setup_scenario(100);
        l_order := pkg_order.create_order(g_customer, g_wh, 'SALES_REP');
        pkg_order.add_item(l_order, g_product, 30);
        pkg_order.confirm_order(l_order);
        pkg_order.cancel_order(l_order);

        select qty_reserved into l_reserved from stock where warehouse_id = g_wh and lot_id = g_lot;
        ut.expect(order_status(l_order)).to_equal('CANCELLED');
        ut.expect(l_reserved).to_equal(0);
    end cancel_confirmed_releases_stock;

    procedure invoice_open_order_raises is
        l_order   number;
        l_invoice number;
    begin
        setup_scenario(100);
        l_order := pkg_order.create_order(g_customer, g_wh, 'PHONE');
        pkg_order.add_item(l_order, g_product, 1);
        l_invoice := pkg_order.invoice_order(l_order);
    end invoice_open_order_raises;

    procedure failed_confirmation_is_logged is
        l_order   number;
        l_started timestamp := sys_extract_utc(systimestamp);
        l_logged  number;
    begin
        setup_scenario(5);
        l_order := pkg_order.create_order(g_customer, g_wh, 'PHONE');
        pkg_order.add_item(l_order, g_product, 10);

        begin
            pkg_order.confirm_order(l_order);
        exception
            when pkg_stock.e_insufficient_stock then
                null;
        end;

        -- gravado em transação autônoma
        select count(*) into l_logged
          from hub_audit.error_log
         where package_name = 'PKG_ORDER'
           and procedure_name = 'CONFIRM_ORDER'
           and parameters = 'order_id=' || l_order
           and error_code = -20101
           and logged_at >= l_started;

        ut.expect(order_status(l_order)).to_equal('OPEN');
        ut.expect(l_logged).to_equal(1);
    end failed_confirmation_is_logged;

end test_pkg_order;
/
