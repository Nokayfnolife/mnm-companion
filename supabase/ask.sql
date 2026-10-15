-- MnM Companion: daily question limit for the "ask" Edge Function.
-- Run this once in Supabase > SQL Editor.

create table if not exists public.ask_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  day     date not null default ((now() at time zone 'utc')::date),
  n       int  not null default 0,
  primary key (user_id, day)
);

-- No policies on purpose: players can't read or change this table.
-- Only the ask function, using the service key, touches it through ask_bump below.
alter table public.ask_usage enable row level security;

-- Counts one question for a player and returns today's total,
-- or -1 when they've already reached the limit.
create or replace function public.ask_bump(uid uuid, lim int)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare cur int;
begin
  insert into public.ask_usage (user_id, day, n)
  values (uid, (now() at time zone 'utc')::date, 1)
  on conflict (user_id, day) do update
    set n = public.ask_usage.n + 1
    where public.ask_usage.n < lim
  returning n into cur;
  return coalesce(cur, -1);
end $$;

revoke all on function public.ask_bump(uuid, int) from public, anon, authenticated;
grant execute on function public.ask_bump(uuid, int) to service_role;
