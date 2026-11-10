# Explain it yourself

**Real-data update:** subsequent work completed both a [40-image subset run](kitti-small-run.md) and an [all-289-image run](kitti-full-run.md), including official sequence mapping, overlay inspection, CPU training and held-out evaluation. Earlier no-KITTI statements below describe the initial synthetic-only milestone. The full report records current coverage limitations.

Before presenting the project, answer these by pointing to code and a saved test:

1. Why can a timed-out HTTP request still have committed? How does the idempotency key prevent duplicate logical jobs?
2. What does `SKIP LOCKED` skip? Which rows are locked, and when are those locks released?
3. Why does a lease need an attempt token as well as a deadline? Demonstrate a stale completion after reassignment.
4. Why use database time rather than the worker's clock? What happens if a worker is paused for a minute?
5. Where could duplicate computation happen? Why is one accepted result different from exactly-once execution?
6. Why write attempt-specific paths? What files can remain after a worker crash?
7. What happens if the API commits completion but the response is lost? What if the disk loses the accepted file later?
8. How does retryable differ from invalid input? When does backoff happen, and when does a job become terminal?
9. What do the red and blue KITTI label channels mean? Why must the validity mask affect both training loss and metrics?
10. Why is the all-road label different from ego-lane? Show the filename pairing rule.
11. Why can neighboring frames leaking between splits inflate apparent performance? What evidence supports your group assignments?
12. Trace `[N,3,H,W]` through U-Net to `[N,1,H,W]`. Why are the output values logits rather than class IDs?
13. Why can pixel accuracy be misleading? Compute TP/FP/FN/TN, IoU and Dice by hand for a 2×2 mask.
14. Why can micro IoU differ from mean image IoU? How do empty road masks and entirely ignored images differ?
15. Which decisions may use validation data? What would make an internal-test result invalid as a held-out estimate?
16. Which measurements did you actually collect? Why does the local fake benchmark say nothing about multi-host scalability?

## Honest limitations

- KITTI labeled images and official raw mapping are not bundled. The devkit label decoder was verified; actual KITTI import, overlay inspection, group assignments and real-data training remain unverified.
- A normalized mapping CSV is accepted, but parsing the official mapping's raw format awaits access to that file. The adapter makes no automatic sequence-independence claim without supplied group data.
- The two-epoch synthetic U-Net is intentionally only a smoke check. No real driving performance, weather robustness, safety or generalization claim follows.
- 128×64 resizing is cheap and distorts aspect ratio. No augmentation, calibration to bird's-eye view, pretrained backbone, class balancing or tuned learning schedule is included.
- API and workers share a trusted machine/filesystem. There is no authentication, multi-tenant isolation, multi-host storage, backup policy, job cancellation, automatic artifact retention or pagination beyond the latest 200 jobs.
- Database schema bootstrap is for the initial version. Production changes need explicit migrations and deployment coordination.
- Local crash tests cover SIGKILL and API restart, not full host/power loss, corrupt storage, PostgreSQL failover or network partitions lasting hours.
- The benchmark uses a burst of fake sleep jobs. Its latency includes intentional worker polling and process startup; it is not a capacity estimate or an ML throughput benchmark.
- CPU training was exercised; accelerator paths are implemented but unverified. Unsupported deterministic operations can fail explicitly.
- Browser submission retries retain keys in memory only. A page reload loses an unresolved submission key.
- No video, simulator, object tracking, real-time control, estimated-depth fusion, cloud queues, or remote storage is present.

Read `relay/store.go` before adding infrastructure. The intended next milestone is collecting real-data evidence, not expanding the architecture.
