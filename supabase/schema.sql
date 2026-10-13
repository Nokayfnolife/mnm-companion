-- MnM Companion: one row of saved data (characters, progress, map pins) per player.
-- Run this once in Supabase > SQL Editor.

create table if not exists public.user_data (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  constraint user_data_size check (pg_column_size(data) < 512000)
);

alter table public.user_data enable row level security;

drop policy if exists "read own"   on public.user_data;
drop policy if exists "insert own" on public.user_data;
drop policy if exists "update own" on public.user_data;
drop policy if exists "delete own" on public.user_data;

create policy "read own"   on public.user_data for select using (auth.uid() = user_id);
create policy "insert own" on public.user_data for insert with check (auth.uid() = user_id);
create policy "update own" on public.user_data for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "delete own" on public.user_data for delete using (auth.uid() = user_id);

-- Live sync between a player's devices
do $$ begin
  alter publication supabase_realtime add table public.user_data;
exception when duplicate_object then null; end $$;
