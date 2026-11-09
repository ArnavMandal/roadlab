# RoadLab + Relay

RoadLab tests how well an AI model identifies the road in an image. It compares the model’s predictions with labeled answers, calculates scores, and shows where the model made mistakes.

Relay manages those tests in the background. It saves jobs, assigns them to workers, and retries them if a worker crashes. If work runs more than once, it ensures only the current worker’s result is accepted.

You can try the project using generated images and a simple demo predictor—no dataset download or trained model is needed. These runs are clearly labeled **synthetic demo**. They show that the software works, not how well it performs on real roads.

This project tests models; it does not drive or control a vehicle.

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

For real data, follow the exact manual-download and manifest steps in the [dataset card](docs/dataset-card.md). Then:

```sh
.venv/bin/python -m worker.train --train kitti-train \
  --validation kitti-validation --name kitti-rgb-v1 --epochs 20 --device cpu
.venv/bin/python -m worker.evaluate --dataset kitti-internal_test \
  --model kitti-rgb-v1 --out storage/manual/kitti-rgb-v1
```

Twenty epochs is a starting command, not a validated training schedule. Do not tune on the internal test split. The trivial `all-background` model is also registered. Dashboard evaluations run these same model implementations through Relay.

## Read and explain

- [Architecture, state machine, transaction boundaries, crash windows](docs/architecture.md)
- [Submission-to-result walkthrough and failure recovery](docs/walkthrough.md)
- [Dataset encoding, provenance and splits](docs/dataset-card.md)
- [Model, tensors, loss and exact metric definitions](docs/model-card.md)
- [Explain-it-yourself questions and limitations](docs/learning.md)

**Remaining real-data work:** download KITTI using your account and terms, obtain and normalize the official raw-sequence mapping, import and inspect actual masks, then train and evaluate on real labeled data. The adapter's channel semantics were checked against the official devkit; a real KITTI import or training run has not happened. The project is operational with synthetic data, but real-data validation is not complete.
