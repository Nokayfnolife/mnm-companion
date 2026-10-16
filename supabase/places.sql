-- Community places: map pins players suggest for everyone, shown once a moderator approves them.
-- Run once in Supabase > SQL Editor (safe to run again). Then make yourself a moderator, see the end of this file.

create table if not exists public.places (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  map text not null check (char_length(map) between 1 and 60),
  x double precision not null check (x >= 0 and x <= 1),
  y double precision not null check (y >= 0 and y <= 1),
  kind text not null check (kind in ('camp','named','quest','vendor','trainer','craft','exit','travel','landmark','other')),
  title text not null check (char_length(title) between 1 and 80),
  note text not null default '' check (char_length(note) <= 400),
  lvl_lo int check (lvl_lo between 1 and 60),
  lvl_hi int check (lvl_hi between 1 and 60),
  to_zone text check (char_length(to_zone) <= 60),
  author text check (char_length(author) <= 40),
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);
create index if not exists places_status_idx on public.places (status);
create index if not exists places_user_idx on public.places (user_id);

-- who can approve suggestions
create table if not exists public.place_mods (
  user_id uuid primary key references auth.users (id) on delete cascade
);

alter table public.places enable row level security;
alter table public.place_mods enable row level security;

create or replace function public.is_place_mod() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.place_mods where user_id = auth.uid());
$$;

-- a player can have at most 25 suggestions waiting at once
create or replace function public.places_limit() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.places where user_id = new.user_id and status = 'pending') >= 25 then
    raise exception 'You already have 25 places waiting for review.';
  end if;
  return new;
end $$;
drop trigger if exists places_limit on public.places;
create trigger places_limit before insert on public.places for each row execute function public.places_limit();

drop policy if exists "places: read approved, your own, or all as a moderator" on public.places;
create policy "places: read approved, your own, or all as a moderator" on public.places
  for select using (status = 'approved' or user_id = auth.uid() or public.is_place_mod());

drop policy if exists "places: suggest as yourself" on public.places;
create policy "places: suggest as yourself" on public.places
  for insert to authenticated with check (user_id = auth.uid() and status = 'pending');

drop policy if exists "places: moderators review" on public.places;
create policy "places: moderators review" on public.places
  for update to authenticated using (public.is_place_mod()) with check (public.is_place_mod());

drop policy if exists "places: withdraw your waiting ones, or moderators remove" on public.places;
create policy "places: withdraw your waiting ones, or moderators remove" on public.places
  for delete to authenticated using ((user_id = auth.uid() and status = 'pending') or public.is_place_mod());

drop policy if exists "place_mods: see yourself" on public.place_mods;
create policy "place_mods: see yourself" on public.place_mods
  for select to authenticated using (user_id = auth.uid());

grant select on public.places to anon, authenticated;
grant insert, update, delete on public.places to authenticated;
grant select on public.place_mods to authenticated;

-- Make yourself a moderator (use the email your account signs in with; for Discord, the email on your Discord account):
-- insert into public.place_mods (user_id) select id from auth.users where email = 'you@example.com' on conflict do nothing;
