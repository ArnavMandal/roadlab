package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"sync"
	"testing"
	"time"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("set TEST_DATABASE_URL for real PostgreSQL tests")
	}
	ctx := context.Background()
	admin, e := pgxpool.New(ctx, url)
	if e != nil {
		t.Fatal(e)
	}
	name := "test_" + id()
	if _, e = admin.Exec(ctx, "CREATE SCHEMA "+name); e != nil {
		t.Fatal(e)
	}
	cfg, e := pgxpool.ParseConfig(url)
	if e != nil {
		t.Fatal(e)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = name
	pool, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { pool.Close(); admin.Exec(ctx, "DROP SCHEMA "+name+" CASCADE"); admin.Close() })
	if _, e = pool.Exec(ctx, schema); e != nil {
		t.Fatal(e)
	}
	return &Store{pool, 2}
}
func submitTest(t *testing.T, s *Store, key string, max int) Job {
	t.Helper()
	j, e := s.submit(context.Background(), key, []byte(`{"task":"fake"}`), []byte(`{"task":"fake"}`), max)
	if e != nil {
		t.Fatal(e)
	}
	return j
}
func claimTest(t *testing.T, s *Store) Job {
	t.Helper()
	j, e := s.claim(context.Background(), "test-worker")
	if e != nil {
		t.Fatal(e)
	}
	return j
}
func expire(t *testing.T, s *Store, j Job) {
	t.Helper()
	if _, e := s.pool.Exec(context.Background(), "UPDATE jobs SET lease_until=statement_timestamp()-interval '1 second' WHERE id=$1", j.ID); e != nil {
		t.Fatal(e)
	}
}
func ready(t *testing.T, s *Store, j Job) {
	t.Helper()
	if _, e := s.pool.Exec(context.Background(), "UPDATE jobs SET available_at=statement_timestamp() WHERE id=$1", j.ID); e != nil {
		t.Fatal(e)
	}
}
func TestIdempotencyConcurrent(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	var wg sync.WaitGroup
	ids := make(chan string, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			j, e := s.submit(ctx, "same", []byte(`{"a":1,"b":2}`), []byte(`{}`), 3)
			if e != nil {
				t.Error(e)
				return
			}
			ids <- j.ID
		}()
	}
	wg.Wait()
	close(ids)
	seen := map[string]bool{}
	for x := range ids {
		seen[x] = true
	}
	if len(seen) != 1 {
		t.Fatal(seen)
	}
	_, e := s.submit(ctx, "same", []byte(`{"b":2,"a":1}`), []byte(`{}`), 3)
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.submit(ctx, "same", []byte(`{"a":9}`), []byte(`{}`), 3)
	if !errors.Is(e, errConflict) {
		t.Fatal(e)
	}
}
func TestConcurrentClaims(t *testing.T) {
	s := testStore(t)
	for i := 0; i < 20; i++ {
		submitTest(t, s, fmt.Sprint(i), 3)
	}
	var wg sync.WaitGroup
	ids := make(chan string, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			j, e := s.claim(context.Background(), "parallel")
			if e != nil {
				t.Error(e)
				return
			}
			ids <- j.ID
		}()
	}
	wg.Wait()
	close(ids)
	seen := map[string]bool{}
	for x := range ids {
		if seen[x] {
			t.Error("double claim", x)
		}
		seen[x] = true
	}
	if len(seen) != 20 {
		t.Fatal(len(seen))
	}
}
func TestExpiryStaleAndRepeatCompletion(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	submitTest(t, s, "recover", 3)
	first := claimTest(t, s)
	expire(t, s, first)
	if _, e := s.mutate(ctx, first.ID, *first.Token, "heartbeat", 0, "", "", false); !errors.Is(e, errConflict) {
		t.Fatal("expired heartbeat", e)
	}
	if e := s.reap(ctx); e != nil {
		t.Fatal(e)
	}
	ready(t, s, first)
	second := claimTest(t, s)
	if *first.Token == *second.Token || second.Attempt != 2 {
		t.Fatal(second)
	}
	for _, action := range []string{"heartbeat", "complete", "fail"} {
		if _, e := s.mutate(ctx, first.ID, *first.Token, action, 0, "", "abc", true); !errors.Is(e, errConflict) {
			t.Fatal(action, e)
		}
	}
	for i := 0; i < 2; i++ {
		j, e := s.mutate(ctx, second.ID, *second.Token, "complete", 1, "", "abc", false)
		if e != nil || j.State != "succeeded" {
			t.Fatal(j, e)
		}
	}
	if _, e := s.mutate(ctx, second.ID, *second.Token, "complete", 1, "", "different", false); !errors.Is(e, errConflict) {
		t.Fatal(e)
	}
	var n int
	s.pool.QueryRow(ctx, "SELECT count(*) FROM attempts WHERE state='succeeded'").Scan(&n)
	if n != 1 {
		t.Fatal(n)
	}
}
func TestHeartbeatKeepsLease(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	submitTest(t, s, "heartbeat", 3)
	j := claimTest(t, s)
	// Cross original expiry while extending with real database time.
	for i := 0; i < 4; i++ {
		time.Sleep(650 * time.Millisecond)
		if _, e := s.mutate(ctx, j.ID, *j.Token, "heartbeat", .5, "", "", false); e != nil {
			t.Fatal(e)
		}
		if e := s.reap(ctx); e != nil {
			t.Fatal(e)
		}
	}
	if _, e := s.claim(ctx, "other"); !errors.Is(e, errMissing) {
		t.Fatal(e)
	}
	current, e := s.get(ctx, j.ID)
	if e != nil || current.Attempt != 1 || current.State != "running" {
		t.Fatal(current, e)
	}
}
func TestRetryExhaustionAndInvalid(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	submitTest(t, s, "retry", 2)
	for i := 1; i <= 2; i++ {
		j := claimTest(t, s)
		after, e := s.mutate(ctx, j.ID, *j.Token, "fail", 0, "retryable", "", true)
		if e != nil {
			t.Fatal(e)
		}
		if i == 1 {
			if after.State != "queued" || !after.Available.After(after.Updated) {
				t.Fatal(after)
			}
			ready(t, s, j)
		} else if after.State != "failed" {
			t.Fatal(after)
		}
	}
	submitTest(t, s, "invalid", 3)
	j := claimTest(t, s)
	after, e := s.mutate(ctx, j.ID, *j.Token, "fail", 0, "invalid", "", false)
	if e != nil || after.State != "failed" {
		t.Fatal(after, e)
	}
	submitTest(t, s, "death", 1)
	j = claimTest(t, s)
	expire(t, s, j)
	if e = s.reap(ctx); e != nil {
		t.Fatal(e)
	}
	after, e = s.get(ctx, j.ID)
	if e != nil || after.State != "failed" {
		t.Fatal(after, e)
	}
}
func TestReconnectPreservesJobs(t *testing.T) {
	s := testStore(t)
	j := submitTest(t, s, "persist", 3)
	cfg := s.pool.Config()
	other, e := pgxpool.NewWithConfig(context.Background(), cfg)
	if e != nil {
		t.Fatal(e)
	}
	defer other.Close()
	s.pool.Close()
	restarted := &Store{other, 2}
	got, e := restarted.get(context.Background(), j.ID)
	if e != nil || got.ID != j.ID {
		t.Fatal(got, e)
	}
	claimTest(t, restarted)
}
