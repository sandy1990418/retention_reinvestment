-- Run this in Supabase Dashboard → SQL Editor

create table watchlist (
  id bigint generated always as identity primary key,
  user_id text not null,
  stock_id text not null,
  created_at timestamptz default now(),
  unique (user_id, stock_id)
);

-- Index for fast lookups by user
create index idx_watchlist_user_id on watchlist (user_id);

-- Enable Row Level Security
alter table public.watchlist enable row level security;

-- Allow service role (backend) full access
create policy "Service role full access"
  on public.watchlist
  for all
  using (true)
  with check (true);
