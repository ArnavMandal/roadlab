"use client";
import { useCallback, useEffect, useRef, useState } from "react";
type Metrics = {
  iou: number | null;
  dice: number | null;
  precision: number | null;
  recall: number | null;
};
type Job = {
  id: string;
  state: string;
  attempt: number;
  max_attempts: number;
  progress: number;
  error: string;
  created_at: string;
  lease_until: string | null;
  spec: { label: string; synthetic_demo: boolean; task: string };
  request: { dataset?: string; model?: string };
};
type Attempt = {
  token: string;
  number: number;
  worker: string;
  state: string;
  error: string;
  started_at: string;
  finished_at: string | null;
};
type Example = {
  id: string;
  metrics: Metrics;
  counts: Record<string, number>;
  artifacts: Record<string, string>;
};
type Result = {
  kind: string;
  label: string;
  synthetic_demo?: boolean;
  dataset_sha256?: string;
  metric_config?: object;
  metrics?: Metrics;
  counts?: Record<string, number>;
  mean_image_iou?: number | null;
  images?: Example[];
  worst_ids?: string[];
  provenance?: object;
  preprocessing?: object;
};
type Entry = {
  id: string;
  metadata: {
    name: string;
    synthetic_demo?: boolean;
    role?: string;
    kind?: string;
  };
};
async function api<T>(
  path: string,
  signal?: AbortSignal,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch("/api" + path, { ...init, signal, cache: "no-store" });
  if (!r.ok) {
    let message = `Relay unavailable (${r.status})`;
    try {
      message = (await r.json()).error || message;
    } catch {}
    throw new Error(message);
  }
  return r.json();
}
const pct = (n: number | null | undefined) =>
  n == null ? "—" : (n * 100).toFixed(2) + "%";
function MetricGrid({ result }: { result: Result }) {
  return (
    <>
      <div className="metrics">
        {Object.entries(result.metrics || {}).map(([key, value]) => (
          <div key={key}>
            <span>Road {key}</span>
            <strong>{pct(value)}</strong>
          </div>
        ))}
      </div>
      <p className="muted">
        Micro aggregate ·{" "}
        {Object.entries(result.counts || {})
          .map(([k, v]) => `${k.toUpperCase()} ${v.toLocaleString()}`)
          .join(" / ")}{" "}
        · Mean image IoU {pct(result.mean_image_iou)}
      </p>
    </>
  );
}
export default function Home() {
  const [registry, setRegistry] = useState<{
    datasets: Entry[];
    models: Entry[];
  }>({ datasets: [], models: [] });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [dataset, setDataset] = useState("synthetic-internal_test");
  const [model, setModel] = useState("demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [detailError, setDetailError] = useState("");
  const [example, setExample] = useState("");
  const [view, setView] = useState("overlay");
  const [compareId, setCompareId] = useState("");
  const [comparison, setComparison] = useState<Result | null>(null);
  const [compareError, setCompareError] = useState("");
  const pending = useRef<{ payload: string; key: string } | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [list, reg] = await Promise.all([
          api<Job[]>("/jobs", ctl.signal),
          api<{ datasets: Entry[]; models: Entry[] }>("/registry", ctl.signal),
        ]);
        setJobs(list);
        setRegistry(reg);
        setError("");
      } catch (e) {
        if (!ctl.signal.aborted) setError((e as Error).message);
      } finally {
        if (!ctl.signal.aborted) {
          setLoading(false);
          timer = setTimeout(poll, 2500);
        }
      }
    }
    poll();
    return () => {
      ctl.abort();
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    setJob(null);
    setResult(null);
    setAttempts([]);
    setExample("");
    setDetailError("");
    setCompareId("");
    if (!selected) return;
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [j, a] = await Promise.all([
          api<Job>(`/jobs/${selected}`, ctl.signal),
          api<Attempt[]>(`/jobs/${selected}/attempts`, ctl.signal),
        ]);
        setJob(j);
        setAttempts(a);
        if (j.state === "succeeded") {
          const r = await api<Result>(`/jobs/${selected}/result`, ctl.signal);
          setResult(r);
          setExample((current) => current || r.worst_ids?.[0] || "");
        }
        setDetailError("");
        if (!ctl.signal.aborted && !["succeeded", "failed"].includes(j.state))
          timer = setTimeout(poll, 1500);
      } catch (e) {
        if (!ctl.signal.aborted) {
          setDetailError((e as Error).message);
          timer = setTimeout(poll, 3000);
        }
      }
    }
    poll();
    return () => {
      ctl.abort();
      clearTimeout(timer);
    };
  }, [selected]);
  useEffect(() => {
    setComparison(null);
    setCompareError("");
    if (!compareId) return;
    const ctl = new AbortController();
    api<Result>(`/jobs/${compareId}/result`, ctl.signal)
      .then(setComparison)
      .catch((e) => {
        if (!ctl.signal.aborted) setCompareError(e.message);
      });
    return () => ctl.abort();
  }, [compareId]);
  const submit = useCallback(async () => {
    setBusy(true);
    setError("");
    const payload = JSON.stringify({
      task: "evaluate",
      dataset,
      model,
      max_attempts: 3,
    });
    if (pending.current?.payload !== payload)
      pending.current = { payload, key: crypto.randomUUID() };
    try {
      const j = await api<Job>("/jobs", undefined, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": pending.current.key,
        },
        body: payload,
      });
      pending.current = null;
      setSelected(j.id);
      setJobs((prev) => [j, ...prev.filter((x) => x.id !== j.id)]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [dataset, model]);
  const compatible = !!(
    result &&
    comparison &&
    result.kind === "evaluation" &&
    comparison.kind === "evaluation" &&
    result.dataset_sha256 === comparison.dataset_sha256 &&
    JSON.stringify(result.metric_config) ===
      JSON.stringify(comparison.metric_config) &&
    JSON.stringify(result.preprocessing) ===
      JSON.stringify(comparison.preprocessing)
  );
  const image = result?.images?.find((x) => x.id === example);
  const active = jobs.filter((x) => x.state === "running").length;
  return (
    <main>
      <header>
        <a className="brand" href="/" aria-label="RoadLab home">
          <span className="brandmark">
            R<span>↗</span>
          </span>
          <div>
            RoadLab<small>PERCEPTION WORKBENCH</small>
          </div>
        </a>
        <span className="local">
          <i /> LOCAL / OFFLINE
        </span>
      </header>
      <section className="intro">
        <div>
          <p className="eyebrow">EVALUATE. INSPECT. UNDERSTAND.</p>
          <h1>
            A clearer view
            <br />
            of road segmentation.
          </h1>
          <p>
            Run reproducible evaluations. Inspect the failures.
            <br />
            Let Relay handle the work between.
          </p>
        </div>
        <div className="queue-summary">
          <span className="eyebrow">RELAY / QUEUE</span>
          <strong>{loading ? "—" : active.toString().padStart(2, "0")}</strong>
          <span>active workers’ jobs</span>
          <small>
            At-least-once execution
            <br />
            Lease-protected results
          </small>
        </div>
      </section>
      <div className="notice">
        <span>↳</span>
        <p>
          <strong>Offline evaluation, with honest boundaries.</strong> Synthetic
          demo runs test this pipeline and its recovery. Their metrics do not
          measure real driving performance.
        </p>
      </div>
      {error && (
        <div role="alert" className="error">
          {error}{" "}
          <small>
            Start Relay and PostgreSQL, then wait for the next poll. If
            submission was interrupted, retrying reuses its idempotency key.
          </small>
        </div>
      )}
      <section className="panel submit">
        <div>
          <p className="eyebrow">01 / NEW EVALUATION</p>
          <h2>Set up a run</h2>
        </div>
        <label>
          Dataset split
          <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
            {registry.datasets
              .filter((x) => x.metadata.role !== "train")
              .map((x) => (
                <option key={x.id} value={x.id}>
                  {x.metadata.name}
                  {x.metadata.synthetic_demo ? " · synthetic demo" : ""}
                </option>
              ))}
          </select>
        </label>
        <label>
          Model checkpoint
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {registry.models.map((x) => (
              <option key={x.id} value={x.id}>
                {x.metadata.name}
                {x.metadata.kind === "demo" ? " · synthetic demo" : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          onClick={submit}
          disabled={
            busy || !registry.datasets.length || !registry.models.length
          }
        >
          {busy ? "Submitting…" : "Evaluate →"}
        </button>
      </section>
      <div className="workspace">
        <section className="panel runs">
          <div className="section-title">
            <div>
              <p className="eyebrow">02 / RUN HISTORY</p>
              <h2>Evaluations</h2>
            </div>
            <span className="count">{jobs.length}</span>
          </div>
          <p className="muted">Latest 200 jobs · updates every 2.5 seconds</p>
          {loading ? (
            <p className="empty">Connecting to Relay…</p>
          ) : !jobs.length ? (
            <p className="empty">
              No jobs yet. Submit your first evaluation above.
            </p>
          ) : (
            <div className="run-list">
              {jobs.map((j) => (
                <button
                  key={j.id}
                  className={`run ${selected === j.id ? "selected" : ""}`}
                  onClick={() => setSelected(j.id)}
                >
                  <div>
                    <b>{j.request.model || "Fake workload"}</b>
                    <span className={`status ${j.state}`}>{j.state}</span>
                  </div>
                  <p>{j.request.dataset || "Queue reliability test"}</p>
                  <small>
                    {j.spec.label} · {j.id.slice(0, 8)}
                  </small>
                  <progress max={1} value={j.progress} />
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="panel detail">
          <p className="eyebrow">03 / INSPECTION</p>
          {!selected ? (
            <div className="empty detail-empty">
              <span>◎</span>
              <h2>Every result has a story.</h2>
              <p>
                Select a run to inspect its metrics,
                <br />
                predictions, and attempt history.
              </p>
            </div>
          ) : (
            <>
              {detailError && (
                <p className="error" role="alert">
                  {detailError}
                </p>
              )}
              {!job ? (
                <p>Loading run…</p>
              ) : (
                <>
                  <div className="section-title">
                    <h2>{job.request.model || "Fake workload"}</h2>
                    <span className={`status ${job.state}`}>{job.state}</span>
                  </div>
                  <p className="run-label">{job.spec.label}</p>
                  <p className="muted mono">{job.id}</p>
                  <div className="progress-row">
                    <progress max={1} value={job.progress} />
                    <span>{Math.round(job.progress * 100)}%</span>
                  </div>
                  {job.error && <p className="error">{job.error}</p>}
                  {result && (
                    <>
                      <MetricGrid result={result} />
                      {image && (
                        <>
                          <div className="image-toolbar">
                            <label>
                              Example
                              <select
                                value={example}
                                onChange={(e) => setExample(e.target.value)}
                              >
                                {result.images?.map((x) => (
                                  <option key={x.id}>{x.id}</option>
                                ))}
                              </select>
                            </label>
                            <label>
                              View
                              <select
                                value={view}
                                onChange={(e) => setView(e.target.value)}
                              >
                                {[
                                  ["original", "Original RGB"],
                                  ["ground_truth", "Ground truth"],
                                  ["prediction", "Prediction"],
                                  ["gt_overlay", "Ground truth overlay"],
                                  ["overlay", "Prediction overlay"],
                                ].map(([v, l]) => (
                                  <option key={v} value={v}>
                                    {l}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </div>
                          <div className="image-frame">
                            <img
                              src={`/api/jobs/${job.id}/artifacts/${image.artifacts[view]}`}
                              alt={`${view} for ${image.id}`}
                            />
                            <span>ROAD IoU {pct(image.metrics.iou)}</span>
                          </div>
                          <p className="muted">
                            Green: road · Purple: ignored area · Gray: ignored
                            mask pixels
                          </p>
                          <h3>Lowest road IoU</h3>
                          <div className="worst">
                            {result.worst_ids?.map((id) => {
                              const x = result.images?.find((i) => i.id === id);
                              return (
                                <button
                                  key={id}
                                  onClick={() => setExample(id)}
                                  className={example === id ? "chosen" : ""}
                                >
                                  <span>{id}</span>
                                  <b>{pct(x?.metrics.iou)}</b>
                                </button>
                              );
                            })}
                          </div>
                        </>
                      )}
                      {result.kind === "evaluation" && (
                        <div className="comparison">
                          <h3>Compare a completed run</h3>
                          <select
                            aria-label="Comparison run"
                            value={compareId}
                            onChange={(e) => setCompareId(e.target.value)}
                          >
                            <option value="">Select a run…</option>
                            {jobs
                              .filter(
                                (j) =>
                                  j.id !== selected &&
                                  j.state === "succeeded" &&
                                  j.spec.task === "evaluate",
                              )
                              .map((j) => (
                                <option value={j.id} key={j.id}>
                                  {j.request.model} / {j.id.slice(0, 8)}
                                </option>
                              ))}
                          </select>
                          {compareError && <p role="alert">{compareError}</p>}
                          {compareId && !comparison && !compareError && (
                            <p>Loading comparison…</p>
                          )}
                          {comparison &&
                            (compatible ? (
                              <>
                                <p className="muted">
                                  Same dataset manifest, preprocessing, and
                                  metric configuration.
                                </p>
                                <table>
                                  <thead>
                                    <tr>
                                      <th>Road metric</th>
                                      <th>This run</th>
                                      <th>Compared run</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {Object.keys(result.metrics || {}).map(
                                      (k) => (
                                        <tr key={k}>
                                          <td>{k}</td>
                                          <td>
                                            {pct(
                                              result.metrics?.[
                                                k as keyof Metrics
                                              ],
                                            )}
                                          </td>
                                          <td>
                                            {pct(
                                              comparison.metrics?.[
                                                k as keyof Metrics
                                              ],
                                            )}
                                          </td>
                                        </tr>
                                      ),
                                    )}
                                  </tbody>
                                </table>
                              </>
                            ) : (
                              <p className="error">
                                Comparison unavailable: dataset split,
                                preprocessing, or metric configuration differs.
                              </p>
                            ))}
                        </div>
                      )}
                      <details>
                        <summary>Provenance & metric configuration</summary>
                        <pre>
                          {JSON.stringify(
                            {
                              metric_config: result.metric_config,
                              dataset_sha256: result.dataset_sha256,
                              provenance: result.provenance,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    </>
                  )}
                  <h3>
                    Attempt history{" "}
                    <span className="muted">
                      {job.attempt}/{job.max_attempts}
                    </span>
                  </h3>
                  {attempts.length === 0 ? (
                    <p className="muted">
                      Waiting for a worker to claim this job.
                    </p>
                  ) : (
                    attempts.map((a) => (
                      <div className="attempt" key={a.token}>
                        <div>
                          <b>
                            #{a.number} · {a.worker}
                          </b>
                          <span className={`status ${a.state}`}>{a.state}</span>
                        </div>
                        <small>
                          {new Date(a.started_at).toLocaleString()} ·{" "}
                          {a.finished_at
                            ? "finished " +
                              new Date(a.finished_at).toLocaleTimeString()
                            : "lease " +
                              (job.lease_until
                                ? new Date(job.lease_until).toLocaleTimeString()
                                : "—")}
                        </small>
                        <code>{a.token}</code>
                        {a.error && <p>{a.error}</p>}
                      </div>
                    ))
                  )}
                </>
              )}
            </>
          )}
        </section>
      </div>
      <footer>
        <span>ROADLAB / POWERED BY RELAY</span>
        <span>RGB only. Image-space metrics. No leaderboard claims.</span>
      </footer>
    </main>
  );
}
