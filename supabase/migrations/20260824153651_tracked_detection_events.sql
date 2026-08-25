alter table public.detection_events
  add column if not exists track_uuid text,
  add column if not exists track_id integer,
  add column if not exists track_hits integer not null default 1,
  add column if not exists class_confidence double precision,
  add column if not exists color_confidence double precision,
  add column if not exists first_seen timestamptz,
  add column if not exists last_seen timestamptz,
  add column if not exists ingested_at timestamptz,
  add column if not exists time_source text not null default 'ingest',
  add column if not exists direction text,
  add column if not exists dwell_seconds double precision,
  add column if not exists motion_px_per_second double precision,
  add column if not exists stopped boolean not null default false,
  add column if not exists wrong_way boolean,
  add column if not exists bbox_x1 integer,
  add column if not exists bbox_y1 integer,
  add column if not exists bbox_x2 integer,
  add column if not exists bbox_y2 integer;

update public.detection_events
set
  first_seen = coalesce(first_seen, ts),
  last_seen = coalesce(last_seen, ts),
  ingested_at = coalesce(ingested_at, ts, now())
where first_seen is null or last_seen is null or ingested_at is null;

alter table public.detection_events
  alter column ingested_at set default now(),
  alter column ingested_at set not null;

create unique index if not exists detection_events_track_uuid_uidx
  on public.detection_events (track_uuid)
  where track_uuid is not null;

create index if not exists detection_events_camera_track_idx
  on public.detection_events (camera_id, track_id);

create index if not exists detection_events_ingested_at_idx
  on public.detection_events (ingested_at);

alter table public.watchlist
  add column if not exists min_confidence double precision not null default 0.65,
  add column if not exists min_track_hits integer not null default 3;

update public.watchlist
set min_confidence = 0.72, min_track_hits = 4
where case_ref = 'NCB/2026/07';

update public.watchlist
set min_confidence = 0.55, min_track_hits = 3
where kind = 'plate';

alter table public.alerts
  add column if not exists match_confidence double precision,
  add column if not exists ingested_at timestamptz,
  add column if not exists time_source text not null default 'ingest';

update public.alerts
set ingested_at = coalesce(ingested_at, ts, now())
where ingested_at is null;

alter table public.alerts
  alter column ingested_at set default now(),
  alter column ingested_at set not null;

create index if not exists alerts_ingested_at_idx
  on public.alerts (ingested_at);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'detection_events_track_hits_positive'
      and conrelid = 'public.detection_events'::regclass
  ) then
    alter table public.detection_events
      add constraint detection_events_track_hits_positive check (track_hits > 0);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'detection_events_confidence_ranges'
      and conrelid = 'public.detection_events'::regclass
  ) then
    alter table public.detection_events
      add constraint detection_events_confidence_ranges check (
        (class_confidence is null or class_confidence between 0 and 1)
        and (color_confidence is null or color_confidence between 0 and 1)
      );
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'detection_events_seen_order'
      and conrelid = 'public.detection_events'::regclass
  ) then
    alter table public.detection_events
      add constraint detection_events_seen_order check (
        first_seen is null or last_seen is null or last_seen >= first_seen
      );
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'watchlist_match_thresholds_valid'
      and conrelid = 'public.watchlist'::regclass
  ) then
    alter table public.watchlist
      add constraint watchlist_match_thresholds_valid check (
        min_confidence between 0 and 1 and min_track_hits > 0
      );
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'alerts_match_confidence_range'
      and conrelid = 'public.alerts'::regclass
  ) then
    alter table public.alerts
      add constraint alerts_match_confidence_range check (
        match_confidence is null or match_confidence between 0 and 1
      );
  end if;
end $$;

-- This project-level DDL helper is SECURITY DEFINER and must not be callable
-- through the exposed Data API. Keep execution limited to postgres/service_role.
do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable()
      from public, anon, authenticated;
  end if;
end $$;
