-- Models 1-3: durable asset lifecycle plus normalized multi-system provenance.
alter table public.cameras
  add column if not exists source_system text,
  add column if not exists source_adapter text,
  add column if not exists external_id text,
  add column if not exists installed_at timestamptz,
  add column if not exists maintenance_status text not null default 'unknown',
  add column if not exists last_service_at timestamptz,
  add column if not exists next_service_at timestamptz,
  add column if not exists eol_at timestamptz,
  add column if not exists maintenance_notes text;

update public.cameras
set
  source_system = coalesce(
    source_system,
    case
      when camera_id like 'GJ-CSITMS-%' then 'Gujarat CSITMS'
      else 'Manual / CSV'
    end
  ),
  source_adapter = coalesce(
    source_adapter,
    case
      when camera_id like 'GJ-CSITMS-%' then 'csitms_api'
      else 'manual'
    end
  ),
  external_id = coalesce(
    external_id,
    case
      when camera_id like 'GJ-CSITMS-%' then ltrim(split_part(camera_id, '-', 3), '0')
      else camera_id
    end
  );

update public.cameras
set external_id = '0'
where external_id = '';

alter table public.cameras
  alter column source_system set default 'Manual / CSV',
  alter column source_system set not null,
  alter column source_adapter set default 'manual',
  alter column source_adapter set not null,
  alter column external_id set not null;

create index if not exists cameras_source_system_idx
  on public.cameras (source_system);
create index if not exists cameras_source_adapter_idx
  on public.cameras (source_adapter);
create unique index if not exists cameras_source_external_uidx
  on public.cameras (source_system, external_id);
create index if not exists cameras_maintenance_due_idx
  on public.cameras (maintenance_status, next_service_at);
create index if not exists cameras_eol_at_idx
  on public.cameras (eol_at)
  where eol_at is not null;

alter table public.detection_events
  add column if not exists source_system text,
  add column if not exists source_adapter text;

update public.detection_events as event
set
  source_system = camera.source_system,
  source_adapter = camera.source_adapter
from public.cameras as camera
where camera.camera_id = event.camera_id
  and (event.source_system is null or event.source_adapter is null);

create index if not exists detection_events_source_ts_idx
  on public.detection_events (source_system, ts desc);

alter table public.alerts
  add column if not exists source_system text;

update public.alerts as alert
set source_system = camera.source_system
from public.cameras as camera
where camera.camera_id = alert.camera_id
  and alert.source_system is null;

create index if not exists alerts_source_ts_idx
  on public.alerts (source_system, ts desc);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'cameras_maintenance_status_valid'
      and conrelid = 'public.cameras'::regclass
  ) then
    alter table public.cameras
      add constraint cameras_maintenance_status_valid check (
        maintenance_status in (
          'unknown', 'healthy', 'due', 'overdue', 'under_maintenance', 'retired'
        )
      );
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'cameras_lifecycle_dates_valid'
      and conrelid = 'public.cameras'::regclass
  ) then
    alter table public.cameras
      add constraint cameras_lifecycle_dates_valid check (
        (last_service_at is null or next_service_at is null or next_service_at >= last_service_at)
        and (installed_at is null or eol_at is null or eol_at >= installed_at)
      );
  end if;
end $$;

comment on column public.cameras.source_system is
  'Stable independent VMS or departmental source-system identity.';
comment on column public.cameras.external_id is
  'Camera identifier within source_system; unique only together with source_system.';
