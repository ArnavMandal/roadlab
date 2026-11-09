package main

import (
	"context"
	"crypto/rand"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"log/slog"
	"time"
)

//go:embed schema.sql
var schema string
var errConflict = errors.New("conflict or expired claim")
var errMissing = errors.New("not found")

type Store struct {
	pool  *pgxpool.Pool
	lease int
}
type Job struct {
	ID          string          `json:"id"`
	Request     json.RawMessage `json:"request"`
	Spec        json.RawMessage `json:"spec"`
	State       string          `json:"state"`
	Attempt     int             `json:"attempt"`
	MaxAttempts int             `json:"max_attempts"`
	Token       *string         `json:"token"`
	Lease       *time.Time      `json:"lease_until"`
	Created     time.Time       `json:"created_at"`
	Updated     time.Time       `json:"updated_at"`
	Available   time.Time       `json:"available_at"`
	Progress    float64         `json:"progress"`
	Error       string          `json:"error"`
	ResultSHA   *string         `json:"result_sha256"`
}

const columns = "id,request,spec,state,attempt_count,max_attempts,token,lease_until,created_at,updated_at,available_at,progress,error,result_sha256"

func scan(row pgx.Row) (j Job, err error) {
	err = row.Scan(&j.ID, &j.Request, &j.Spec, &j.State, &j.Attempt, &j.MaxAttempts, &j.Token, &j.Lease, &j.Created, &j.Updated, &j.Available, &j.Progress, &j.Error, &j.ResultSHA)
	if errors.Is(err, pgx.ErrNoRows) {
		err = errMissing
	}
	return
}
func id() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b)
}
func (s *Store) submit(ctx context.Context, key string, req, spec []byte, max int) (Job, error) {
	// Unique index serializes conflicting inserts. A second statement sees the winner
	// even if its transaction was invisible when INSERT began (READ COMMITTED).
	_, e := s.pool.Exec(ctx, `INSERT INTO jobs(id,idempotency_key,request,spec,state,max_attempts) VALUES($1,$2,$3,$4,'queued',$5) ON CONFLICT(idempotency_key) DO NOTHING`, id(), key, req, spec, max)
	if e != nil {
		return Job{}, e
	}
	j, e := scan(s.pool.QueryRow(ctx, "SELECT "+columns+" FROM jobs WHERE idempotency_key=$1", key))
	if e != nil {
		return j, e
	}
	var same bool
	e = s.pool.QueryRow(ctx, "SELECT request=$2::jsonb FROM jobs WHERE id=$1", j.ID, req).Scan(&same)
	if e == nil && !same {
		e = errConflict
	}
	return j, e
}
func (s *Store) get(ctx context.Context, jid string) (Job, error) {
	return scan(s.pool.QueryRow(ctx, "SELECT "+columns+" FROM jobs WHERE id=$1", jid))
}
func (s *Store) list(ctx context.Context) ([]Job, error) {
	rows, e := s.pool.Query(ctx, "SELECT "+columns+" FROM jobs ORDER BY created_at DESC LIMIT 200")
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Job{}
	for rows.Next() {
		j, e := scan(rows)
		if e != nil {
			return nil, e
		}
		out = append(out, j)
	}
	return out, rows.Err()
}
func (s *Store) reap(ctx context.Context) error {
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	rows, e := tx.Query(ctx, "SELECT id,token,attempt_count,max_attempts FROM jobs WHERE state='running' AND lease_until <= statement_timestamp() ORDER BY lease_until FOR UPDATE SKIP LOCKED LIMIT 100")
	if e != nil {
		return e
	}
	type expired struct {
		id, token string
		n, max    int
	}
	items := []expired{}
	for rows.Next() {
		var x expired
		if e = rows.Scan(&x.id, &x.token, &x.n, &x.max); e != nil {
			rows.Close()
			return e
		}
		items = append(items, x)
	}
	rows.Close()
	if rows.Err() != nil {
		return rows.Err()
	}
	for _, x := range items {
		if _, e = tx.Exec(ctx, "UPDATE attempts SET state='expired',finished_at=statement_timestamp(),error='lease expired' WHERE token=$1", x.token); e != nil {
			return e
		}
		state := "queued"
		if x.n >= x.max {
			state = "failed"
		}
		if _, e = tx.Exec(ctx, `UPDATE jobs SET state=$2,lease_until=NULL,error='lease expired',progress=0,available_at=statement_timestamp()+ make_interval(secs=>LEAST(60,power(2,attempt_count)::int)),updated_at=statement_timestamp() WHERE id=$1`, x.id, state); e != nil {
			return e
		}
		slog.Info("lease_expired", "job_id", x.id, "attempt_token", x.token, "next_state", state)
	}
	return tx.Commit(ctx)
}
func (s *Store) claim(ctx context.Context, worker string) (Job, error) {
	if e := s.reap(ctx); e != nil {
		return Job{}, e
	}
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return Job{}, e
	}
	defer tx.Rollback(ctx)
	j, e := scan(tx.QueryRow(ctx, "SELECT "+columns+" FROM jobs WHERE state='queued' AND available_at <= statement_timestamp() ORDER BY available_at,created_at FOR UPDATE SKIP LOCKED LIMIT 1"))
	if e != nil {
		return j, e
	}
	token := id()
	j, e = scan(tx.QueryRow(ctx, `UPDATE jobs SET state='running',attempt_count=attempt_count+1,token=$2,lease_until=statement_timestamp()+make_interval(secs=>$3),updated_at=statement_timestamp(),progress=0,error='' WHERE id=$1 RETURNING `+columns, j.ID, token, s.lease))
	if e != nil {
		return j, e
	}
	_, e = tx.Exec(ctx, "INSERT INTO attempts(token,job_id,number,worker,state) VALUES($1,$2,$3,$4,'running')", token, j.ID, j.Attempt, worker)
	if e != nil {
		return j, e
	}
	e = tx.Commit(ctx)
	if e == nil {
		slog.Info("claimed", "job_id", j.ID, "attempt", j.Attempt, "attempt_token", token, "worker", worker)
	}
	return j, e
}
func (s *Store) mutate(ctx context.Context, jid, token, action string, progress float64, message, sha string, retry bool) (Job, error) {
	tx, e := s.pool.Begin(ctx)
	if e != nil {
		return Job{}, e
	}
	defer tx.Rollback(ctx)
	j, e := scan(tx.QueryRow(ctx, "SELECT "+columns+" FROM jobs WHERE id=$1 FOR UPDATE", jid))
	if e != nil {
		return j, e
	}
	// Idempotent completion works even after lease expiry, but only for the exact
	// token and result digest already accepted by the first successful commit.
	if action == "complete" && j.State == "succeeded" && j.Token != nil && *j.Token == token && j.ResultSHA != nil && *j.ResultSHA == sha {
		return j, nil
	}
	var valid bool
	e = tx.QueryRow(ctx, "SELECT state='running' AND token=$2 AND lease_until>statement_timestamp() FROM jobs WHERE id=$1", jid, token).Scan(&valid)
	if e != nil {
		return j, e
	}
	if !valid {
		return j, errConflict
	}
	switch action {
	case "heartbeat":
		_, e = tx.Exec(ctx, `UPDATE jobs SET lease_until=statement_timestamp()+make_interval(secs=>$2),progress=GREATEST(progress,$3),updated_at=statement_timestamp() WHERE id=$1`, jid, s.lease, progress)
	case "complete":
		_, e = tx.Exec(ctx, "UPDATE jobs SET state='succeeded',lease_until=NULL,result_sha256=$2,progress=1,updated_at=statement_timestamp() WHERE id=$1", jid, sha)
		if e == nil {
			_, e = tx.Exec(ctx, "UPDATE attempts SET state='succeeded',finished_at=statement_timestamp() WHERE token=$1", token)
		}
	case "fail":
		state := "failed"
		if retry && j.Attempt < j.MaxAttempts {
			state = "queued"
		}
		_, e = tx.Exec(ctx, `UPDATE jobs SET state=$2,lease_until=NULL,error=$3,progress=0,available_at=statement_timestamp()+make_interval(secs=>LEAST(60,power(2,attempt_count)::int)),updated_at=statement_timestamp() WHERE id=$1`, jid, state, message)
		if e == nil {
			_, e = tx.Exec(ctx, "UPDATE attempts SET state='failed',error=$2,finished_at=statement_timestamp() WHERE token=$1", token, message)
		}
	default:
		return j, fmt.Errorf("unknown action")
	}
	if e != nil {
		return j, e
	}
	j, e = scan(tx.QueryRow(ctx, "SELECT "+columns+" FROM jobs WHERE id=$1", jid))
	if e != nil {
		return j, e
	}
	e = tx.Commit(ctx)
	if e == nil && action != "heartbeat" {
		slog.Info(action, "job_id", jid, "attempt_token", token, "state", j.State)
	}
	return j, e
}
