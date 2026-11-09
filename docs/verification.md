# Verification ledger — November 9, 2026

These are observations from actual execution, not intended future behavior.

## Implemented

Go/pgx queue and HTTP API; durable jobs/attempts; idempotency; short `SKIP LOCKED` claims; database-time leases; token fencing; heartbeat/progress; recovery; bounded retry/backoff; repeated completion; attempt-specific artifacts; rooted artifact serving; registered fake and evaluation tasks; Next.js selection/submission/history/results/overlays/compatible comparison; synthetic fixtures; verified label-channel decoder; KITTI manifest importer; compact U-Net training and evaluation; local model manifests; crash-demo/benchmark scripts; learning documentation.

## Verified against real PostgreSQL 14.18

`go test -race -v ./...` passed **7 integration tests**, including:

- 16 concurrent identical submissions give one job; reordered JSON is equivalent; changed JSON conflicts.
- 20 concurrent claims get 20 different jobs.
- Expired ownership cannot heartbeat; after reassignment, old tokens cannot heartbeat, complete or fail.
- Identical accepted completion repeats safely; different digest conflicts.
- Real-time heartbeats cross the original deadline without reclamation.
- Retryable errors back off, attempts exhaust, invalid input fails terminally, and final-attempt expiry fails terminally.
- Reconnecting the API store preserves jobs.
- HTTP submission/claim/completion/result flow, invalid task/unknown fields, symlink escape and traversal rejection, and browser-origin restriction.

Evidence: [PostgreSQL test log](evidence/postgres-tests.txt). Tests use unique PostgreSQL schemas, not a mock database. Docker Compose's PostgreSQL 16.13 image was **not run**, because Docker is absent here.

The [crash demonstration report](evidence/crash-demo.json) records an actual SIGKILL of worker A. Worker B reclaimed its job; attempts were expired then succeeded. Both logical jobs had exactly one accepted succeeded attempt. Duplicate submission returned the original ID. Restarting the actual Go API process preserved the result. Repeating completion returned success. This tests lost-response retry semantics by repeating a committed completion; it does not claim a packet-level network-fault injection harness.

## Verified science and end-to-end behavior

Four Python tests passed: RGB mask decoding with ignored road bits, hand-calculated metrics including empty/invalid cases, nearest-neighbor label preservation, and U-Net shape/backpropagation. [Log](evidence/science-tests.txt).

The actual CPU smoke training used seed 2026, 12 synthetic training images, 6 validation images, batch size 1 and two epochs. Validation IoU was 0.3223778736 after epoch 1 and 0.0439840308 after epoch 2, so **epoch 1** was selected. The held-out synthetic split has 6 different images.

| Predictor | Micro road IoU | Dice | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Synthetic smoke U-Net | 0.322378 | 0.487573 | 0.322378 | 1.000000 |
| Synthetic geometric demo | 0.708202 | 0.829178 | 0.976771 | 0.720334 |
| All-background baseline | 0.000000 | 0.000000 | undefined | 0.000000 |

All three rows are **synthetic demo** results, not KITTI results. Raw counts and per-image metrics: [U-Net](evidence/synthetic-unet.json), [demo](evidence/synthetic-demo.json), [background](evidence/synthetic-background.json). The U-Net smoke is weak; its high recall comes from predicting road broadly.

Four API-backed evaluations completed during the initial end-to-end check, including one submitted through the browser. All 120 referenced PNG artifacts were retrieved with valid PNG signatures. [Accepted jobs](evidence/evaluation-jobs.json).

The final process supervisor was also verified with two workers and a fifth evaluation; localhost proxy access succeeded and a nonlocal Host header returned 403. [Supervisor job](evidence/supervisor-job.json).

The Next.js production build and TypeScript check passed. Browser checks confirmed selection, submission, completion polling, metrics, ground-truth/prediction overlays, and compatible run comparison. [Screenshot](dashboard.png). Responsive CSS exists but a dedicated mobile viewport test was not performed. The original Turbopack dev watcher hit a sandbox FSEvents restriction; the production server worked. The final webpack development server was then started with WATCHPACK_POLLING=true; both its rendered page and /api/health proxy returned successfully.

## Measured scheduling benchmark

[Full report including job IDs](evidence/fake-benchmark.json). Machine: macOS 26.0.1 arm64, 8 logical CPUs, Python 3.12.11; PostgreSQL 14.18; native Go API. Exact hardware model and RAM were not available to the sandbox.

Configuration: 30 fake jobs submitted as a burst, two newly started workers, 0.1 seconds sleep per job, no injected failures, one allowed attempt, 0.4-second worker polling delay. No ML inference. Total measured time includes submission, worker startup and completion polling.

| Measurement | Observed |
| --- | ---: |
| Total wall time | 7.689 s |
| Throughput | 3.902 jobs/s |
| Queue wait p50 / p95 / p99 | 3.907 / 7.296 / 7.531 s |
| End-to-end p50 / p95 / p99 | 4.030 / 7.410 / 7.644 s |

Queue wait is first-attempt start minus job creation; end-to-end is attempt finish minus job creation, from database timestamps. Percentiles use linear interpolation. The burst queues behind two workers, and the deliberate 0.4-second polling delay dominates these tiny tasks. This is a baseline measurement of this small local implementation, not a saturation test, production SLA or multi-host scalability claim.

## Still unverified or requiring user data

- Actual KITTI image download, all-road pairing against that download, decoded overlay inspection, official raw-mapping normalization and group separation.
- Full real-data training and held-out real-data evaluation. No such result was fabricated.
- CUDA/MPS execution, Docker Compose execution, power-loss behavior, backup/restore and multi-host deployment.

The synthetic local workflow is working. Real KITTI scientific validation remains a separate required milestone after the manual dataset steps.
