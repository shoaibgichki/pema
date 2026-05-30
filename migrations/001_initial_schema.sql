-- ═══════════════════════════════════════════════════════════════════
-- PEMA — Supabase Database Schema
--
-- Run this in Supabase SQL Editor (https://supabase.com/dashboard)
-- Project → SQL Editor → New Query → Paste → Run
-- ═══════════════════════════════════════════════════════════════════

-- Enable UUID extension (usually enabled by default on Supabase)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── 1. Triage Sessions ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS triage_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status      VARCHAR(30)  NOT NULL DEFAULT 'consent_framing',
    channel     VARCHAR(20)  NOT NULL DEFAULT 'web',
    language    VARCHAR(5)   NOT NULL DEFAULT 'en',
    engine_version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─── 2. Messages ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS messages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID         NOT NULL REFERENCES triage_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(10)  NOT NULL,
    message_text TEXT        NOT NULL,
    turn_number INTEGER      NOT NULL DEFAULT 0,
    timestamp   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);

-- ─── 3. Session Facts ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS session_facts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID         NOT NULL UNIQUE REFERENCES triage_sessions(id) ON DELETE CASCADE,

    -- Extracted clinical facts
    chief_complaint  TEXT,
    body_region      VARCHAR(100),
    duration         VARCHAR(100),
    severity         VARCHAR(20),
    associated_symptoms TEXT,       -- JSON-encoded list
    age              INTEGER,
    sex              VARCHAR(10),
    is_pregnant      BOOLEAN,
    additional_context TEXT,

    -- Outcome (populated on triage completion)
    urgency     VARCHAR(20),
    specialty   VARCHAR(50),
    confidence  FLOAT
);

CREATE INDEX IF NOT EXISTS idx_session_facts_session_id ON session_facts(session_id);

-- ─── 4. Rule Events ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rule_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID         NOT NULL REFERENCES triage_sessions(id) ON DELETE CASCADE,
    rule_name   VARCHAR(50)  NOT NULL,
    severity    VARCHAR(20)  NOT NULL,
    evidence_snippet TEXT    NOT NULL,
    timestamp   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_events_session_id ON rule_events(session_id);

-- ─── 5. Model Audits ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS model_audits (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID         NOT NULL REFERENCES triage_sessions(id) ON DELETE CASCADE,
    prompt_version  VARCHAR(20) NOT NULL,
    model_name      VARCHAR(50) NOT NULL,
    structured_output_json JSONB,
    latency_ms      INTEGER,
    trace_id        VARCHAR(100),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_audits_session_id ON model_audits(session_id);

-- ─── Row Level Security (RLS) ──────────────────────────────────────
-- For the MVP, disable RLS so the backend service can access everything.
-- In production, add policies for API-level access control.

ALTER TABLE triage_sessions DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE session_facts DISABLE ROW LEVEL SECURITY;
ALTER TABLE rule_events DISABLE ROW LEVEL SECURITY;
ALTER TABLE model_audits DISABLE ROW LEVEL SECURITY;
