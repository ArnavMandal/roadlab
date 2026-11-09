CREATE TABLE IF NOT EXISTS jobs (
 id text PRIMARY KEY, idempotency_key text UNIQUE NOT NULL,
 request jsonb NOT NULL, spec jsonb NOT NULL,
 state text NOT NULL CHECK (state IN ('queued','running','succeeded','failed')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
 max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 8),
 token text, lease_until timestamptz,
 available_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 progress double precision NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
 error text NOT NULL DEFAULT '', result_sha256 text,
 CHECK ((state = 'running') = (lease_until IS NOT NULL)),
 CHECK ((state = 'succeeded') = (result_sha256 IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(available_at,created_at) WHERE state='queued';
CREATE INDEX IF NOT EXISTS jobs_expired ON jobs(lease_until) WHERE state='running';
CREATE TABLE IF NOT EXISTS attempts (
 token text PRIMARY KEY, job_id text NOT NULL REFERENCES jobs(id),
 number integer NOT NULL, worker text NOT NULL,
 state text NOT NULL CHECK (state IN ('running','succeeded','failed','expired')),
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 error text NOT NULL DEFAULT '', UNIQUE(job_id,number)
);
