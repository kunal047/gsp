-- Visual detections without evidence are not operational events. Preserve the
-- legacy metadata in a recovery-only archive before removing it from the live
-- event table.
create table if not exists public.detection_events_without_evidence_archive
(like public.detection_events including all);

insert into public.detection_events_without_evidence_archive
select * from public.detection_events
where snapshot is null or btrim(snapshot) = ''
on conflict (id) do nothing;

delete from public.detection_events
where snapshot is null or btrim(snapshot) = '';

alter table public.detection_events
  alter column snapshot set not null;

alter table public.detection_events
  add constraint detection_events_snapshot_nonempty
  check (btrim(snapshot) <> '');
