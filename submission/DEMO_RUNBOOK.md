# Netra Demonstration Runbook

## Before entering the room

1. Run `NETRA_PASSWORD=... python3 scripts/preflight.py` and retain the output.
2. Confirm the supplied feed count and update `NETRA_EXPECTED_CAMERAS`.
3. Keep the local PostGIS profile, Docker images and model weights cached.
4. Open the Map, Video Wall, Tracking, Alerts and Ops tabs in separate tabs.
5. Clear only rehearsal records; never seed a result for the evaluator's plate.

## Live scored workflow

1. Ask the evaluator for the registration number and repeat it aloud.
2. Show source onboarding and the exact live camera count.
3. Open two representative feeds to establish that video is live.
4. Enter the supplied registration number in Tracking.
5. Show the ordered route, timestamps, camera locations, evidence and match confidence.
6. Export the movement CSV and open it for the evaluator.
7. Open Ops and show source provenance, health, readiness and federation state.
8. Run `NETRA_TEST_PLATE=<plate> NETRA_PASSWORD=... python3 scripts/rehearse.py` to save machine-readable timing evidence.

## Three-minute own-feed video

- 0:00-0:20: the fragmented-camera problem and Netra's one-line promise.
- 0:20-0:45: onboard the independent RTSP system and show provenance.
- 0:45-1:20: show live playback and the same real vehicle crossing three cameras.
- 1:20-2:10: search the plate; show route, timestamps and evidence.
- 2:10-2:35: export the movement report.
- 2:35-3:00: show measured readiness, security and the 80,000-camera rollout.

## Government-feed video

- Show the feed source and actual camera count.
- Show live/recorded viewing without claiming readable plates where resolution is insufficient.
- Show genuine detections, source timestamps and exported report rows.
- State the camera-resolution limitation plainly, then show the ANPR-grade real-road proof as a separate source.

## Recovery

- Feed unavailable: show the explicit ingest error, retry, then switch to another genuine feed.
- Remote database unavailable: start the documented local PostGIS profile.
- GPU unavailable: reduce active analytics streams and sampling rate; do not change confidence gates.
- Network unavailable: use cached images/models and the independent local RTSP system.
