# Multi-Agent Specification Plan

## Purpose

Produce a concrete, reviewable specification for the proposed dynamic multi-agent diagnostic workflow: each agent's inputs, outputs, responsibilities, handoff rules, and stopping conditions.

## Current basis and limits

The architecture proposal describes an Orchestrator that can select among vision, clinical analysis, diagnosis, critic, and RAG capabilities, using shared case state and iterative verification. It is a conceptual proposal; no runnable orchestrator or agent interfaces were found in the inspected project materials.

The tropical disease demo provides retrospective case text, age, gender, images referenced through image metadata, image captions/types/labels, and article/citation metadata. It is suitable for designing and exercising contracts against examples. It does not define a real-time patient intake format. Disease-folder membership is a filter label, not guaranteed ground truth for every case. Some image paths reference files outside the demo folders, and the with-image/without-image partitions leave nine cases unaccounted for across dengue, malaria, and typhoid.

## Specification work plan

### 1. Set operating scope

Write down the intended use and boundaries before defining agent behavior:

- Is the first version a research/demo prototype or a clinician-facing decision-support tool?
- Which conditions are in scope initially (suggestion: the eight tropical disease subsets)?
- Will inputs be retrospective dataset records, manually entered cases, or both?
- What output is expected: ranked differential, evidence summary, triage suggestion, or another format?
- Which decisions must remain with a qualified clinician?

**Deliverable:** a short scope statement and explicit out-of-scope list.

### 2. Define the canonical case input

Create a normalized case object independent of the source CSV layout. Map fields available in the dataset and mark all other fields optional or unknown. At minimum consider:

- `case_id` and source provenance (`pmcid`, article/citation reference)
- `demographics` (`age`, `gender`, preserving missing values and source wording)
- `clinical_narrative` (source `case_text`)
- `images[]` (image identifier, accessible URI/path, caption, image type/subtype, labels, license)
- `available_tests[]` and `reported_diagnoses[]`, only when explicitly extracted or supplied
- `data_quality` (missing fields, unavailable image, extraction limitations)
- `dataset_label` as provenance/filter metadata, never silently promoted to a confirmed diagnosis

For each field specify type, allowed null behavior, units, validation, source, and whether it is observed, derived, or model-generated. Decide how to represent temporal course, negation, uncertainty, and conflicting statements without losing the original narrative.

**Deliverable:** schema plus example records for a text-only case, image case, and incomplete case.

### 3. Define the shared case state

Specify what the orchestrator stores between calls, how updates are appended/versioned, and how source attribution is retained. Suggested logical sections:

- original input and provenance
- extracted clinical facts with evidence spans and uncertainty
- image observations linked to image IDs
- candidate diagnoses and supporting/refuting evidence
- retrieved sources and citations
- unresolved questions, safety flags, and completed actions
- agent outputs, status, errors, and timestamps

Set rules that preserve the original case and distinguish source facts from model inferences.

**Deliverable:** shared-state schema and update/merge rules.

### 4. Specify each agent contract

For every agent define: purpose, trigger/eligibility conditions, required and optional inputs, exact structured output, evidence/provenance requirements, failure/abstention behavior, and what it must not do.

Candidate responsibilities to validate:

| Agent | Candidate responsibility | Candidate output |
|---|---|---|
| Intake/normalizer | Validate and normalize case data; identify missing or malformed fields | Normalized case, data-quality notes, clarification needs |
| Clinical extraction | Extract symptoms, timeline, exposures, exam findings, tests, treatments, and explicit negatives from narrative | Structured facts with source spans, temporal context, and uncertainty |
| Vision | Describe visible findings and classify image modality/region; do not infer beyond image evidence | Per-image observations, confidence/limitations, image IDs |
| Evidence retrieval (RAG) | Retrieve relevant trusted references for a stated question or candidate | Claims with source citations, publication metadata, and retrieval query |
| Differential diagnosis | Generate and compare candidates from accumulated evidence | Ranked candidates, supporting/refuting findings, missing discriminators |
| Critic/verifier | Find unsupported claims, contradictions, omitted urgent findings, and evidence gaps | Issues, severity, required corrections or pass/return decision |
| Orchestrator | Select next capability, enforce budget/limits, maintain state, decide continue/stop | Action decision, rationale, state update, stop reason |
| Final response | Present the approved result in the agreed format with uncertainty and provenance | Structured final report and safety/limitation statement |

These are proposals, not existing implemented agents. The final specification should merge or split roles according to available local models and tools.

**Deliverable:** one input/output contract per approved agent, preferably JSON-schema-backed.

### 5. Specify orchestration and handoffs

Define a finite state machine or explicit routing table covering at least:

- text-only input versus image-present input
- missing/ambiguous data and clarification request behavior
- when RAG is called and what question it receives
- when differential generation runs or is repeated
- critic rejection/return loops and a maximum iteration count
- model/tool failures, timeouts, and partial results
- termination conditions and escalation/abstention behavior

Specify local compute constraints: model availability, sequential/parallel calls, latency or token budgets, and fallback rules. Keep these configurable rather than embedding undocumented assumptions.

**Deliverable:** routing table/state diagram and termination policy.

### 6. Define final output and safety behavior

Choose a stable response structure. A candidate format includes:

- case summary based on supplied facts
- ranked differential with rationale and evidence for/against
- important missing information or tests to consider (if in scope)
- urgent findings/safety flags (if in scope)
- linked citations and image observations
- uncertainty, limitations, and explicit distinction between educational output and diagnosis

Define when the system must return “insufficient information,” abstain, or request human review. Avoid unsupported certainty and fabricated citations.

**Deliverable:** final-output schema and examples for normal, uncertain, and abstained cases.

### 7. Map dataset to contracts and document provenance

Build a data mapping from source columns/JSON fields to the normalized case schema. Check `case_id` joins, image path availability, split-file membership discrepancies, license handling, and disease-label interpretation. Decide how evaluation examples are selected without leaking the folder filter label into model input when testing diagnosis.

**Deliverable:** source-to-schema mapping and a small validated example set.

### 8. Define evaluation and acceptance criteria

Before implementation, define how each contract and the workflow will be judged. Include schema validity, extraction fidelity against source text, correct image-to-case linkage, citation validity, contradiction detection, abstention behavior, and end-to-end review by domain experts. Establish an evaluation split and prevent the disease subset label from becoming an accidental answer cue.

**Deliverable:** evaluation protocol, acceptance thresholds, and known limitations.

## Completion checklist

The specification is ready for implementation when it contains:

- agreed operating scope and boundaries
- canonical input and shared-state schemas
- approved agent roster with responsibility boundaries
- typed input/output contracts and failure behavior for every agent
- routing, handoff, iteration, budget, and termination rules
- final response format and abstention/safety rules
- source-data mapping and verified image access assumptions
- evaluation criteria and representative examples

## Immediate next artifacts

1. Confirm the operating scope and intended user of the prototype.
2. Draft the normalized case and shared-state schemas from the actual dataset columns and metadata.
3. Fill in the agent contract table with exact structured outputs.
4. Draw the routing state machine and define stop/failure behavior.
5. Validate the contracts against representative text-only, image, ambiguous, and incomplete dataset cases.
