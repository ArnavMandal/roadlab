package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestHTTPContractAndArtifactContainment(t *testing.T) {
	s := testStore(t)
	dir := t.TempDir()
	root, e := os.OpenRoot(dir)
	if e != nil {
		t.Fatal(e)
	}
	defer root.Close()
	a := &API{s, root, t.TempDir()}
	handler := a.routes()
	call := func(method, path, key string, body any) (int, []byte) {
		t.Helper()
		raw, _ := json.Marshal(body)
		r := httptest.NewRequest(method, path, bytes.NewReader(raw))
		r.Host = "127.0.0.1:8080"
		if key != "" {
			r.Header.Set("Idempotency-Key", key)
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w.Code, w.Body.Bytes()
	}
	for _, body := range []any{map[string]any{"task": "shell"}, map[string]any{"task": "fake", "command": "whoami"}, map[string]any{"task": "fake", "max_attempts": 9}} {
		if code, _ := call("POST", "/jobs", "invalid", body); code != 400 {
			t.Fatal(code)
		}
	}
	payload := map[string]any{"task": "fake", "duration": 1, "max_attempts": 3}
	code, raw := call("POST", "/jobs", "same", payload)
	if code != 200 {
		t.Fatal(code, string(raw))
	}
	var j Job
	json.Unmarshal(raw, &j)
	code, again := call("POST", "/jobs", "same", payload)
	var duplicate Job
	json.Unmarshal(again, &duplicate)
	if code != 200 || j.ID != duplicate.ID {
		t.Fatal(code)
	}
	if code, _ = call("POST", "/jobs", "same", map[string]any{"task": "fake", "duration": 2}); code != 409 {
		t.Fatal(code)
	}
	code, raw = call("POST", "/claim", "", map[string]string{"worker": "http-worker"})
	if code != 200 {
		t.Fatal(code, string(raw))
	}
	json.Unmarshal(raw, &j)
	attemptDir := filepath.Join(dir, j.ID, *j.Token)
	if e = os.MkdirAll(attemptDir, 0755); e != nil {
		t.Fatal(e)
	}
	result := []byte(`{"kind":"fake"}`)
	os.WriteFile(filepath.Join(attemptDir, "result.json"), result, 0644)
	// In-progress artifacts are not visible.
	if code, _ = call("GET", "/jobs/"+j.ID+"/result", "", nil); code != 404 {
		t.Fatal(code)
	}
	for i := 0; i < 2; i++ {
		code, raw = call("POST", "/jobs/"+j.ID+"/complete", "", map[string]string{"token": *j.Token, "sha256": hash(result)})
		if code != 200 {
			t.Fatal(code, string(raw))
		}
	}
	if code, _ = call("GET", "/jobs/"+j.ID+"/result", "", nil); code != 200 {
		t.Fatal(code)
	}
	outside := filepath.Join(t.TempDir(), "secret.png")
	os.WriteFile(outside, []byte("private"), 0644)
	if e = os.Symlink(outside, filepath.Join(attemptDir, "escape.png")); e != nil {
		t.Fatal(e)
	}
	if code, _ = call("GET", "/jobs/"+j.ID+"/artifacts/escape.png", "", nil); code != 404 {
		t.Fatal("root escape", code)
	}
	if code, _ = call("GET", "/jobs/"+j.ID+"/artifacts/%2e%2e%2fsecret.png", "", nil); code == 200 {
		t.Fatal("traversal accepted")
	}
	r := httptest.NewRequest("POST", "/claim", bytes.NewBufferString(`{"worker":"evil"}`))
	r.Host = "127.0.0.1:8080"
	r.Header.Set("Origin", "https://untrusted.example")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	if w.Code != http.StatusForbidden {
		t.Fatal(w.Code)
	}
}
