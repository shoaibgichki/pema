# Conversation Engine Architecture Note

**Conversational symptom intake and doctor-specialty routing engine for a WhatsApp-first MVP**

**Version 1.0 | March 2026**

> **Recommended MVP framing**
> The engine should guide users to the right doctor type, not provide diagnosis or treatment. Emergency rules must sit outside the LLM and override normal conversation flow.

---

## 1. Purpose and scope

This document turns the earlier planning discussion into a practical technical path for building the Conversation Engine before any WhatsApp integration.

The engine should accept free-text symptom descriptions, ask focused follow-up questions, detect red flags, maintain session state, and return one of four safe outcomes: emergency escalation, urgent routing, non-urgent specialty routing, or request for more information.

The first release should be channel-independent so it can be tested in a web sandbox and later connected to WhatsApp without changing the core logic.

---

## 2. Recommended technology stack

Use a narrow, dependable backend stack first. The goal is predictable behavior, strong validation, and simple deployment.

| Layer | Choice | Why this is suitable |
|---|---|---|
| Language | Python 3.12 | Mature ecosystem for APIs, validation, testing, and AI integration. |
| API backend | FastAPI | Typed request and response models, clear routers, strong developer ergonomics, and easy internal testing. |
| Schema validation | Pydantic v2 | Strict data models for session state, model outputs, and policy decisions. |
| LLM integration | OpenAI Responses API | Best fit for structured outputs, deterministic JSON, and controlled orchestration. |
| Database | Postgres on Supabase | Simple managed Postgres for sessions, messages, facts, and audit data. |
| Auth | Defer for phase 1 | Keep the engine backend-only during internal testing and add auth once the flow stabilizes. |
| Frontend for testing | Web sandbox | A browser-based test UI is faster and safer than starting with a mobile app. |

---

## 3. Core design principles

The engine should be conversational, but the control plane should remain deterministic.

- **LLM for understanding:** Use the model to extract facts, identify missing information, and draft the next question.
- **Code for control:** Keep emergency escalation, stopping rules, specialty enums, and confidence thresholds in backend logic.
- **Short-turn design:** Ask one useful follow-up question at a time instead of producing long medical conversations.
- **Fixed output space:** Allow only a constrained list of specialties and urgency levels.
- **Auditability:** Store raw inputs, extracted facts, triggered rules, and final decisions for every turn.
- **Safety first:** Run red-flag checks on every turn, not only at session start.

---

## 4. Engine modules

A clean module split keeps the engine testable and makes later WhatsApp integration much easier.

| Module | Primary responsibility | Typical outputs |
|---|---|---|
| Session manager | Create and update triage sessions | Session status, turn count, timestamps, active state |
| Fact extractor | Convert free text into structured facts | Age, symptoms, duration, severity, missing fields |
| Safety rules | Detect emergency and urgent patterns | Rule events, escalation flags, evidence snippets |
| Policy engine | Decide next step using code | Need more info, continue, escalate, complete |
| Response composer | Generate short user-facing text | Next question, recommendation, emergency instruction |
| Audit logger | Persist trace data for every turn | Prompt version, model JSON, final output, rule results |

---

## 5. Conversation state flow

Treat the engine as a state machine rather than open-ended chat.

- **Consent and framing:** explain that the tool helps route the user to the right doctor type and is not a diagnosis engine.
- **Chief complaint:** capture the user's main problem in the user's own words.
- **Mandatory facts:** collect age, sex or pregnancy relevance where needed, duration, severity, and major associated symptoms.
- **Red-flag check:** evaluate emergency signals on every turn.
- **Specialty routing:** map the case to a fixed specialty enum or urgent care path.
- **Completion:** return urgency, recommended doctor type, and a brief rationale in plain language.

**Suggested specialty enum for the MVP:**

| | |
|---|---|
| General practitioner | Pediatrician |
| Gynecologist | Dermatologist |
| ENT | Pulmonologist |
| Gastroenterologist | Orthopedist |
| Neurologist | Urologist |
| Psychiatrist | Emergency department |

---

## 6. API surface for phase 1

Start with a minimal backend API that can be exercised from Swagger, Postman, or a small test UI.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /sessions | Create a new triage session and return session metadata. |
| POST | /sessions/{id}/messages | Accept a user message, run the engine, and return the next system response. |
| GET | /sessions/{id} | Return current session state and key extracted facts. |
| POST | /sessions/{id}/close | Close or abandon a session explicitly. |
| GET | /admin/sessions | List recent sessions for internal review. |
| GET | /admin/sessions/{id} | Inspect message history, rule events, and model audits. |

---

## 7. Data model

Keep the first schema small. The goal is traceability, not enterprise-scale modeling.

| Table | Purpose and typical fields |
|---|---|
| triage_sessions | Session id, status, channel, created_at, updated_at, engine_version. |
| messages | Session id, role, message text, timestamp, turn number. |
| session_facts | Age, sex, complaint, duration, severity, urgency, specialty recommendation, confidence. |
| rule_events | Triggered rule name, severity, evidence snippet, timestamp. |
| model_audits | Prompt version, model name, structured JSON output, latency, trace id. |

---

## 8. Development roadmap

The fastest path is to build the deterministic skeleton first and add the model only where it adds clear value.

- **Step 1 - Deterministic skeleton:** Implement sessions, core schema, emergency rules, specialty enums, and a basic policy engine without any LLM.
- **Step 2 - Structured extraction:** Add one model call that converts free text into validated JSON facts.
- **Step 3 - Next-question logic:** Use code to determine what is missing, then let the model phrase one short follow-up question.
- **Step 4 - Completion logic:** Once required facts are present, compute urgency and specialty and produce the final recommendation.
- **Step 5 - Test harness:** Create scripted test cases covering emergency, pediatric, pregnancy-related, respiratory, neurological, and urinary scenarios.
- **Step 6 - Internal review UI:** Add a simple admin page to inspect sessions, failure cases, and rule triggers before WhatsApp integration.

---

## 9. MVP acceptance criteria

- The engine can handle a full session from symptom description to doctor-specialty recommendation in a browser-based test environment.
- Emergency cases are escalated consistently and do not fall through to routine routing.
- Every turn is stored with enough detail to reconstruct the decision path.
- The response style stays short, clear, and non-diagnostic.
- The same engine can later be called from a WhatsApp webhook without changing the core triage logic.

---

> **Immediate next build target**
> A FastAPI-based triage engine that accepts text, stores session state, runs red-flag rules, extracts structured symptom facts, and returns one next question or one specialty recommendation.