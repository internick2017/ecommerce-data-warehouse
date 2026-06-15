create schema if not exists raw;
create schema if not exists staging;
create schema if not exists curated;
create schema if not exists meta;

create table if not exists raw.orders (
    shopify_gid  text primary key,
    payload      jsonb not null,
    load_id      bigint not null,
    extracted_at timestamptz not null,
    loaded_at    timestamptz not null default now()
);

create table if not exists raw.products (
    shopify_gid  text primary key,
    payload      jsonb not null,
    load_id      bigint not null,
    extracted_at timestamptz not null,
    loaded_at    timestamptz not null default now()
);

create table if not exists raw.customers (
    shopify_gid  text primary key,
    payload      jsonb not null,
    load_id      bigint not null,
    extracted_at timestamptz not null,
    loaded_at    timestamptz not null default now()
);

create table if not exists raw.rejects (
    reject_id   bigint generated always as identity primary key,
    entity      text not null,
    payload     jsonb not null,
    reason      text not null,
    load_id     bigint not null,
    rejected_at timestamptz not null default now()
);

create table if not exists raw.erp_costs (
    sku            text primary key,
    unit_cost      numeric(12,2),
    on_hand        int,
    erp_updated_at timestamptz,
    loaded_at      timestamptz not null default now()
);

create table if not exists meta.load_audit (
    load_id       bigint generated always as identity primary key,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    status        text not null default 'RUNNING' check (status in ('RUNNING','SUCCESS','FAILED')),
    rows_extracted int not null default 0,
    rows_loaded    int not null default 0,
    rows_rejected  int not null default 0,
    error         text
);

create table if not exists meta.watermarks (
    entity          text primary key,
    last_updated_at timestamptz not null
);
