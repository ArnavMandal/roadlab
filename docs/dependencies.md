# Recorded environment and dependency choices

Verified locally on macOS 26.0.1, arm64, 8 logical CPUs, Python 3.12.11, Node 24.1.0, Go 1.27.3, PostgreSQL 14.18 (existing Homebrew installation, separate database cluster). RAM and exact model were not collected because the sandbox denied the hardware query.

| Component | Pin / requirement | Record |
| --- | --- | --- |
| Go | language minimum 1.26; verified toolchain 1.27.3 | `relay/go.mod` |
| pgx | 5.7.6 | `relay/go.mod`, `go.sum` |
| PostgreSQL Compose | 16.13 | `compose.yaml` (not run here: Docker absent) |
| Next.js | 16.4.5 | `web/package.json`, `package-lock.json` |
| React / React DOM | 19.3.1 | package lock |
| TypeScript | 5.9.3 | package lock |
| PyTorch | 2.10.0 | `worker/requirements.txt`, `requirements-lock.txt` |
| NumPy | 2.2.6 | Python lock |
| Pillow | 11.3.0 | Python lock |

The npm registry's stable versions were checked when installing. Direct dependencies are exact pins, with transitive npm and Go locks. Python's fully pinned environment is in `requirements-lock.txt`; the short requirements file documents core choices. Lock records versions, not cross-platform binary identity. CUDA-specific wheel installation may require using PyTorch's official platform index; the delivered environment is macOS CPU/MPS-capable PyTorch, with tests performed on CPU.

Go was downloaded from the official distribution and its SHA-256 verified before extraction:
`go1.27.3.darwin-arm64.tar.gz` — `dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2`.

The repository does not require the locally downloaded toolchain. `scripts/setup.sh` uses the Go, Node and Python on your PATH and installs project-local dependencies. A local-only workspace convenience script reuses already installed tools and caches; it is excluded from Git.

## Storage

Measured during construction: approximately 404 MB repository including web dependencies/build and 1.6 GB workspace tooling/caches/database. Python environment ~569 MB, Go toolchain ~271 MB, PostgreSQL's initial cluster ~50 MB; synthetic data/checkpoint/artifacts initially ~1.3 MB. Subsequent tests/artifacts/builds add to those figures.

Plan approximately 3–5 GB for development, or 5–8 GB including downloaded and extracted KITTI; these are estimates, not measured KITTI installation sizes. The official base-kit download is listed around 0.5 GB. At this tiny U-Net size checkpoints are small; retained outputs accumulate per attempt and run. Source data, caches, virtualenvs, build output and artifacts are excluded from Git. No automatic cleanup deletes user data.

Source formatting used gofmt, Black 26.1.0 and Prettier 3.6.2. Formatters are not runtime dependencies.
