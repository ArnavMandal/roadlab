package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

var identifier = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,80}$`)
var digest = regexp.MustCompile(`^[a-f0-9]{64}$`)

type Request struct {
	Task        string  `json:"task"`
	Dataset     string  `json:"dataset,omitempty"`
	Model       string  `json:"model,omitempty"`
	Duration    float64 `json:"duration,omitempty"`
	FailUntil   int     `json:"fail_until,omitempty"`
	Invalid     bool    `json:"invalid,omitempty"`
	MaxAttempts int     `json:"max_attempts"`
}
type API struct {
	store    *Store
	root     *os.Root
	registry string
}

func hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func jsonOut(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}
func failure(w http.ResponseWriter, e error) {
	code := 500
	if errors.Is(e, errConflict) {
		code = 409
	}
	if errors.Is(e, errMissing) {
		code = 404
	}
	if code == 500 {
		slog.Error("request_failed", "error", e)
		e = errors.New("internal error; see Relay log")
	}
	jsonOut(w, code, map[string]string{"error": e.Error()})
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 65536))
	d.DisallowUnknownFields()
	e := d.Decode(v)
	if e == nil {
		var extra any
		if d.Decode(&extra) != io.EOF {
			e = errors.New("exactly one JSON object required")
		}
	}
	if e != nil {
		jsonOut(w, 400, map[string]string{"error": e.Error()})
		return false
	}
	return true
}
func (a *API) registryEntry(kind, name string) (map[string]any, []byte, error) {
	if !identifier.MatchString(name) {
		return nil, nil, errMissing
	}
	b, e := os.ReadFile(filepath.Join(a.registry, kind, name+".json"))
	if e != nil {
		return nil, nil, errMissing
	}
	var v map[string]any
	e = json.Unmarshal(b, &v)
	return v, b, e
}
func (a *API) spec(req Request) ([]byte, error) {
	spec := map[string]any{"task": req.Task, "synthetic_demo": false, "label": "fake queue workload"}
	if req.MaxAttempts < 1 || req.MaxAttempts > 8 {
		return nil, errors.New("max_attempts must be 1..8")
	}
	switch req.Task {
	case "fake":
		if req.Duration < 0 || req.Duration > 300 || req.FailUntil < 0 || req.FailUntil > 8 {
			return nil, errors.New("invalid fake workload limits")
		}
		spec["duration"] = req.Duration
		spec["fail_until"] = req.FailUntil
		spec["invalid"] = req.Invalid
	case "evaluate":
		d, db, e := a.registryEntry("datasets", req.Dataset)
		if e != nil {
			return nil, errors.New("unregistered dataset")
		}
		m, mb, e := a.registryEntry("models", req.Model)
		if e != nil {
			return nil, errors.New("unregistered model")
		}
		synthetic, _ := d["synthetic_demo"].(bool)
		if m["kind"] == "demo" && !synthetic {
			return nil, errors.New("demo predictor requires synthetic data")
		}
		if m["kind"] != "demo" && m["kind"] != "unet" && m["kind"] != "all_background" {
			return nil, errors.New("unsupported registered model kind")
		}
		spec["dataset"] = d
		spec["model"] = m
		spec["dataset_sha256"] = hash(db)
		spec["model_manifest_sha256"] = hash(mb)
		spec["synthetic_demo"] = synthetic
		spec["label"] = "internal image-space evaluation"
		if synthetic {
			spec["label"] = "synthetic demo"
		}
	default:
		return nil, errors.New("registered tasks: fake, evaluate")
	}
	return json.Marshal(spec)
}
func (a *API) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		if e := a.store.pool.Ping(r.Context()); e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /registry", func(w http.ResponseWriter, r *http.Request) {
		out := map[string]any{}
		for _, kind := range []string{"datasets", "models"} {
			items := []any{}
			files, _ := filepath.Glob(filepath.Join(a.registry, kind, "*.json"))
			for _, f := range files {
				name := strings.TrimSuffix(filepath.Base(f), ".json")
				v, _, e := a.registryEntry(kind, name)
				if e == nil {
					items = append(items, map[string]any{"id": name, "metadata": v})
				}
			}
			out[kind] = items
		}
		jsonOut(w, 200, out)
	})
	mux.HandleFunc("POST /jobs", func(w http.ResponseWriter, r *http.Request) {
		key := r.Header.Get("Idempotency-Key")
		if !identifier.MatchString(key) {
			jsonOut(w, 400, map[string]string{"error": "Idempotency-Key: 1..80 letters, digits, underscore or dash required"})
			return
		}
		var req Request
		if !decode(w, r, &req) {
			return
		}
		if req.MaxAttempts == 0 {
			req.MaxAttempts = 3
		}
		raw, _ := json.Marshal(req)
		// Resolve duplicates before mutable registry lookup. Original snapshots survive registry edits.
		old, e := scan(a.store.pool.QueryRow(r.Context(), "SELECT "+columns+" FROM jobs WHERE idempotency_key=$1", key))
		if e == nil {
			var same bool
			e = a.store.pool.QueryRow(r.Context(), "SELECT request=$2::jsonb FROM jobs WHERE id=$1", old.ID, raw).Scan(&same)
			if e != nil {
				failure(w, e)
				return
			}
			if !same {
				failure(w, errConflict)
				return
			}
			jsonOut(w, 200, old)
			return
		}
		if !errors.Is(e, errMissing) {
			failure(w, e)
			return
		}
		spec, e := a.spec(req)
		if e != nil {
			jsonOut(w, 400, map[string]string{"error": e.Error()})
			return
		}
		j, e := a.store.submit(r.Context(), key, raw, spec, req.MaxAttempts)
		if e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, j)
	})
	mux.HandleFunc("GET /jobs", func(w http.ResponseWriter, r *http.Request) {
		j, e := a.store.list(r.Context())
		if e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, j)
	})
	mux.HandleFunc("GET /jobs/{id}", func(w http.ResponseWriter, r *http.Request) {
		j, e := a.store.get(r.Context(), r.PathValue("id"))
		if e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, j)
	})
	mux.HandleFunc("GET /jobs/{id}/attempts", func(w http.ResponseWriter, r *http.Request) {
		rows, e := a.store.pool.Query(r.Context(), "SELECT json_build_object('token',token,'number',number,'worker',worker,'state',state,'started_at',started_at,'finished_at',finished_at,'error',error) FROM attempts WHERE job_id=$1 ORDER BY number", r.PathValue("id"))
		if e != nil {
			failure(w, e)
			return
		}
		defer rows.Close()
		out := []json.RawMessage{}
		for rows.Next() {
			var b []byte
			if e = rows.Scan(&b); e != nil {
				failure(w, e)
				return
			}
			out = append(out, b)
		}
		if rows.Err() != nil {
			failure(w, rows.Err())
			return
		}
		jsonOut(w, 200, out)
	})
	mux.HandleFunc("POST /claim", func(w http.ResponseWriter, r *http.Request) {
		var b struct {
			Worker string `json:"worker"`
		}
		if !decode(w, r, &b) {
			return
		}
		if !identifier.MatchString(b.Worker) {
			jsonOut(w, 400, map[string]string{"error": "invalid worker id"})
			return
		}
		j, e := a.store.claim(r.Context(), b.Worker)
		if errors.Is(e, errMissing) {
			w.WriteHeader(204)
			return
		}
		if e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, j)
	})
	mux.HandleFunc("POST /jobs/{id}/{action}", func(w http.ResponseWriter, r *http.Request) {
		var b struct {
			Token     string  `json:"token"`
			Progress  float64 `json:"progress"`
			Error     string  `json:"error"`
			Retryable bool    `json:"retryable"`
			SHA       string  `json:"sha256"`
		}
		if !decode(w, r, &b) {
			return
		}
		jid, action := r.PathValue("id"), r.PathValue("action")
		if !identifier.MatchString(jid) || !identifier.MatchString(b.Token) || b.Progress < 0 || b.Progress > 1 || len(b.Error) > 4096 {
			jsonOut(w, 400, map[string]string{"error": "invalid update"})
			return
		}
		if action != "heartbeat" && action != "complete" && action != "fail" {
			failure(w, errMissing)
			return
		}
		if action == "complete" {
			if !digest.MatchString(b.SHA) {
				jsonOut(w, 400, map[string]string{"error": "sha256 required"})
				return
			}
			f, e := a.root.Open(jid + "/" + b.Token + "/result.json")
			if e != nil {
				jsonOut(w, 400, map[string]string{"error": "result.json missing in attempt directory"})
				return
			}
			raw, e := io.ReadAll(io.LimitReader(f, 16<<20))
			f.Close()
			if e != nil || !json.Valid(raw) || hash(raw) != b.SHA {
				jsonOut(w, 400, map[string]string{"error": "result hash or JSON invalid"})
				return
			}
		}
		j, e := a.store.mutate(r.Context(), jid, b.Token, action, b.Progress, b.Error, b.SHA, b.Retryable)
		if e != nil {
			failure(w, e)
			return
		}
		jsonOut(w, 200, j)
	})
	mux.HandleFunc("GET /jobs/{id}/result", func(w http.ResponseWriter, r *http.Request) { a.artifact(w, r, "result.json") })
	mux.HandleFunc("GET /jobs/{id}/artifacts/{name}", func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("name")
		if !regexp.MustCompile(`^[a-zA-Z0-9_-]+\.png$`).MatchString(name) {
			failure(w, errMissing)
			return
		}
		a.artifact(w, r, name)
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, splitErr := net.SplitHostPort(r.Host)
		if splitErr != nil {
			host = r.Host
		}
		if host != "127.0.0.1" && host != "localhost" {
			jsonOut(w, 403, map[string]string{"error": "host forbidden"})
			return
		}

		// Reject browser cross-origin writes; no CORS is enabled. Next proxies /api.
		if origin := r.Header.Get("Origin"); origin != "" && origin != "http://localhost:3000" && origin != "http://127.0.0.1:3000" {
			jsonOut(w, 403, map[string]string{"error": "origin forbidden"})
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		mux.ServeHTTP(w, r)
	})
}
func (a *API) artifact(w http.ResponseWriter, r *http.Request, name string) {
	j, e := a.store.get(r.Context(), r.PathValue("id"))
	if e != nil {
		failure(w, e)
		return
	}
	if j.State != "succeeded" || j.Token == nil {
		failure(w, errMissing)
		return
	}
	f, e := a.root.Open(j.ID + "/" + *j.Token + "/" + name)
	if e != nil {
		failure(w, errMissing)
		return
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil || !st.Mode().IsRegular() {
		failure(w, errMissing)
		return
	}
	if name == "result.json" {
		raw, e := io.ReadAll(io.LimitReader(f, 16<<20))
		if e != nil || hash(raw) != *j.ResultSHA {
			failure(w, errors.New("accepted result changed on disk"))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(raw)
		return
	}
	http.ServeContent(w, r, name, st.ModTime(), f)
}
func env(k, fallback string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return fallback
}
func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	pool, e := pgxpool.New(ctx, env("DATABASE_URL", "postgres://roadlab:roadlab@127.0.0.1:54329/roadlab?sslmode=disable"))
	if e != nil {
		panic(e)
	}
	defer pool.Close()
	if _, e = pool.Exec(ctx, schema); e != nil {
		panic(e)
	}
	rootPath := env("ARTIFACT_ROOT", "storage/artifacts")
	if e = os.MkdirAll(rootPath, 0755); e != nil {
		panic(e)
	}
	root, e := os.OpenRoot(rootPath)
	if e != nil {
		panic(e)
	}
	defer root.Close()
	lease, e := strconv.Atoi(env("LEASE_SECONDS", "12"))
	if e != nil || lease < 2 {
		panic("LEASE_SECONDS must be >=2")
	}
	s := &Store{pool, lease}
	a := &API{s, root, env("REGISTRY_ROOT", "registry")}
	addr := env("RELAY_ADDR", "127.0.0.1:8080")
	if !strings.HasPrefix(addr, "127.0.0.1:") {
		panic("RELAY_ADDR must bind 127.0.0.1")
	}
	server := &http.Server{Addr: addr, Handler: a.routes(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		t := time.NewTicker(time.Second)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if e := s.reap(ctx); e != nil && ctx.Err() == nil {
					slog.Error("reap_failed", "error", e)
				}
			}
		}
	}()
	go func() {
		<-ctx.Done()
		c, stop := context.WithTimeout(context.Background(), 5*time.Second)
		defer stop()
		server.Shutdown(c)
	}()
	fmt.Println("Relay listening on http://" + addr)
	if e = server.ListenAndServe(); e != nil && !errors.Is(e, http.ErrServerClosed) {
		panic(e)
	}
}
