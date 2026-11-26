-- Estoque por lote: entrada, reserva FEFO, liberação e baixa.
-- Nenhuma rotina faz COMMIT; em erro, desfaz só o próprio trabalho (savepoint).

create or replace package pkg_stock authid definer as
    -- validade mínima para venda
    c_min_shelf_life_days constant pls_integer := 30;

    e_insufficient_stock exception;
    pragma exception_init(e_insufficient_stock, -20101);
    e_invalid_quantity exception;
    pragma exception_init(e_invalid_quantity, -20102);

    procedure receive_stock(
        p_warehouse_id in stock.warehouse_id%type,
        p_lot_id       in stock.lot_id%type,
        p_quantity     in number,
        p_event_at     in timestamp default sys_extract_utc(systimestamp)
    );

    -- Sem estoque suficiente: -20101, sem reserva parcial.
    procedure reserve_fefo(
        p_order_id     in order_item_allocations.order_id%type,
        p_line_number  in order_item_allocations.line_number%type,
        p_warehouse_id in stock.warehouse_id%type,
        p_product_id   in lots.product_id%type,
        p_quantity     in number,
        p_on_date      in date default trunc(sysdate),
        p_event_at     in timestamp default sys_extract_utc(systimestamp)
    );

    procedure release_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    );

    procedure ship_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    );

    function available_qty(
        p_warehouse_id in stock.warehouse_id%type,
        p_product_id   in lots.product_id%type,
        p_on_date      in date default trunc(sysdate)
    ) return number;
end pkg_stock;
/

create or replace package body pkg_stock as

    c_package constant varchar2(30) := 'PKG_STOCK';

    procedure check_quantity(p_quantity in number) is
    begin
        if p_quantity is null or p_quantity <= 0 or p_quantity != trunc(p_quantity) then
            raise_application_error(-20102, 'Quantidade inválida: ' || nvl(to_char(p_quantity), 'NULL'));
        end if;
    end check_quantity;

    procedure receive_stock(
        p_warehouse_id in stock.warehouse_id%type,
        p_lot_id       in stock.lot_id%type,
        p_quantity     in number,
        p_event_at     in timestamp default sys_extract_utc(systimestamp)
    ) is
    begin
        savepoint sp_receive_stock;
        check_quantity(p_quantity);

        merge into stock s
        using (select p_warehouse_id as warehouse_id, p_lot_id as lot_id, p_quantity as qty from dual) src
           on (s.warehouse_id = src.warehouse_id and s.lot_id = src.lot_id)
         when matched then
            update set s.qty_on_hand = s.qty_on_hand + src.qty, s.updated_at = p_event_at
         when not matched then
            insert (warehouse_id, lot_id, qty_on_hand, qty_reserved, updated_at)
            values (src.warehouse_id, src.lot_id, src.qty, 0, p_event_at);

        insert into stock_movements (warehouse_id, lot_id, movement_type, quantity, created_at)
        values (p_warehouse_id, p_lot_id, 'IN', p_quantity, p_event_at);
    exception
        when others then
            rollback to sp_receive_stock;
            hub_audit.pkg_error_log.log_error(
                c_package, 'RECEIVE_STOCK',
                'warehouse_id=' || p_warehouse_id || ', lot_id=' || p_lot_id || ', quantity=' || p_quantity,
                sqlcode, sqlerrm
            );
            raise;
    end receive_stock;

    procedure reserve_fefo(
        p_order_id     in order_item_allocations.order_id%type,
        p_line_number  in order_item_allocations.line_number%type,
        p_warehouse_id in stock.warehouse_id%type,
        p_product_id   in lots.product_id%type,
        p_quantity     in number,
        p_on_date      in date default trunc(sysdate),
        p_event_at     in timestamp default sys_extract_utc(systimestamp)
    ) is
        -- FOR UPDATE evita reserva duplicada em pedidos concorrentes
        cursor c_lots is
            select s.lot_id, s.qty_on_hand - s.qty_reserved as qty_available
              from stock s
              join lots l on l.lot_id = s.lot_id
             where s.warehouse_id = p_warehouse_id
               and l.product_id = p_product_id
               and l.expires_on > p_on_date + c_min_shelf_life_days
               and s.qty_on_hand - s.qty_reserved > 0
             order by l.expires_on, l.lot_id
               for update of s.qty_reserved;
        l_remaining number := p_quantity;
        l_take      number;
    begin
        savepoint sp_reserve_fefo;
        check_quantity(p_quantity);

        for r in c_lots loop
            exit when l_remaining = 0;
            l_take := least(r.qty_available, l_remaining);

            update stock
               set qty_reserved = qty_reserved + l_take,
                   updated_at = p_event_at
             where current of c_lots;

            insert into order_item_allocations (order_id, line_number, lot_id, warehouse_id, quantity)
            values (p_order_id, p_line_number, r.lot_id, p_warehouse_id, l_take);

            insert into stock_movements (warehouse_id, lot_id, movement_type, quantity, order_id, created_at)
            values (p_warehouse_id, r.lot_id, 'RESERVE', l_take, p_order_id, p_event_at);

            l_remaining := l_remaining - l_take;
        end loop;

        if l_remaining > 0 then
            raise_application_error(
                -20101,
                'Estoque insuficiente: produto ' || p_product_id || ' no CD ' || p_warehouse_id
                    || ' (faltam ' || l_remaining || ' de ' || p_quantity || ')'
            );
        end if;
    exception
        when others then
            rollback to sp_reserve_fefo;
            hub_audit.pkg_error_log.log_error(
                c_package, 'RESERVE_FEFO',
                'order_id=' || p_order_id || ', line=' || p_line_number || ', warehouse_id=' || p_warehouse_id
                    || ', product_id=' || p_product_id || ', quantity=' || p_quantity,
                sqlcode, sqlerrm
            );
            raise;
    end reserve_fefo;

    procedure release_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    ) is
    begin
        savepoint sp_release_order;

        merge into stock s
        using (
            select warehouse_id, lot_id, sum(quantity) as qty
              from order_item_allocations
             where order_id = p_order_id
             group by warehouse_id, lot_id
        ) a
           on (s.warehouse_id = a.warehouse_id and s.lot_id = a.lot_id)
         when matched then
            update set s.qty_reserved = s.qty_reserved - a.qty, s.updated_at = p_event_at;

        insert into stock_movements (warehouse_id, lot_id, movement_type, quantity, order_id, created_at)
        select warehouse_id, lot_id, 'RELEASE', quantity, order_id, p_event_at
          from order_item_allocations
         where order_id = p_order_id;

        delete from order_item_allocations where order_id = p_order_id;
    exception
        when others then
            rollback to sp_release_order;
            hub_audit.pkg_error_log.log_error(c_package, 'RELEASE_ORDER', 'order_id=' || p_order_id, sqlcode, sqlerrm);
            raise;
    end release_order;

    procedure ship_order(
        p_order_id in orders.order_id%type,
        p_event_at in timestamp default sys_extract_utc(systimestamp)
    ) is
    begin
        savepoint sp_ship_order;

        merge into stock s
        using (
            select warehouse_id, lot_id, sum(quantity) as qty
              from order_item_allocations
             where order_id = p_order_id
             group by warehouse_id, lot_id
        ) a
           on (s.warehouse_id = a.warehouse_id and s.lot_id = a.lot_id)
         when matched then
            update set s.qty_on_hand = s.qty_on_hand - a.qty,
                       s.qty_reserved = s.qty_reserved - a.qty,
                       s.updated_at = p_event_at;

        insert into stock_movements (warehouse_id, lot_id, movement_type, quantity, order_id, created_at)
        select warehouse_id, lot_id, 'OUT', quantity, order_id, p_event_at
          from order_item_allocations
         where order_id = p_order_id;
    exception
        when others then
            rollback to sp_ship_order;
            hub_audit.pkg_error_log.log_error(c_package, 'SHIP_ORDER', 'order_id=' || p_order_id, sqlcode, sqlerrm);
            raise;
    end ship_order;

    function available_qty(
        p_warehouse_id in stock.warehouse_id%type,
        p_product_id   in lots.product_id%type,
        p_on_date      in date default trunc(sysdate)
    ) return number is
        l_qty number;
    begin
        select nvl(sum(s.qty_on_hand - s.qty_reserved), 0)
          into l_qty
          from stock s
          join lots l on l.lot_id = s.lot_id
         where s.warehouse_id = p_warehouse_id
           and l.product_id = p_product_id
           and l.expires_on > p_on_date + c_min_shelf_life_days;
        return l_qty;
    end available_qty;

end pkg_stock;
/
