# RoadLab + Relay

RoadLab tests how well an AI model identifies the road in an image. It compares the model’s predictions with labeled answers, calculates scores, and shows where the model made mistakes.

Relay manages those tests in the background. It saves jobs, assigns them to workers, and retries them if a worker crashes. If work runs more than once, it ensures only the current worker’s result is accepted.

You can try the project using generated images and a simple demo predictor—no dataset download or trained model is needed. These runs are clearly labeled **synthetic demo**. They show that the software works, not how well it performs on real roads.

This project tests models; it does not drive or control a vehicle.

## What has been verified?

**Relay is the main engineering focus.** Both fake workloads and real KITTI evaluations have passed a two-worker crash demonstration: kill one worker, reclaim its job, reject a stale completion, and preserve the accepted result across an API restart. Duplicate submissions and repeated completion requests return the existing result. Execution is at least once; only the valid attempt can publish the accepted result.

The current KITTI example uses a small RGB U-Net, recording-separated splits covering all three road categories, and aspect-preserving 384×128 inputs. Its 43-image internal test scored **79.33% road IoU, 88.48% F1/Dice, 92.38% precision, and 84.89% recall**. These are internal image-space scores, not official KITTI leaderboard results or driving-safety evidence. The split changed from earlier experiments, so those scores are not directly comparable.

[Real-workload recovery and per-category results](docs/kitti-v2-run.md) · [Queue design](docs/architecture.md)

## Why one repository?

RoadLab and Relay form one monorepo with separate components and native processes:

- `relay/`: Go API and reusable PostgreSQL queue core.
- `worker/`: Python API client, evaluation and model training.
- `web/`: Next.js dashboard; accesses Relay over HTTP, never PostgreSQL.
- `docs/` and `scripts/`: shared design, evidence and end-to-end workflows.

One commit can update their HTTP contract and tests together. Each component retains its own dependency files. No monorepo framework is needed. Relay's queue logic remains separate from segmentation, so it can be extracted later if another application needs an independent release cycle.

[Architecture and transaction boundaries](docs/architecture.md)

## Portable setup

Prerequisites: Go >=1.26, Python 3.12, Node >=20.9, npm, and Docker Compose. Tested versions and lockfiles: [dependencies](docs/dependencies.md). Native processes are used for everything except PostgreSQL.

```sh
./scripts/setup.sh
# Downloads pinned dependencies, builds Relay, generates the fixture.
docker compose up -d --wait
(cd web && npm run build)
./scripts/start.sh --production
```

For editing the dashboard: `./scripts/start.sh` uses Next's webpack development server. In a restricted environment without filesystem events, use `WATCHPACK_POLLING=true ./scripts/start.sh`. No cloud services or authentication are needed. Keep this unauthenticated development system bound to localhost.

Directory layout:

```text
relay/     HTTP API, generic queue transactions, SQL schema, integration tests
worker/    API client, fake workload, dataset adapter, U-Net, train/evaluate
web/       Next.js + TypeScript dashboard, CSS, HTTP proxy only (no database)
registry/  local dataset/model JSON manifests; snapshotted at submission
scripts/   setup, process supervisor, crash demo, benchmark
storage/   generated/downloaded data, checkpoints, artifacts (Git-ignored)
docs/      design, learning guide, data/model cards, measured verification
```

## Tests, real crash demo, benchmark

Use a PostgreSQL database where the test user may create schemas. Tests create unique schemas and remove only their own schemas.

```sh
export TEST_DATABASE_URL='postgres://roadlab:roadlab@127.0.0.1:54329/roadlab?sslmode=disable'
./scripts/test.sh
```

Stop other workers and API instances before the crash demonstration. It starts its own API on 8081, a dashboard on 3000, and two workers; injects a real SIGKILL; checks recovery, duplicate requests, repeated completion, and an API restart; then stops its own processes. It requires an idle queue.

```sh
.venv/bin/python scripts/demo.py
# Automated / no dashboard: .venv/bin/python scripts/demo.py --no-web
```

If using an existing virtual environment, use its Python executable instead of `.venv/bin/python`.

Benchmark requires a running Relay on 8080 and **no other workers**. It starts and stops its own workers. Keep fake-workload measurements separate from ML evaluation.

```sh
bin/relay                 # Terminal 1, from repository root
.venv/bin/python scripts/benchmark.py --jobs 30 --workers 2 --duration .1  # Terminal 2
```

Actual results and proof: [verification report](docs/verification.md). No uncollected measurements are reported.

## Train and evaluate

```sh
.venv/bin/python -m worker.train --train synthetic-train \
  --validation synthetic-validation --name my-smoke --epochs 2 --device cpu
.venv/bin/python -m worker.evaluate --dataset synthetic-internal_test \
  --model my-smoke --out storage/manual/my-smoke
```

Use a new model name for each training run. Checkpoint selection uses validation IoU, not internal-test IoU. `--device auto` chooses CUDA, then MPS, then CPU if available; only CPU was verified here. Deterministic operations may reject unsupported accelerator operations rather than silently changing reproducibility.

## Real KITTI workflow

Download the base kit and official sequence mapping yourself as described in the [dataset card](docs/dataset-card.md). The repository includes manifests and measured evidence, **not downloaded images or trained checkpoints**. The commands below use fresh names so they do not overwrite the recorded experiments:

```sh
.venv/bin/python -m worker.kitti_subset \
  --road-zip "$HOME/Downloads/data_road.zip" \
  --mapping-zip "$HOME/Downloads/devkit_road_mapping.zip" \
  --name kitti-local-v1 --counts 189 57 43 --seed 2026
.venv/bin/python -m worker.prepare_benchmark \
  --source kitti-local-v1 --name kitti-local-v2
.venv/bin/python -m worker.train --train kitti-local-v2-train \
  --validation kitti-local-v2-validation --name kitti-local-unet-v2 --epochs 12 --device cpu
```

Keep PostgreSQL running and stop other Relay/workers before testing recovery on this trained model:

```sh
.venv/bin/python scripts/demo.py --no-web \
  --dataset kitti-local-v2-internal_test --model kitti-local-unet-v2 \
  --comparison-model kitti-local-v2-background
```

The demo runs actual inference, kills a worker after it has started producing images, and checks recovery and stale-token rejection. It also evaluates the background baseline on the same split. Choose new dataset/model names when repeating setup; registered experiment names are protected against overwrite. If optional PyTorch device-plugin discovery stalls locally, prefix commands with `TORCH_DEVICE_BACKEND_AUTOLOAD=0`; the recorded CPU runs used that setting.

Select checkpoints using validation scores only. This is a versioned exploratory benchmark: the same source data appeared in earlier experiments, and old checkpoints must not be treated as clean comparison models for a newly assigned split. No further model search is required to demonstrate Relay.

## Read and explain

- [Architecture, state machine, transaction boundaries, crash windows](docs/architecture.md)
- [Submission-to-result walkthrough and failure recovery](docs/walkthrough.md)
- [Dataset encoding, provenance and splits](docs/dataset-card.md)
- [Model, tensors, loss and exact metric definitions](docs/model-card.md)
- [Explain-it-yourself questions and limitations](docs/learning.md)

Experiment history: [40-image smoke run](docs/kitti-small-run.md), [first full-data run](docs/kitti-full-run.md), and [current v2 run through Relay](docs/kitti-v2-run.md).
