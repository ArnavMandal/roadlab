# Follow one job from submit to accepted result

1. The dashboard POSTs a registered dataset/model selection with an idempotency key. If a network response is lost, its retry keeps that key. A new intentional run gets a new key. Reloading the browser loses an in-flight key, so inspect existing jobs before resubmitting after a reload.
2. Go normalizes defaults, snapshots registry manifests and creates a queued database row. A different request under the same key gets HTTP 409.
3. A Python worker POSTs `/claim`. Go commits a short claim transaction containing a fresh token, lease and durable attempt. The worker receives the snapshotted specification.
4. Python creates `<job>/<token>/`. A background thread sends heartbeats while the main thread loads inputs and computes. Progress advances between images; this MVP has no per-layer progress.
5. The worker verifies input/checkpoint hashes, predicts road pixels, masks out ignored pixels, accumulates counts, and saves RGB, truth, prediction and overlay artifacts. It writes the result manifest last.
6. The worker submits the result digest. Go checks the file, locks the row, validates the current token and lease, and commits success with that digest. Only this attempt becomes visible through result/artifact endpoints.
7. The dashboard polls for the terminal state, loads metrics and artifacts, and shows the attempts that led to the accepted result.

Useful API examples (from a terminal):

```sh
curl -s http://127.0.0.1:8080/registry
curl -s http://127.0.0.1:8080/jobs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: example-demo-1' \
  -d '{"task":"evaluate","dataset":"synthetic-internal_test","model":"demo","max_attempts":3}'
curl -s http://127.0.0.1:8080/jobs
# Substitute a returned ID:
curl -s http://127.0.0.1:8080/jobs/JOB_ID
curl -s http://127.0.0.1:8080/jobs/JOB_ID/attempts
curl -s http://127.0.0.1:8080/jobs/JOB_ID/result
```

Repeat the same submission to see the existing job ID. Change `model` under that key to see a conflict. For queue-only failure injection:

```sh
curl -s http://127.0.0.1:8080/jobs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: retry-demo-1' \
  -d '{"task":"fake","duration":2,"fail_until":1,"max_attempts":3}'
```

Attempt 1 intentionally raises a retryable failure; attempt 2 succeeds after backoff. Set `invalid:true` to cause a terminal invalid-input failure, or set `fail_until` at least as high as `max_attempts` to exhaust retries. No executable commands are accepted in a task payload.

## Real crash recovery

Run `scripts/demo.py` with no other workers. Worker A starts a 7-second fake task; worker B starts a second. The script kills A with SIGKILL, so no graceful failure notification can happen. After the 4-second demo lease expires and backoff passes, B claims A's logical job with a different token. Its first attempt remains in history as expired, its second as succeeded. The script asserts exactly one succeeded attempt per job.

Next it resubmits the same key/payload, restarts the actual Go process, and repeats completion with the accepted token/digest. The returned job and result are unchanged. JSON logs include job IDs and tokens; the script's report includes database-backed attempts and accepted results. See `docs/evidence/` for the run actually collected here.

## Endpoint outline

| Method / path | Purpose |
| --- | --- |
| GET `/health`, `/registry` | Readiness and local registered configurations |
| POST `/jobs` | Idempotent submission via `Idempotency-Key` header |
| GET `/jobs` | Latest 200 jobs |
| GET `/jobs/{id}`, `/jobs/{id}/attempts` | State, progress, errors, history |
| POST `/claim` | `{worker}`; 204 means no ready job |
| POST `/jobs/{id}/heartbeat` | `{token, progress}` |
| POST `/jobs/{id}/fail` | `{token, error, retryable}` |
| POST `/jobs/{id}/complete` | `{token, sha256}` |
| GET `/jobs/{id}/result` | Accepted result JSON only |
| GET `/jobs/{id}/artifacts/{name}` | Accepted PNG by validated basename |

Malformed input: 400; unknown resources: 404; stale claim/key mismatch: 409; unexpected server failure: 500. Client timeouts do not mean a transaction rolled back. Retry idempotent submission/completion with the same identity. Claim itself is not idempotent: an unseen successful claim can remain leased until expiry.
