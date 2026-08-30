# Netra Evaluation Scorecard

This scorecard prevents unsupported claims. Fill measured fields from the final
government-feed rehearsal and from independently recorded ANPR-grade road
footage. Do not use the composited regression clip for accuracy claims.

| Measure | Target | Current evidence | Final result |
|---|---:|---|---|
| Supplied feeds onboarded | 50/50 | Adapter and 30-feed live source verified | Pending event feed set |
| Feed onboarding time | < 5 min | Instrumented health/readiness APIs | Pending timed run |
| Exact plate-string accuracy | >= 90% on ANPR-grade views | Multi-frame consensus works on regression fixture | Pending labeled real-road set |
| Plate false-positive rate | < 1% | Regex, confidence and repeat-read gates | Pending labeled real-road set |
| Cross-camera route accuracy | 100% on test corridor | Three-camera route regression proof | Pending genuine corridor footage |
| Search latency | < 2 s | `scripts/rehearse.py` records it | Pending final run |
| Evidence coverage | 100% of stored tracked events | Readiness API measures it | Verify before submission |
| Backend ingestion capacity | >= 250 frame summaries/s | 820 req/s measured | Pass |
| Recovery from one failed feed | < 30 s, other feeds unaffected | Per-adapter isolation and health monitor | Pending fault-injection video |
| Independent source systems | >= 2 | CSITMS + MediaMTX adapters | Pass; strengthen with physical VMS if available |

## Minimum real-road benchmark protocol

- At least 200 labeled plate appearances from consenting/authorized footage.
- Day, night, blur, angle and partial-occlusion strata reported separately.
- Train/tune footage must not appear in the final test split.
- Report exact-string accuracy, character accuracy, detection precision/recall,
  false alerts per hour and end-to-end route accuracy.
- Retain representative failures and show how confidence gating handles them.
