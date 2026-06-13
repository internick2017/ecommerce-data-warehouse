create table if not exists meta.webhook_events (
    event_id    text primary key,
    topic       text,
    shopify_gid text,
    hmac_valid  boolean,
    status      text not null default 'received' check (status in ('received','processed','rejected')),
    received_at timestamptz not null default now()
)
