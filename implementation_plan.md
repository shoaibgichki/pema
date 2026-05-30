# PEMA — Phase-by-Phase Implementation Plan

> AI-Powered Healthcare Triage Chatbot — MVP Build Plan  
> Based on [PRD.md](file:///d:/pema/PRD.md) v1.0 and [mvpArchitecture.md](file:///d:/pema/mvpArchitecture.md)

---

## Overview

This plan covers the complete construction of the PEMA MVP across **6 phases**, directly mirroring the PRD's development roadmap (Section 11). Each phase is independently testable, and I will pause for your approval before proceeding to the next.

**Tech Stack:** Python 3.12 · FastAPI · Pydantic v2 · PostgreSQL (Supabase) · OpenAI Responses API

---

## Project Structure

```
d:\pema\
├── PRD.md
├── mvpArchitecture.md
├── pyproject.toml                    # Project metadata, dependencies
├── .env.example                      # Template for env vars (DB URL, OpenAI key)
├── alembic.ini                       # DB migration config
├── alembic/
│   └── versions/                     # Migration scripts
├── app/
│   ├── __init__.py
│   ├── main.py                       # FastAPI app factory, middleware, CORS
│   ├── config.py                     # Settings via pydantic-settings (.env)
│   ├── database.py                   # Async SQLAlchemy engine & session factory
│   ├── models/                       # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── session.py                # TriageSession
│   │   ├── message.py                # Message
│   │   ├── fact.py                   # SessionFact
│   │   ├── rule_event.py             # RuleEvent
│   │   └── model_audit.py            # ModelAudit
│   ├── schemas/                      # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── session.py                # CreateSession, SessionResponse, etc.
│   │   ├── message.py                # SendMessage, MessageResponse
│   │   ├── fact.py                   # ExtractedFacts (LLM output schema)
│   │   ├── admin.py                  # Admin list/detail responses
│   │   └── enums.py                  # Specialty, Urgency, SessionStatus, etc.
│   ├── api/                          # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── sessions.py               # /sessions endpoints
│   │   └── admin.py                  # /admin endpoints
│   ├── engine/                       # Core triage engine (channel-independent)
│   │   ├── __init__.py
│   │   ├── orchestrator.py           # Main turn-processing pipeline
│   │   ├── session_manager.py        # Session lifecycle (create, update, close)
│   │   ├── fact_extractor.py         # LLM-based fact extraction
│   │   ├── safety_rules.py           # Deterministic red-flag detection
│   │   ├── policy_engine.py          # Next-action decision logic
│   │   ├── response_composer.py      # LLM-based response generation
│   │   └── audit_logger.py           # Structured audit logging
│   └── prompts/                      # LLM prompt templates (versioned)
│       ├── fact_extraction.py
│       └── response_composition.py
├── tests/
│   ├── conftest.py                   # Fixtures (test DB, client, mock LLM)
│   ├── test_safety_rules.py          # Red-flag detection unit tests
│   ├── test_policy_engine.py         # Policy engine unit tests
│   ├── test_api.py                   # API integration tests
│   ├── test_scenarios.py             # 15 PRD end-to-end test scenarios
│   └── test_fact_extractor.py        # Fact extraction tests
└── sandbox/                          # Web test UI (Phase 6)
    ├── index.html
    ├── style.css
    └── app.js
```

---

## Phase 1 — Deterministic Skeleton

**Goal:** A working FastAPI backend with sessions, schemas, safety rules, enums, and a basic policy engine — **no LLM calls**. This proves the control plane works before adding AI.

**PRD Coverage:** FR-01.2 (partial — schemas), FR-03.1–FR-03.5, FR-04.1–FR-04.2 (enums), FR-05.1–FR-05.4, FR-06.1–FR-06.2, FR-07.1–FR-07.3, NFR-02, NFR-08–NFR-10

---

### 1.1 Project Bootstrap

#### [NEW] [pyproject.toml](file:///d:/pema/pyproject.toml)

- Project metadata and dependency declaration using `pyproject.toml` with a standard `[project]` section.
- **Core dependencies:** `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `pydantic>=2.0`, `pydantic-settings`, `alembic`, `python-dotenv`, `httpx` (for async OpenAI later)
- **Dev dependencies:** `pytest`, `pytest-asyncio`, `httpx` (test client), `ruff` (linter)

#### [NEW] [.env.example](file:///d:/pema/.env.example)

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/pema
OPENAI_API_KEY=sk-...
ENGINE_VERSION=1.0.0
LOG_LEVEL=INFO
```

#### [NEW] [app/config.py](file:///d:/pema/app/config.py)

- `Settings` class using `pydantic-settings` `BaseSettings`:
  - `database_url: str`
  - `openai_api_key: str = ""`  (empty for Phase 1)
  - `engine_version: str = "1.0.0"`
  - `log_level: str = "INFO"`
  - `max_follow_up_turns: int = 8`  (FR-02.3)

---

### 1.2 Enums & Schemas

#### [NEW] [app/schemas/enums.py](file:///d:/pema/app/schemas/enums.py)

All constrained enums as defined in PRD §6:

```python
class Specialty(str, Enum):
    GENERAL_PRACTITIONER = "general_practitioner"
    PEDIATRICIAN = "pediatrician"
    GYNECOLOGIST = "gynecologist"
    DERMATOLOGIST = "dermatologist"
    ENT = "ent"
    PULMONOLOGIST = "pulmonologist"
    GASTROENTEROLOGIST = "gastroenterologist"
    ORTHOPEDIST = "orthopedist"
    NEUROLOGIST = "neurologist"
    UROLOGIST = "urologist"
    PSYCHIATRIST = "psychiatrist"
    EMERGENCY_DEPARTMENT = "emergency_department"

class Urgency(str, Enum):
    EMERGENCY = "emergency"
    URGENT = "urgent"
    ROUTINE = "routine"

class SessionStatus(str, Enum):
    CONSENT_FRAMING = "consent_framing"
    CHIEF_COMPLAINT = "chief_complaint"
    FACT_GATHERING = "fact_gathering"
    SPECIALTY_ROUTING = "specialty_routing"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"

class MessageRole(str, Enum):
    USER = "user"
    SYSTEM = "system"

class Language(str, Enum):
    EN = "en"
    UR = "ur"
```

#### [NEW] [app/schemas/session.py](file:///d:/pema/app/schemas/session.py)

- `CreateSessionRequest`: `language: Language = Language.EN`
- `SessionResponse`: `id, status, language, created_at, updated_at, engine_version, framing_message`
- `CloseSessionRequest`: `reason: str | None`

#### [NEW] [app/schemas/message.py](file:///d:/pema/app/schemas/message.py)

- `SendMessageRequest`: `text: str`
- `MessageResponse`: `session_id, session_status, system_message, extracted_facts: ExtractedFacts | None, triggered_rules: list[RuleEvent] | None`

#### [NEW] [app/schemas/fact.py](file:///d:/pema/app/schemas/fact.py)

- `ExtractedFacts` (Pydantic model — this is the LLM's structured output target):
  - `chief_complaint: str | None`
  - `body_region: str | None`
  - `duration: str | None`
  - `severity: str | None`  (mild / moderate / severe)
  - `associated_symptoms: list[str]`
  - `age: int | None`
  - `sex: str | None`
  - `is_pregnant: bool | None`
  - `additional_context: str | None`

#### [NEW] [app/schemas/admin.py](file:///d:/pema/app/schemas/admin.py)

- `SessionSummary`: for `/admin/sessions` list view
- `SessionDetail`: full detail with messages, facts, rule events, model audits

---

### 1.3 Database Models (SQLAlchemy Async)

#### [NEW] [app/database.py](file:///d:/pema/app/database.py)

- Async engine via `create_async_engine(settings.database_url)`
- `async_session_maker` using `async_sessionmaker`
- `get_db()` dependency for FastAPI DI

#### [NEW] [app/models/session.py](file:///d:/pema/app/models/session.py)

`TriageSession` table matching PRD §6.1:
- `id` (UUID, PK), `status` (SessionStatus), `channel` (default "web"), `language`, `created_at`, `updated_at`, `engine_version`

#### [NEW] [app/models/message.py](file:///d:/pema/app/models/message.py)

`Message` table: `id`, `session_id` (FK), `role`, `message_text`, `timestamp`, `turn_number`

#### [NEW] [app/models/fact.py](file:///d:/pema/app/models/fact.py)

`SessionFact` table: All fields from `ExtractedFacts` schema, plus `session_id` (FK), `urgency`, `specialty`, `confidence`

#### [NEW] [app/models/rule_event.py](file:///d:/pema/app/models/rule_event.py)

`RuleEvent` table: `id`, `session_id` (FK), `rule_name`, `severity`, `evidence_snippet`, `timestamp`

#### [NEW] [app/models/model_audit.py](file:///d:/pema/app/models/model_audit.py)

`ModelAudit` table: `id`, `session_id` (FK), `prompt_version`, `model_name`, `structured_output_json` (JSONB), `latency_ms`, `trace_id`

#### Database Migrations

- Initialize Alembic with `alembic init alembic`
- Create initial migration for all 5 tables
- Migration runs automatically in test fixtures; manual `alembic upgrade head` for dev

---

### 1.4 Safety Rules Engine

#### [NEW] [app/engine/safety_rules.py](file:///d:/pema/app/engine/safety_rules.py)

**This is a critical safety module — fully deterministic, no LLM involvement (FR-03.2, NFR-03).**

- `SAFETY_RULES` registry: a list of rule definitions, each with:
  - `rule_id`: str (e.g., `"RF-001"`)
  - `description`: str
  - `patterns`: dict with `en` and `ur` keyword lists (§9.3)
  - `combination_logic`: how patterns must combine (AND / OR / threshold)
  - `action`: `"emergency"` or `"urgent"`
  - `crisis_info`: optional (for RF-004, suicidal ideation)

- `check_safety_rules(raw_text: str, extracted_facts: ExtractedFacts | None) -> list[RuleEvent]`:
  - Runs against **both** raw user text AND structured facts (belt-and-suspenders)
  - Case-insensitive matching
  - Checks both English and Roman Urdu variants for every rule
  - Returns list of triggered `RuleEvent` objects

**MVP Rules (PRD §8):**

| Rule | English Patterns | Roman Urdu Patterns | Logic |
|------|-----------------|---------------------|-------|
| RF-001 | chest pain + shortness of breath | seenay mein dard + saans (ki takleef / nahi aa rahi / mushkil) | AND |
| RF-002 | severe bleeding, uncontrolled bleeding, hemorrhage | bohat khoon, khoon band nahi ho raha | ANY |
| RF-003 | loss of consciousness, fainted, passed out, unconscious | hosh nahi, behosh, gir gaya/gayi | ANY |
| RF-004 | suicidal, want to die, kill myself, self-harm, end my life | marna chahta/chahti, khudkushi, apne aap ko | ANY |
| RF-005 | sudden numbness, slurred speech, vision loss, severe headache | achanak sun, zuban ladkhadana, nazar, shadeed sar dard | ANY 2+ |
| RF-006 | throat swelling, can't breathe, face swelling, anaphylaxis | gala sujan, saans nahi, chehra sujan | ANY 2+ |
| RF-007 | severe abdominal pain + fever + vomiting | shadeed pet dard + bukhar + ulti | AND (all 3) |
| RF-008 | high fever (>104°F / 40°C) + child under 5 | tez bukhar + bacha (age check) | AND (fact-based) |
| RF-009 | seizure, convulsion, fit | dora, mirgi, jhatke | ANY |
| RF-010 | pregnant + bleeding / severe pain | hamal/pregnant + khoon/shadeed dard | AND |

> [!IMPORTANT]
> RF-004 (suicidal ideation) must additionally return crisis helpline numbers in the response (Pakistan: Umang helpline 0311-7786264, Taskeen: 0316-8275336).

---

### 1.5 Session Manager & Policy Engine (Stub)

#### [NEW] [app/engine/session_manager.py](file:///d:/pema/app/engine/session_manager.py)

- `create_session(db, language) -> TriageSession`: Create session in `CONSENT_FRAMING` status.
- `get_session(db, session_id) -> TriageSession`: Retrieve with validation.
- `update_session_status(db, session, new_status)`: State transition with guards.
- `close_session(db, session_id, reason)`: Set to `ABANDONED`.

#### [NEW] [app/engine/policy_engine.py](file:///d:/pema/app/engine/policy_engine.py)

The policy engine is the **deterministic brain** of the system (FR-02.2, FR-04.4). In Phase 1 it will be a stub returning hardcoded decisions. Full logic will be completed in Phase 3–4.

- `decide_next_action(session, facts, rule_events) -> PolicyDecision`:
  - `PolicyDecision` = Pydantic model: `action: "ask" | "escalate" | "complete"`, `missing_facts: list[str]`, `specialty: Specialty | None`, `urgency: Urgency | None`
  - Phase 1 stub: If red flags → `escalate`. Otherwise → `ask` with all facts as "missing".

#### [NEW] [app/engine/audit_logger.py](file:///d:/pema/app/engine/audit_logger.py)

- `log_turn(db, session_id, ...)`: Persist raw input, extracted facts snapshot, triggered rules, LLM call details (null in Phase 1), final system response, and decision rationale to the appropriate tables.

#### [NEW] [app/engine/orchestrator.py](file:///d:/pema/app/engine/orchestrator.py)

The main turn-processing pipeline. Invoked on each user message:

```
1. Load session + facts from DB
2. Save user message to messages table
3. Run safety_rules.check_safety_rules(raw_text, current_facts)
4. If red flags → transition to ESCALATED, compose emergency response, log, return
5. Run policy_engine.decide_next_action(session, facts, rules)
6. Based on decision:
   - ASK   → compose follow-up question (stub in Phase 1)
   - COMPLETE → compose recommendation (stub in Phase 1)
7. Save system message to messages table
8. Log audit trail
9. Return response
```

---

### 1.6 API Routes

#### [NEW] [app/api/sessions.py](file:///d:/pema/app/api/sessions.py)

Implements PRD §7 endpoints:

- `POST /sessions` → Creates session, returns framing message (EN or UR per FR-06.1–06.2)
- `POST /sessions/{id}/messages` → Core turn handler, delegates to orchestrator
- `GET /sessions/{id}` → Session state + facts
- `POST /sessions/{id}/close` → Close/abandon session

#### [NEW] [app/api/admin.py](file:///d:/pema/app/api/admin.py)

- `GET /admin/sessions` → List sessions with filters (status, date range)
- `GET /admin/sessions/{id}` → Full detail: messages, facts, rule events, model audits

#### [NEW] [app/main.py](file:///d:/pema/app/main.py)

- FastAPI app factory
- Register routers (`/sessions`, `/admin`)
- CORS middleware (permissive for dev)
- Startup/shutdown events for DB connection
- Health check endpoint `GET /health`

---

### 1.7 Framing Messages

Hardcoded bilingual framing messages per FR-06.1–06.2, stored as constants:

**English:**
> Hi! I'm PEMA, your health guide. I can help you figure out what type of doctor to visit based on your symptoms.  
> ⚠️ I don't diagnose or prescribe. If this is an emergency, please call 1122 immediately.  
> Tell me, what's bothering you today?

**Roman Urdu:**
> Assalam o Alaikum! Main PEMA hoon. Main aapko batata hoon ke aapko kis qisam ke doctor ke paas jana chahiye.  
> ⚠️ Main diagnose ya dawai nahi deta. Agar emergency hai to abhi 1122 call karein.  
> Batayein, kya takleef hai?

---

### Phase 1 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | FastAPI app boots, serves Swagger docs at `/docs` |
| | `POST /sessions` returns session ID + framing message (EN/UR) |
| | `POST /sessions/{id}/messages` processes messages through the pipeline |
| | Safety rules trigger correctly for all 10 red-flag patterns (EN + UR) |
| | `POST /sessions/{id}/close` closes the session |
| | Admin endpoints return session data |
| | All data persisted to PostgreSQL |
| | Unit tests pass for safety rules |

---

## Phase 2 — Structured Extraction (LLM Fact Extractor)

**Goal:** Add a single LLM call that converts free-text user input into structured `ExtractedFacts` JSON. The LLM does not control flow — it only extracts.

**PRD Coverage:** FR-01.1–FR-01.4, NFR-06, NFR-07

---

### 2.1 OpenAI Client Setup

#### [MODIFY] [config.py](file:///d:/pema/app/config.py)

- Add `openai_model: str = "gpt-4o"` to settings
- Add `fact_extraction_prompt_version: str = "v1"`

#### [NEW] [app/engine/llm_client.py](file:///d:/pema/app/engine/llm_client.py)

- Thin async wrapper around the OpenAI Responses API
- Uses structured output (JSON mode) with the `ExtractedFacts` Pydantic schema as the response format
- Records latency, model name, prompt version for audit
- Returns `(ExtractedFacts, ModelAuditData)` tuple

---

### 2.2 Fact Extraction Prompt

#### [NEW] [app/prompts/fact_extraction.py](file:///d:/pema/app/prompts/fact_extraction.py)

System prompt designed to:
1. Extract structured facts from free-text symptom descriptions
2. Handle English, Roman Urdu, and mixed-language input (FR-01.4)
3. Map Roman Urdu health terms to medical concepts (using PRD §9.1 vocabulary)
4. Output **only** the structured JSON — no diagnosis, no medical opinion
5. Preserve `null` for unknown fields (do not guess)
6. Merge new information with previously extracted facts (incremental extraction)

The prompt will include the Roman Urdu vocabulary table from PRD §9.1 as reference context.

**Input to the prompt:** conversation history (all messages) + current extracted facts + new user message.

**Output:** Validated `ExtractedFacts` JSON.

---

### 2.3 Fact Extractor Module

#### [NEW] [app/engine/fact_extractor.py](file:///d:/pema/app/engine/fact_extractor.py)

- `extract_facts(conversation_history, current_facts, new_message) -> (ExtractedFacts, ModelAuditData)`:
  - Builds the prompt from the template + conversation context
  - Calls `llm_client` with structured output
  - Validates the returned JSON against the `ExtractedFacts` Pydantic model
  - Merges with existing facts (new values override nulls, never erase known facts)
  - Returns validated facts + audit metadata

#### [MODIFY] [app/engine/orchestrator.py](file:///d:/pema/app/engine/orchestrator.py)

- Insert fact extraction step between "save user message" and "run safety rules"
- Safety rules now also receive parsed facts (belt-and-suspenders check)
- Audit logger records the LLM call metadata

---

### 2.4 Language Detection

- The LLM prompt will be instructed to detect the user's language from message content
- Store detected language in session facts for use by the Response Composer in Phase 3
- If user writes in Roman Urdu, set `session.language = "ur"`

---

### Phase 2 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | Fact Extractor produces valid `ExtractedFacts` from English free text |
| | Fact Extractor handles Roman Urdu input (PRD §9.1 terms) |
| | Mixed-language input correctly parsed (FR-01.4) |
| | Facts incrementally merged across turns |
| | LLM call metadata logged to `model_audits` table |
| | Safety rules now check both raw text AND extracted facts |

---

## Phase 3 — Next-Question Logic

**Goal:** The policy engine determines which facts are still missing. The LLM phrases a natural-language follow-up question. One question per turn. Max 8 turns (FR-02.3).

**PRD Coverage:** FR-02.1–FR-02.4, FR-01.3

---

### 3.1 Policy Engine — Full Implementation

#### [MODIFY] [app/engine/policy_engine.py](file:///d:/pema/app/engine/policy_engine.py)

Replace the Phase 1 stub with real decision logic:

- **Required facts definition:** A configuration-driven list of mandatory fields:
  - `age` — always required
  - `sex` — always required
  - `chief_complaint` — always required
  - `duration` — required if symptom-based
  - `severity` — required if symptom-based
  - `is_pregnant` — required if sex is female and age 12–55
  - At least 1 associated symptom query answered — required

- `decide_next_action(session, facts, rule_events) -> PolicyDecision`:
  1. If `rule_events` contains emergency rules → `action = "escalate"`
  2. Compute `missing_facts` from the required facts definition vs. current facts
  3. If `turn_count >= max_follow_up_turns` and still missing facts → `action = "complete"` with lower confidence (default to GP)
  4. If `missing_facts` is empty → `action = "complete"`
  5. Otherwise → `action = "ask"` with `missing_facts` list and priority order
  
- **Fact priority order:** chief_complaint > age > sex > duration > severity > associated symptoms > pregnancy status

---

### 3.2 Response Composer

#### [NEW] [app/prompts/response_composition.py](file:///d:/pema/app/prompts/response_composition.py)

System prompt for generating the next user-facing message. Instructions:
1. Ask **one** question at a time (FR-02.1), targeting the most important missing fact
2. Use plain, non-medical language (FR-02.4)
3. Match the user's language (EN or Roman Urdu) (NFR-07)
4. Keep responses to 1–3 sentences (§10.3)
5. Tone: warm, clear, reassuring

#### [NEW] [app/engine/response_composer.py](file:///d:/pema/app/engine/response_composer.py)

- `compose_follow_up(conversation_history, missing_facts, language) -> (str, ModelAuditData)`:
  - Builds prompt with missing fact name, conversation context, and language preference
  - Returns a natural-language question + audit data

- `compose_emergency_response(rule_events, language) -> str`:
  - Deterministic template (not LLM) for emergency responses
  - Includes emergency number 1122, bold formatting, emojis (§10.3)
  - Different templates for EN and UR
  - RF-004 adds crisis helpline numbers

#### [MODIFY] [app/engine/orchestrator.py](file:///d:/pema/app/engine/orchestrator.py)

- When policy says `"ask"` → call `response_composer.compose_follow_up()`
- When policy says `"escalate"` → call `response_composer.compose_emergency_response()`
- Track turn count; increment on each user message

---

### Phase 3 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | Policy engine correctly identifies missing facts |
| | One question asked per turn; plain language; matches user's language |
| | Turn limit enforced (max 8 follows ups) (FR-02.3) |
| | Pregnancy status asked only for females of reproductive age (FR-01.3) |
| | Emergency responses use deterministic templates, not LLM |

---

## Phase 4 — Completion Logic

**Goal:** When all required facts are collected, compute urgency + specialty and produce the final recommendation. The complete end-to-end triage flow is now functional.

**PRD Coverage:** FR-04.1–FR-04.4, NFR-04, NFR-05

---

### 4.1 Specialty Mapping Rules

#### [MODIFY] [app/engine/policy_engine.py](file:///d:/pema/app/engine/policy_engine.py)

Add a rules-based specialty mapping system (FR-04.4 — implemented in code, not LLM):

- `compute_recommendation(facts: ExtractedFacts) -> (Specialty, Urgency, float)`:
  - Returns (specialty, urgency_level, confidence_score)
  
- **Mapping rules** (configurable, stored as data structures):
  
  | Symptom Cluster | Specialty | Default Urgency |
  |----------------|-----------|-----------------|
  | Stomach/digestion + nausea/bloating | Gastroenterologist | Routine |
  | Skin-related (rash, lesion, itching) | Dermatologist | Routine |
  | Ear/nose/throat (ear pain, hearing, sinus) | ENT | Routine |
  | Respiratory (cough, wheeze, breathing) | Pulmonologist | Routine → Urgent if >2 weeks |
  | Joint/bone/muscle pain | Orthopedist | Routine |
  | Headache/neuro symptoms (vision, numbness) | Neurologist | Urgent if severe |
  | Urinary (pain, blood, frequency) | Urologist | Urgent if blood present |
  | Mental health (anxiety, depression, insomnia) | Psychiatrist | Routine → Urgent if severe |
  | Gynecological (menstrual, pelvic) | Gynecologist | Routine |
  | Child < 12 + general symptoms | Pediatrician | Based on severity |
  | Fallback / unclear | General Practitioner | Routine |

- **Urgency modifiers:**
  - Severity "severe" → bump urgency one level
  - Duration > 2 weeks → consider "urgent" if currently "routine"
  - Blood in symptoms → at minimum "urgent"
  - Child under 5 with fever → "urgent" minimum

- **Confidence calculation:**
  - 0.9+ if chief complaint clearly maps to a single specialty
  - 0.7–0.9 if mapping is probable but ambiguous
  - < 0.7 → default to General Practitioner

---

### 4.2 Recommendation Response

#### [MODIFY] [app/engine/response_composer.py](file:///d:/pema/app/engine/response_composer.py)

- `compose_recommendation(specialty, urgency, facts, language) -> (str, ModelAuditData)`:
  - LLM generates a brief, plain-language rationale based on extracted facts
  - Includes: specialty name (with plain-language explanation), urgency level, disclaimer
  - Matches user's language
  - Example output modeled on PRD §10.1 and §10.2
  - **Every recommendation MUST include the disclaimer** (NFR-04, NFR-05)

#### [MODIFY] [app/engine/orchestrator.py](file:///d:/pema/app/engine/orchestrator.py)

- When policy says `"complete"`:
  1. Call `policy_engine.compute_recommendation(facts)`
  2. Call `response_composer.compose_recommendation(...)`
  3. Transition session to `COMPLETED`
  4. Store specialty, urgency, confidence in `session_facts`
  5. Log full audit trail

---

### Phase 4 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | End-to-end triage works: symptom → follow-ups → recommendation |
| | Specialty mapping is code-driven with configurable rules |
| | Urgency levels correctly computed based on severity, duration, age |
| | Recommendations include specialty, urgency, rationale, and disclaimer |
| | Session transitions to COMPLETED after recommendation |
| | Confidence score stored; low confidence defaults to GP |

---

## Phase 5 — Test Harness

**Goal:** Comprehensive automated tests covering all 15 PRD scenarios (§12) plus safety rule unit tests and API integration tests.

**PRD Coverage:** All 15 test scenarios (TS-01 through TS-15), NFR-03

---

### 5.1 Unit Tests

#### [NEW] [tests/conftest.py](file:///d:/pema/tests/conftest.py)

- Test database setup (SQLite async or test PostgreSQL)
- FastAPI test client fixture using `httpx.AsyncClient`
- Mock LLM fixture that returns predetermined `ExtractedFacts` for known inputs
- Session factory fixture

#### [NEW] [tests/test_safety_rules.py](file:///d:/pema/tests/test_safety_rules.py)

Exhaustive tests for all 10 red-flag rules:
- English keyword matching for each rule
- Roman Urdu keyword matching for each rule
- Mixed-language input
- Combination logic (AND rules like RF-001, RF-007)
- Fact-based rules (RF-008 — age check)
- **Zero false negatives** — test every trigger pattern in the PRD
- Case insensitivity
- Partial text matching (patterns embedded in longer messages)

#### [NEW] [tests/test_policy_engine.py](file:///d:/pema/tests/test_policy_engine.py)

- Missing fact detection
- Turn limit enforcement
- Specialty mapping for each symptom cluster
- Urgency computation
- Confidence thresholds
- Default-to-GP fallback

---

### 5.2 Integration Tests

#### [NEW] [tests/test_api.py](file:///d:/pema/tests/test_api.py)

- Session creation (EN and UR)
- Session retrieval
- Message send/receive
- Session closure
- Admin endpoints
- Error handling (invalid session ID, message to closed session)

---

### 5.3 End-to-End Scenario Tests

#### [NEW] [tests/test_scenarios.py](file:///d:/pema/tests/test_scenarios.py)

Automated multi-turn tests simulating the full 15 PRD scenarios. Each test:
1. Creates a session
2. Sends a sequence of user messages (simulating the patient)
3. Uses mock LLM responses (but real safety rules and policy engine)
4. Asserts on: final specialty, urgency, session status, triggered rules
5. Verifies audit data completeness (FR-07.2)

| Test | Scenario | Key Assertions |
|------|----------|----------------|
| TS-01 | Stomach pain, nausea, 32yo | Gastroenterologist, Routine |
| TS-02 | Chest pain + SOB | Emergency escalation, session halted, RF-001 |
| TS-03 | Child age 3, fever >104°F | Emergency escalation, RF-008 |
| TS-04 | Headaches, blurred vision | Neurologist, Urgent |
| TS-05 | Irregular periods, pelvic pain | Gynecologist, Routine |
| TS-06 | Pregnant, bleeding | Emergency escalation, RF-010 |
| TS-07 | Skin rash, 2 weeks | Dermatologist, Routine |
| TS-08 | Ear pain, hearing loss | ENT, Routine |
| TS-09 | Cough, wheezing, 1 month | Pulmonologist, Urgent |
| TS-10 | Joint pain, swelling | Orthopedist, Routine |
| TS-11 | Painful urination, blood | Urologist, Urgent |
| TS-12 | Suicidal thoughts | Emergency + crisis helpline, RF-004 |
| TS-13 | Roman Urdu: bukhar + sar dard | Fact extraction works, response in UR |
| TS-14 | Mixed: "meri back mein pain hai from 1 week" | Fact extraction, correct specialty |
| TS-15 | Minimal info, no elaboration | Follow-ups, eventual GP default |

---

### Phase 5 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | All 10 safety rules pass tests in EN + UR |
| | All 15 PRD test scenarios pass |
| | API integration tests pass |
| | Zero false negatives on red-flag patterns (NFR-03) |
| | Audit trail completeness verified for each scenario |

---

## Phase 6 — Internal Review UI (Admin Dashboard + Web Sandbox)

**Goal:** A simple admin web page and a patient-facing chat sandbox for testing. Both are browser-based.

**PRD Coverage:** §2.2 (admin persona), FR-07.3, §11 Step 6

---

### 6.1 Web Sandbox (Test Chat UI)

#### [NEW] [sandbox/index.html](file:///d:/pema/sandbox/index.html)

A clean, responsive chat interface for testing the triage flow:
- Chat message bubbles (user/system)
- Session ID display
- Language toggle (EN/UR)
- Emergency alerts styled with red background, emojis
- "New Session" button
- Auto-scroll, send on Enter

#### [NEW] [sandbox/style.css](file:///d:/pema/sandbox/style.css)

Modern chat UI styling: dark theme, message bubbles, responsive.

#### [NEW] [sandbox/app.js](file:///d:/pema/sandbox/app.js)

- Calls `POST /sessions` on load → displays framing message
- Sends messages via `POST /sessions/{id}/messages`
- Renders system responses
- Handles emergency state (disables input, shows alert)

#### [MODIFY] [app/main.py](file:///d:/pema/app/main.py)

- Serve `sandbox/` as static files at `/sandbox`

---

### 6.2 Admin Dashboard

#### [NEW] [sandbox/admin.html](file:///d:/pema/sandbox/admin.html)

Minimal admin page for internal reviewers:
- Session list with filters (status, date)
- Click-through to session detail
- Full message history display
- Extracted facts table
- Rule events with severity highlighting
- Model audit data (prompt version, latency, raw output)

#### [NEW] [sandbox/admin.js](file:///d:/pema/sandbox/admin.js)

- Calls `/admin/sessions` for listing
- Calls `/admin/sessions/{id}` for detail view
- No authentication for MVP (PRD: auth deferred to Phase 2)

---

### Phase 6 Deliverables

| ✅ | Deliverable |
|----|-------------|
| | Web sandbox allows full triage conversation in browser |
| | Admin dashboard shows session list + drill-down |
| | Emergency alerts render correctly with styling |
| | Session trace is reviewable (messages, facts, rules, audits) |

---

## Verification Plan

### Automated Tests

All tests are run from the project root:

```powershell
# Install dependencies
cd d:\pema
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run only safety rule tests
pytest tests/test_safety_rules.py -v

# Run only scenario tests
pytest tests/test_scenarios.py -v

# Run only API tests
pytest tests/test_api.py -v
```

### Manual Verification

After each phase, I will:
1. Start the server (`uvicorn app.main:app --reload`) and verify Swagger docs load at `/docs`
2. Run `pytest` and confirm all tests pass
3. For Phases 4+: Complete a full triage flow via Swagger/Sandbox UI
4. For Phase 6: Visually verify the sandbox chat UI and admin dashboard in the browser

### Browser-Based Verification (Phase 6)

- Open `http://localhost:8000/sandbox` and complete several triage flows
- Open `http://localhost:8000/sandbox/admin.html` and verify session inspection
- Test both EN and UR flows
- Trigger emergency scenarios and verify alerts render correctly

---

## Noted PRD Gaps & Risks

> [!NOTE]
> These are observations, not blockers. Flagging them for awareness.

| # | Observation | Impact | Suggested Mitigation |
|---|-------------|--------|---------------------|
| 1 | **No rate limiting specified.** The PRD doesn't mention rate limiting on the public API. | An abusive client could flood sessions. | Add basic rate limiting middleware in Phase 1 (e.g., `slowapi`). Can be simple — 10 sessions/min per IP. |
| 2 | **Session timeout not defined.** FR-05.3 mentions "abandoned (user left or timed out)" but no timeout duration is given. | Sessions could remain open indefinitely. | Default to 30-minute inactivity timeout. Implement a background task or check on next access. |
| 3 | **RF-007 is "Urgent" but §3.3 says all red flags are emergency.** The PRD defines RF-007 (severe abdominal pain + fever + vomiting) as "Urgent escalation" in the rules table, but FR-03.3 implies all red flags trigger emergency escalation. | Ambiguous handling of RF-007. | I'll implement RF-007 as **urgent** (not emergency) per the explicit rules table, since it's the more specific definition. Let me know if you want this changed. |
| 4 | **No explicit CORS policy.** Multiple origins may need access (sandbox, future mobile app). | Could block sandbox requests. | Set permissive CORS in dev; tighten for production. |
| 5 | **OpenAI Responses API vs. Chat Completions.** The PRD specifies "Responses API" but structured output is also available via Chat Completions. | The Responses API is newer and may have fewer examples. | I'll use whichever supports `response_format` with Pydantic schema best. Likely Chat Completions with `response_format={"type": "json_schema", ...}`. Will confirm during Phase 2. |
| 6 | **No versioning strategy for prompts.** PRD requires prompt version in audits but doesn't define a versioning scheme. | Prompt changes are hard to track. | Use simple string versions (`"fact_extraction_v1"`) stored as constants in the prompt modules. |

---

## Critical Patch: Semantic Red-Flag Detection (Done afterwards)
**Problem:** Lexical mismatching (e.g., user says "heart pain" while the code expects "chest pain").

### Hybrid Normalization Architecture
We implemented a **Symptom Normalizer** pre-pass to bridge the gap between human language and clinical keywords.

| Step | Component | Action |
| :--- | :--- | :--- |
| **1** | **Normalizer (LLM)** | Rewrites raw text into clinical keywords (e.g., "dil mein dard" → "chest pain"). |
| **2** | **Safety Rules (Code)** | Scans **both** raw and normalized text for deterministic red-flag patterns. |
| **3** | **Decision (Code)** | If a match exists in either source, the engine triggers an immediate emergency escalation. |

**Safety Guardrails:**
* **Deterministic Control:** The LLM *never* decides if it is an emergency; it only translates the symptoms.
* **Graceful Degradation:** A 3-second timeout ensures that if the LLM is slow, the engine falls back to raw text matching so the safety check is never skipped.
* **Zero-Temperature:** Forced deterministic output for maximum consistency.