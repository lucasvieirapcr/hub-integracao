-- Ciclo do pedido:
--   OPEN --confirm_order--> CONFIRMED --invoice_order--> INVOICED
--     |                         |
--     +------cancel_order-------+--> CANCELLED
--
-- p_event_at/p_created_at permitem gravar horário simulado (padrão: agora, UTC).

create or replace package pkg_order authid definer as
    e_invalid_status exception;
    pragma exception_init(e_invalid_status, -20201);
    e_empty_order exception;
    pragma exception_init(e_empty_order, -20202);
    e_order_not_found exception;
    pragma exception_init(e_order_not_found, -20203);

    function create_order(
        p_customer_id        in orders.customer_id%type,
        p_warehouse_id       in orders.warehouse_id%type,
        p_channel            in orders.channel%type,
        p_order_date         in orders.order_date%type default trunc(sysdate),
        p_external_order_ref in orders.external_order_ref%type default null,
        p_created_at         in timestamp default sys_extract_utc(systimestamp)
    ) return orders.order_id%type;

    -- p_unit_price nulo = preço da tabela do cliente (pkg_pricing).
    procedure add_item(
        p_order_id   in orders.order_id%type,
        p_product_id in order_items.product_id%type,
        p_quantity   in order_items.quantity%type,
        p_unit_price in order_items.unit_price%type default null,
        p_event_at   in timestamp default sys_extract_utc(systimestamp)
    );

    procedure confirm_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    );

    function invoice_order(
        p_order_id  in orders.order_id%type,
        p_issued_at in timestamp default sys_extract_utc(systimestamp)
    ) return invoices.invoice_id%type;

    procedure cancel_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    );
end pkg_order;
/

create or replace package body pkg_order as

    c_package constant varchar2(30) := 'PKG_ORDER';

    function lock_order(p_order_id in orders.order_id%type) return orders%rowtype is
        l_order orders%rowtype;
    begin
        select * into l_order from orders where order_id = p_order_id for update;
        return l_order;
    exception
        when no_data_found then
            raise_application_error(-20203, 'Pedido não encontrado: ' || p_order_id);
    end lock_order;

    procedure require_status(p_order in orders%rowtype, p_expected in varchar2) is
    begin
        if p_order.status != p_expected then
            raise_application_error(
                -20201,
                'Pedido ' || p_order.order_id || ' está ' || p_order.status || '; esperado ' || p_expected
            );
        end if;
    end require_status;

    function create_order(
        p_customer_id        in orders.customer_id%type,
        p_warehouse_id       in orders.warehouse_id%type,
        p_channel            in orders.channel%type,
        p_order_date         in orders.order_date%type default trunc(sysdate),
        p_external_order_ref in orders.external_order_ref%type default null,
        p_created_at         in timestamp default sys_extract_utc(systimestamp)
    ) return orders.order_id%type is
        l_order_id orders.order_id%type;
    begin
        insert into orders (
            customer_id, warehouse_id, channel, external_order_ref, order_date,
            status, total_amount, created_at, updated_at
        ) values (
            p_customer_id, p_warehouse_id, p_channel, p_external_order_ref, p_order_date,
            'OPEN', 0, p_created_at, p_created_at
        )
        returning order_id into l_order_id;
        return l_order_id;
    exception
        when others then
            hub_audit.pkg_error_log.log_error(
                c_package, 'CREATE_ORDER',
                'customer_id=' || p_customer_id || ', warehouse_id=' || p_warehouse_id || ', channel=' || p_channel
                    || ', external_order_ref=' || p_external_order_ref,
                sqlcode, sqlerrm
            );
            raise;
    end create_order;

    procedure add_item(
        p_order_id   in orders.order_id%type,
        p_product_id in order_items.product_id%type,
        p_quantity   in order_items.quantity%type,
        p_unit_price in order_items.unit_price%type default null,
        p_event_at   in timestamp default sys_extract_utc(systimestamp)
    ) is
        l_order       orders%rowtype;
        l_line_number order_items.line_number%type;
        l_unit_price  order_items.unit_price%type;
    begin
        savepoint sp_add_item;
        if p_quantity is null or p_quantity <= 0 then
            raise_application_error(-20102, 'Quantidade inválida: ' || nvl(to_char(p_quantity), 'NULL'));
        end if;

        l_order := lock_order(p_order_id);
        require_status(l_order, 'OPEN');

        -- NVL avaliaria get_unit_price mesmo com preço informado
        if p_unit_price is not null then
            l_unit_price := p_unit_price;
        else
            l_unit_price := pkg_pricing.get_unit_price(l_order.customer_id, p_product_id, l_order.order_date);
        end if;

        select nvl(max(line_number), 0) + 1 into l_line_number from order_items where order_id = p_order_id;

        insert into order_items (order_id, line_number, product_id, quantity, unit_price)
        values (p_order_id, l_line_number, p_product_id, p_quantity, l_unit_price);

        update orders
           set total_amount = total_amount + round(p_quantity * l_unit_price, 2),
               updated_at = p_event_at
         where order_id = p_order_id;
    exception
        when others then
            rollback to sp_add_item;
            hub_audit.pkg_error_log.log_error(
                c_package, 'ADD_ITEM',
                'order_id=' || p_order_id || ', product_id=' || p_product_id || ', quantity=' || p_quantity
                    || ', unit_price=' || p_unit_price,
                sqlcode, sqlerrm
            );
            raise;
    end add_item;

    procedure confirm_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    ) is
        l_order orders%rowtype;
        l_items pls_integer;
    begin
        savepoint sp_confirm_order;
        l_order := lock_order(p_order_id);
        require_status(l_order, 'OPEN');

        select count(*) into l_items from order_items where order_id = p_order_id;
        if l_items = 0 then
            raise_application_error(-20202, 'Pedido sem itens: ' || p_order_id);
        end if;

        for r in (
            select line_number, product_id, quantity
              from order_items
             where order_id = p_order_id
             order by line_number
        ) loop
            pkg_stock.reserve_fefo(
                p_order_id     => p_order_id,
                p_line_number  => r.line_number,
                p_warehouse_id => l_order.warehouse_id,
                p_product_id   => r.product_id,
                p_quantity     => r.quantity,
                p_on_date      => l_order.order_date,
                p_event_at     => p_event_at
            );
        end loop;

        update orders set status = 'CONFIRMED', updated_at = p_event_at where order_id = p_order_id;
    exception
        when others then
            rollback to sp_confirm_order;
            hub_audit.pkg_error_log.log_error(c_package, 'CONFIRM_ORDER', 'order_id=' || p_order_id, sqlcode, sqlerrm);
            raise;
    end confirm_order;

    function invoice_order(
        p_order_id  in orders.order_id%type,
        p_issued_at in timestamp default sys_extract_utc(systimestamp)
    ) return invoices.invoice_id%type is
        l_order      orders%rowtype;
        l_invoice_id invoices.invoice_id%type;
    begin
        savepoint sp_invoice_order;
        l_order := lock_order(p_order_id);
        require_status(l_order, 'CONFIRMED');

        insert into invoices (invoice_number, order_id, issued_at, total_amount, status, created_at, updated_at)
        values (invoice_number_seq.nextval, p_order_id, p_issued_at, 0, 'ISSUED', p_issued_at, p_issued_at)
        returning invoice_id into l_invoice_id;

        -- uma linha por lote reservado
        insert into invoice_items (invoice_id, line_number, product_id, lot_id, quantity, unit_price)
        select l_invoice_id,
               row_number() over (order by a.line_number, a.lot_id),
               oi.product_id,
               a.lot_id,
               a.quantity,
               oi.unit_price
          from order_item_allocations a
          join order_items oi on oi.order_id = a.order_id and oi.line_number = a.line_number
         where a.order_id = p_order_id;

        update invoices
           set total_amount = (select sum(line_amount) from invoice_items where invoice_id = l_invoice_id)
         where invoice_id = l_invoice_id;

        pkg_stock.ship_order(p_order_id, p_issued_at);

        update orders set status = 'INVOICED', updated_at = p_issued_at where order_id = p_order_id;
        return l_invoice_id;
    exception
        when others then
            rollback to sp_invoice_order;
            hub_audit.pkg_error_log.log_error(c_package, 'INVOICE_ORDER', 'order_id=' || p_order_id, sqlcode, sqlerrm);
            raise;
    end invoice_order;

    procedure cancel_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    ) is
        l_order orders%rowtype;
    begin
        savepoint sp_cancel_order;
        l_order := lock_order(p_order_id);

        if l_order.status = 'CONFIRMED' then
            pkg_stock.release_order(p_order_id, p_event_at);
        elsif l_order.status != 'OPEN' then
            raise_application_error(
                -20201,
                'Só pedidos OPEN ou CONFIRMED podem ser cancelados; pedido ' || p_order_id || ' está ' || l_order.status
            );
        end if;

        update orders set status = 'CANCELLED', updated_at = p_event_at where order_id = p_order_id;
    exception
        when others then
            rollback to sp_cancel_order;
            hub_audit.pkg_error_log.log_error(c_package, 'CANCEL_ORDER', 'order_id=' || p_order_id, sqlcode, sqlerrm);
            raise;
    end cancel_order;

end pkg_order;
/
