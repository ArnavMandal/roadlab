# Model card and metric definitions

**Real-data update:** subsequent work completed both a [40-image subset run](kitti-small-run.md) and an [all-289-image run](kitti-full-run.md), including official sequence mapping, overlay inspection, CPU training and held-out evaluation. Earlier no-KITTI statements below describe the initial synthetic-only milestone. The full report records current coverage limitations. The [v2 run](kitti-v2-run.md) adds category coverage in every split, aspect-preserving input and per-category scores.

## Readable RGB-only baseline

`worker/model.py` implements a two-level U-Net with channel widths 8, 16 and 32. Each block has two 3×3 convolutions and ReLUs. Max-pooling shrinks the spatial grid. Bilinear upsampling restores spatial size; skip connections concatenate encoder features with decoder features so fine edges need not be reconstructed from the bottleneck alone. A final 1×1 convolution produces one logit per pixel. There is no pretrained backbone or depth input.

Input: `[N, 3, H, W]` float32 RGB in [0,1]. Output: `[N, 1, H, W]` unrestricted logits. A logit is a score before the sigmoid converts it to a road probability. At the fixed threshold 0.5, a nonnegative logit predicts road. Odd dimensions are supported by resizing each decoder stage to the exact encoder feature shape.

Training uses `binary_cross_entropy_with_logits(..., reduction='none')`. Index the loss by valid pixels, then average. This is more numerically stable than computing a sigmoid and logs separately. An image with no valid pixels contributes no training update. Optimization is Adam, learning rate 0.001, batch size 1, no class weighting or augmentation. Seeds are set for Python, NumPy and PyTorch. Deterministic algorithms are requested, but cross-device/version bitwise equivalence is not promised.

Training updates weights. Validation runs in `eval()` with no gradients and selects the checkpoint with highest validation micro road IoU; ties retain the earlier checkpoint. The internal test is never used by training. Do not select thresholds or epochs from its results. Save a new model name per experiment rather than overwriting an old checkpoint.

Checkpoints contain state_dict, architecture ID, preprocessing, seed, selected epoch, validation IoU, split hashes and worker-code hash. Registry entries additionally record checkpoint SHA-256, training history, configuration and PyTorch version. `torch.load(weights_only=True)` is used; load only your locally registered checkpoints. Evaluation checks the checkpoint digest and architecture/preprocessing compatibility.

## Metrics: `road-micro-v1`

All computations are in the **resized image plane**, not the KITTI official bird's-eye-view protocol. The threshold is fixed at 0.5. Invalid pixels are excluded before counting:

- TP: predicted road and labeled road.
- FP: predicted road and labeled non-road.
- FN: predicted non-road and labeled road.
- TN: predicted non-road and labeled non-road.

| Metric | Formula | Zero-denominator convention |
| --- | --- | --- |
| Road IoU | TP / (TP + FP + FN) | 1 when prediction and truth both have no road, if any valid pixels exist |
| Road Dice | 2TP / (2TP + FP + FN) | Same empty-road convention |
| Precision | TP / (TP + FP) | null if there are no predicted road pixels |
| Recall | TP / (TP + FN) | null if there are no labeled road pixels |

If an image has **no valid pixels**, all metrics are null. Its zero counts add nothing to the global aggregate. Null is displayed as a dash, never a fabricated zero or NaN. If only one of prediction/ground truth contains road, IoU and Dice are zero.

Aggregate road metrics first **sum TP/FP/FN/TN across all images**, then compute formulas. This micro aggregation weights large valid areas more heavily. Per-image counts and metrics are retained. `mean_image_iou` is an unweighted mean of defined per-image IoUs; it is not the reported micro IoU. Worst examples sort ascending by per-image IoU, with no-valid-pixel examples last. The dashboard limits this list to ten.

Pixel accuracy can look high when non-road dominates: the all-background baseline gets every non-road pixel right while detecting no road. That is why it is not the headline measure. Compare the learned model to the registered all-background predictor and, on synthetic fixtures only, the geometric demo predictor.

Direct dashboard comparison is enabled only for equal dataset manifest digests, metric configuration and preprocessing. The UI displays model/checkpoint provenance, and does not claim incompatible splits are comparable.

## Observed results and limits

A two-epoch CPU synthetic smoke run completed. Its validation score was higher after epoch 1, so that checkpoint was retained. Synthetic held-out IoU was about 32.24%; the geometric demo scored about 70.82%; all-background scored 0%. This is an intentionally weak smoke model, not a successful road-perception model. See the exact saved counts and verification report. No full KITTI training or real-driving result is claimed.

Estimated-depth fusion is excluded. A controlled follow-up could hold splits, training budget and metrics fixed and compare RGB-only against RGB plus estimated depth. Depth inferred from RGB is a derived representation of the same input, not an independent sensor measurement. Do not describe it as equivalent to LiDAR or stereo observations.
