drop table if exists curated.fact_order_items cascade;
drop table if exists curated.fact_orders cascade;
drop table if exists curated.dim_inventory cascade;
drop table if exists curated.dim_product cascade;
drop table if exists curated.dim_customer cascade;
drop table if exists curated.dim_date cascade;

create table curated.dim_date as
select
    d::date                       as date_key,
    extract(year from d)::int     as year,
    extract(month from d)::int    as month,
    to_char(d, 'YYYY-MM')         as year_month,
    extract(isodow from d)::int   as day_of_week,
    to_char(d, 'Dy')              as day_name
from generate_series(
    (select coalesce(min(processed_at)::date, current_date) - 7 from staging.orders),
    current_date + 30,
    interval '1 day'
) as d;

alter table curated.dim_date add primary key (date_key);

-- Surrogate keys are recomputed on each full rebuild -- valid because consumers always read the latest build and never persist keys
create table curated.dim_product as
select
    row_number() over (order by product_gid) as product_key,
    product_gid,
    title,
    vendor,
    product_type,
    status
from staging.products;

alter table curated.dim_product add primary key (product_key);
create unique index dim_product_gid_uq on curated.dim_product (product_gid);

create table curated.dim_customer as
select
    row_number() over (order by customer_gid) as customer_key,
    customer_gid,
    display_name,
    orders_count,
    created_at
from staging.customers;

alter table curated.dim_customer add primary key (customer_key);
create unique index dim_customer_gid_uq on curated.dim_customer (customer_gid);

-- NULL customer_gid groups all guest orders into one window partition (acceptable: guest sequence is not a business metric)
create table curated.fact_orders as
with orders as (
    select
        o.order_gid,
        o.order_name,
        o.processed_at,
        o.processed_at::date as date_key,
        c.customer_key,
        o.customer_gid,
        o.currency,
        o.subtotal_amount,
        o.total_amount
    from staging.orders o
    left join curated.dim_customer c using (customer_gid)
)
select
    order_gid,
    order_name,
    processed_at,
    date_key,
    customer_key,
    currency,
    subtotal_amount,
    total_amount,
    row_number() over (partition by customer_gid order by processed_at, order_gid) as customer_order_seq,
    sum(total_amount) over (order by processed_at, order_gid rows between unbounded preceding and current row) as running_revenue
from orders;

alter table curated.fact_orders add primary key (order_gid);
alter table curated.fact_orders add foreign key (date_key) references curated.dim_date (date_key);
alter table curated.fact_orders add foreign key (customer_key) references curated.dim_customer (customer_key);
create index fact_orders_customer_key_idx on curated.fact_orders (customer_key);
create index fact_orders_date_key_idx on curated.fact_orders (date_key);

create table curated.fact_order_items as
select
    i.line_item_gid,
    i.order_gid,
    p.product_key,
    i.title,
    i.sku,
    i.quantity,
    i.unit_price,
    (i.quantity * i.unit_price)::numeric(12,2)                          as line_revenue,
    ec.unit_cost,
    (i.quantity * ec.unit_cost)::numeric(12,2)                          as line_cost,
    ((i.quantity * i.unit_price) - (i.quantity * ec.unit_cost))::numeric(12,2) as line_margin
from staging.order_items i
left join curated.dim_product p using (product_gid)
left join raw.erp_costs ec on ec.sku = i.sku;

alter table curated.fact_order_items add primary key (line_item_gid);
alter table curated.fact_order_items add foreign key (order_gid) references curated.fact_orders (order_gid);
alter table curated.fact_order_items add foreign key (product_key) references curated.dim_product (product_key);
create index fact_order_items_product_key_idx on curated.fact_order_items (product_key);
create index fact_order_items_order_gid_idx on curated.fact_order_items (order_gid);

create table curated.dim_inventory as
select sku, on_hand, unit_cost
from raw.erp_costs;

alter table curated.dim_inventory add primary key (sku);
