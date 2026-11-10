# KITTI v2 run through Relay — November 9, 2026

A deliberately bounded model update. Relay remains the focus of the project; this run exists mainly to exercise Relay's crash-recovery path on a real (non-synthetic) evaluation workload. No new data was downloaded; the same 289 labeled training-release images were re-split.

## What changed from v1

1. **Category-covered, recording-separated split** (`kitti-balanced-v2-*`). A fixed seeded search (seed 2026, 1,000 candidates, metadata only — no model scores) picked the recording-group assignment that best balanced categories. No recording group appears in more than one role.
2. **Aspect-preserving input.** Images are letterboxed into a 384×128 canvas (v1: stretched to 128×64). Padding is labelled invalid, so it is excluded from loss and metrics.
3. **Longer training.** 12 epochs (v1: 5). Same tiny U-Net architecture, seed, optimizer, LR and batch size.

| Role | Images | Recording groups | um / umm / uu |
| --- | ---: | ---: | --- |
| Train | 205 | 26 | 65 / 66 / 74 |
| Validation | 41 | 6 | 17 / 14 / 10 |
| Internal test | 43 | 5 | 13 / 16 / 14 |

The internal test now includes `umm` (multiple marked lanes), which v1's test lacked.

## Training

CPU, seed 2026, 12 epochs, batch 1, Adam LR 0.001. Wall time **124.8 s**. The checkpoint is chosen by validation IoU only. Best was **epoch 11** (validation IoU 0.7378). Validation IoU varied considerably between epochs (0.31–0.74), which shows that 41 validation images make checkpoint choice noisy. See the [training log](evidence/kitti-v2-training.log).

## Internal-test results (evaluated by Relay workers)

| Model | Road IoU | F1 / Dice | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| U-Net v2 | **0.7933** | **0.8848** | 0.9238 | 0.8489 |
| All-background | 0 | 0 | undefined | 0 |

| Category | IoU | F1 | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| um (marked) | 0.8433 | 0.9150 | 0.9271 | 0.9032 |
| umm (multi-marked) | 0.8324 | 0.9085 | 0.9755 | 0.8501 |
| uu (unmarked) | 0.6902 | 0.8167 | 0.8466 | 0.7889 |

Unmarked roads are clearly the weakest. 7 of the 10 worst test images are `uu`: `uu_000005`, `uu_000002`, `umm_000050`, `uu_000036`, `um_000061`, … (full per-image list in the [Relay report](evidence/kitti-v2-relay-report.json)). Overall, errors are mostly missed road (recall) rather than false road.

**Not comparable with v1's 56.94% IoU.** The split, preprocessing and training length all changed together, and the test images differ. The higher number therefore can't be attributed to any one change, and the v1 model can't be re-scored on the v2 split: the evaluator deliberately rejects model and dataset preprocessing mismatches. These remain internal resized-image metrics, not official KITTI bird's-eye-view MaxF/AP.

## Relay verification on the real workload

`scripts/demo.py --dataset kitti-balanced-v2-internal_test --model kitti-unet-v2 --comparison-model kitti-balanced-v2-background` ran two workers and:

- SIGKILLed worker A mid-evaluation. Worker B reclaimed the job after the lease expired, and it succeeded on attempt 2.
- Rejected a late completion from the killed attempt's stale token with **HTTP 409**.
- Returned the same job ID for a duplicate submit, and kept a repeated completion stable.
- Restarted the API process with jobs preserved.
- The recovered job's `result_sha256` matches a clean single-attempt run of the same evaluation.

Result: `PASS` ([log](evidence/kitti-v2-relay-recovery.log)). The same scenario also passed on the synthetic workload ([log](evidence/relay-fake-recovery.log)). Python tests: 9 passing ([output](evidence/kitti-v2-tests.txt)).

## Reproduce

Follow the [README real KITTI workflow](../README.md#real-kitti-workflow) for a fresh checkout: it imports the user-provided ZIPs under new names, builds the category-covered split, trains a checkpoint and runs the real-workload recovery demonstration. Existing experiment names are protected against overwrite; the original checkpoint is not included in Git.

Checkpoint selection used validation only. This is an exploratory versioned split of previously used source data, not a newly collected blind test set. Earlier models may have trained on images assigned to v2's internal test, so they are not suitable baselines on that split even if preprocessing were made compatible.

Checkpoints, images and generated trained-model registrations stay out of Git.
