# Full labeled KITTI run — November 9, 2026

After the first 40-image smoke experiment, the user authorized using more data. All 289 labeled training-release images and their all-road masks were selectively extracted from the existing ZIP. Official benchmark testing images were not extracted and no additional download occurred. Original ZIPs were left unchanged.

## Data and splits

The extracted RGB images and masks total 240,419,511 bytes (~229.3 MiB), plus small manifests and audit files. The earlier 32 MiB subset is retained separately. Source archive hashes and every image/mask hash are recorded in `registry/datasets/kitti-full-v1-*.json`; full assignment is in `storage/datasets/kitti-full-v1/split-audit.json`.

| Role | Images | Raw recordings | um / umm / uu |
| --- | ---: | ---: | --- |
| Train | 189 | 26 | 61 / 68 / 60 |
| Validation | 57 | 6 | 9 / 28 / 20 |
| Internal test | 43 | 5 | 25 / 0 / 18 |

An explicit audit checked all 289 IDs are unique across roles, no raw recording crosses roles, and every earlier subset image retains its original role. These are recording-separated splits, not a claim that geographically related recordings or all visual similarity have been excluded. The internal test has **no umm examples**; this limitation is retained rather than changing the split after looking at test results.

## Training and evaluation actually performed

CPU, seed 2026, five epochs, batch size 1, Adam learning rate 0.001, RGB-only tiny U-Net, 128×64 input, fixed 0.5 probability threshold. Architecture and training schedule were unchanged from the small run. More training samples mean more gradient updates per epoch. Training wall time, including Python startup, data loading and checkpoint output, was **12.237 seconds** on this machine; evaluation/extraction time is not included.

| Epoch | Training loss | Validation micro IoU |
| --- | ---: | ---: |
| 1 | 0.391691 | 0.419823 |
| 2 | 0.253560 | 0.594740 |
| 3 | 0.202472 | 0.713233 |
| 4 | 0.189955 | 0.636691 |
| 5 | 0.168545 | 0.651061 |

**Epoch 3** was selected using validation IoU; the later epochs did not replace it. That checkpoint was evaluated once on the 43-image internal test. No subsequent tuning based on its score was performed.

| Internal-test model | Road IoU | Dice | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| U-Net | 0.569441 | 0.725661 | 0.712651 | 0.739156 |
| All-background | 0 | 0 | undefined | 0 |

These are internal resized-image metrics, not official KITTI bird's-eye-view scores. They are not directly comparable with the earlier eight-image test: the test membership changed. This is an initial baseline, not safety or robust-generalization evidence. Five test recordings, missing umm coverage, low resolution and aspect-ratio distortion remain important limitations.

A visual review of two worst, one middle-ranked and the best test image found severe road misses in the worst cases (including one with zero road IoU). Other examples show substantially better pavement coverage. This review is diagnostic; no configuration was changed in response. The local image panel is `storage/previews/kitti-full-v1/prediction-review.png`. Green indicates road; purple indicates ignored pixels.

Evidence: [training log](evidence/kitti-full-training.log), [timing](evidence/kitti-full-timing.json), [per-image U-Net results and counts](evidence/kitti-full-unet.json), [baseline](evidence/kitti-full-background.json), [seven passing Python tests](evidence/kitti-tests.txt).

## Reproduce

```sh
python -m worker.kitti_subset \
  --road-zip "$HOME/Downloads/data_road.zip" \
  --mapping-zip "$HOME/Downloads/devkit_road_mapping.zip" \
  --name kitti-full-v2 --counts 189 57 43 --seed 2026
python -m worker.train --train kitti-full-v2-train \
  --validation kitti-full-v2-validation --name kitti-full-unet-v2 --epochs 5 --device cpu
python -m worker.evaluate --dataset kitti-full-v2-internal_test \
  --model kitti-full-unet-v2 --out storage/manual/kitti-full-unet-v2
```

Use the project virtual-environment Python (or `"$PYTHON"` after sourcing the local workspace environment script). Existing names are protected against overwrite. In the dashboard, select `kitti-full-v1-internal_test` and `kitti-full-unet-v1` to submit a fresh Relay evaluation. The runs documented here used the standalone evaluation command; no new API job is claimed.

Downloaded images, previews and checkpoints stay out of Git. This work changed local code/manifests/documentation but has not been committed or pushed.
