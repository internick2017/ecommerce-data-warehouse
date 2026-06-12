drop table if exists staging.order_items cascade;
drop table if exists staging.orders cascade;
drop table if exists staging.products cascade;
drop table if exists staging.customers cascade;

create table staging.orders as
select
    payload->>'id'                                          as order_gid,
    payload->>'name'                                        as order_name,
    (payload->>'createdAt')::timestamptz                    as created_at,
    (payload->>'processedAt')::timestamptz                  as processed_at,
    (payload->>'updatedAt')::timestamptz                    as updated_at,
    payload->>'currencyCode'                                as currency,
    (payload#>>'{totalPriceSet,shopMoney,amount}')::numeric(12,2)    as total_amount,
    (payload#>>'{subtotalPriceSet,shopMoney,amount}')::numeric(12,2) as subtotal_amount,
    payload#>>'{customer,id}'                               as customer_gid
from raw.orders;

alter table staging.orders add primary key (order_gid);

-- cross join lateral drops orders whose lineItems.edges is empty: zero-item orders appear in staging.orders only
create table staging.order_items as
select
    o.payload->>'id'                                        as order_gid,
    e.edge#>>'{node,id}'                                    as line_item_gid,
    e.edge#>>'{node,title}'                                 as title,
    (e.edge#>>'{node,quantity}')::int                       as quantity,
    e.edge#>>'{node,sku}'                                   as sku,
    e.edge#>>'{node,product,id}'                            as product_gid,
    (e.edge#>>'{node,originalUnitPriceSet,shopMoney,amount}')::numeric(12,2) as unit_price
from raw.orders o
cross join lateral jsonb_array_elements(o.payload#>'{lineItems,edges}') as e(edge);

-- Shopify LineItem GIDs are globally unique database IDs (not per-order positions)
alter table staging.order_items add primary key (line_item_gid);

create table staging.products as
select
    payload->>'id'                       as product_gid,
    payload->>'title'                    as title,
    payload->>'status'                   as status,
    payload->>'vendor'                   as vendor,
    payload->>'productType'              as product_type,
    (payload->>'createdAt')::timestamptz as created_at,
    (payload->>'updatedAt')::timestamptz as updated_at
from raw.products;

alter table staging.products add primary key (product_gid);

create table staging.customers as
select
    payload->>'id'                        as customer_gid,
    payload->>'displayName'               as display_name,
    (payload->>'numberOfOrders')::int     as orders_count,
    (payload->>'createdAt')::timestamptz  as created_at,
    (payload->>'updatedAt')::timestamptz  as updated_at
from raw.customers;

alter table staging.customers add primary key (customer_gid)
