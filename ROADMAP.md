# Roadmap

Findings from a harness review (2026-08-15), roughly in order of how much they hurt. Completed items are trimmed as they land.

## 1. The prompt contradicts the schema

`src/squawk/agent.py:15` tells the model `"recipients" is a list of recipient names`, but the schema demands full `Contact` objects (`{name, email}`). A model that follows the prose emits `["Jane Doe"]`, validation fails, and the case is recorded as an error failure.

Related prompt/model inconsistencies:

- [x] Fix the recipients prompt line to match the schema
- [ ] The prompt never tells the agent _when_ to escalate, or who "the customer contact" is — the expectation encodes a specific policy (notify customer contact; escalate iff a later leg exists) the agent must guess. Fine if deliberate (measuring whether models infer it), but it should be a choice, not an accident.

## 2. No statistical rigor around a stochastic system

The runner does one attempt per case at temperature 0.5 and reports point estimates. Missing:

- [ ] **Repeats/trials per case** (or a pass@k / consistency metric) — at t=0.5 a single sample tells you little; run-to-run precision will wobble
- [ ] **Confidence intervals** — with 30 cases (3 templates × 10 variants), per-tag slices get small fast. `evals compare` surfaces each slice's `n`; CIs are the remaining piece

## Smaller items

- [ ] **Hybrid report: template the metrics, LLM only for failure narrative**: the report LLM currently transcribes precision/recall/pass rates from `summary` into prose — small local models get numbers wrong, for zero gain, since `AggregateScore` already computes them. Render the metrics/slice tables deterministically (f-string/Jinja) and scope the LLM prompt down to one job: read the sampled failure diffs and describe recurring failure patterns, appended as an analysis section. Each tool does what it's good at; numbers in the report become trustworthy enough to quote
- [x] **Inconsistent defaults**: the CLI now imports `DEFAULT_MODEL` / `DEFAULT_MODEL_TEMPERATURE` from `src/squawkbox/llm.py`, and the agent falls through to the same factory defaults — one source of truth for every entry point (`default_model()` and its temperature-0 default are gone)
- [ ] **Dead dependency**: `langgraph` is in `pyproject.toml` but never imported — the agent is a single LLM call
- [x] **Abstract the LLM model/provider**: all construction now routes through `create_model` in `src/squawkbox/llm.py`, which takes a `provider/model_name` spec; `ChatOllama` appears nowhere else, and provenance records the full spec (provider included). Ollama is deliberately the only wired-in provider for now — adding hosted models (Claude, GPT, via `init_chat_model` or per-provider branches) is a follow-up when comparison against local models is actually wanted
- [ ] **No run ergonomics**: no way to run a subset (`--limit`, filter by tag/case-id) for quick iteration, no progress indication beyond debug logs, no token counts (only latency)
- [ ] **Near-miss tie-breaking**: pairing picks the candidate with the fewest mismatch strings (`evals/scoring/scorer.py:108`), but for `update_property` both "wrong path" and "wrong value" produce exactly one reason, so a completely-wrong-field action ties with an almost-right one. Greedy pairing is fine at this scale, but the tie means near-miss quality isn't distinguished
- [x] **Derive prompt vocabulary blocks from the models, not hand-written prose**: the "Available actions" block in `src/squawk/agent.py:12-15` duplicates the docstrings in `src/squawk/models/actions.py` and has already drifted (the recipients bug, item 1). Generate it by walking the discriminated union (`typing.get_args` + `__doc__` + `model_fields`) — the union is the registry; don't build a separate one. Do the actions block first (fixes the live drift class), and extend to events when they grow (natural moment: the correlation rework). Note: the prompt currently describes _zero_ events — the model reads raw payloads cold, which is part of what's being measured. Describing events is an eval-design change to task difficulty, not a refactor; make it a deliberate, `--label`ed comparison run. Prompt-hash provenance already captures the resulting prompt changes

## Planned: event applicability — raw events, agent-side correlation

Today's incoming events pre-solve the hardest real-world step: `arrival_delay` carries a `leg_index`, so the agent is told which leg is affected. In reality the event arrives as a vessel, voyage, and new ETA, and deciding _whether it applies to this shipment at all_ is the first decision of manage-by-exception. Moving correlation into the agent's job is the most decision-relevant realism available (it passes the anti-goal test cleanly), and it enables the product-shaped use case of running one event against a set of shipments.

Design decisions (settled in discussion, 2026-08-15):

- **Events carry real-world identifiers, not `leg_index`.** Vessel/voyage (legs already have a faked conveyance string), port pair, dates. The agent correlates against the shipment state it already receives — no new prompt structure needed, but verify conveyance identifiers survive state serialization into the prompt.
- **The eval unit stays pairwise `(shipment, event)`.** The fan-out — one event against N shipments — is a runtime/product feature; the eval expresses it as N pairwise cases, some applicable, some distractors. This preserves the one-state-one-event-one-diff shape the scorer, reporter, and decision matrix are built on. Do not broaden the case to a shipment set.
- **Determinism is preserved.** The generator knows ground truth: it either derived the event from the shipment's own leg (applicable) or perturbed identifiers (not applicable). Answer keys still come free; a non-matching event is a new species of clean case with `should_act=False`.
- **Distractors are the new near-miss family.** Same vessel / different voyage, same lane / different vessel, same voyage / shipment already discharged. This is a better answer to the "richer scenario classes" gap than more `eta_confirmed` noise.
- **Applicability is scored as its own axis.** A failed case must distinguish "didn't match the event" from "matched it and acted wrong": tag cases `applicable` / `not_applicable` (plus `near_match` on lookalikes) and add a correlation row to the decision matrix.
- **"Injector" is renamed along with the rework.** "Inject" promises the event lands _in_ this shipment; a distractor event is only staged _near_ it. The contract — given a shipment, produce an event, the answer key, and tags — is authoring a scenario, not injecting a fault. One name for the whole family: do **not** split into Injector-vs-Distractor class families — same interface, same pipeline, and the report wants them as one slice dimension. `distractor` is a tag, not a class family. `is_applicable` keeps its name with a shifted reading: "can this scenario be staged against this shipment" (a distractor answers yes when it can build a convincing lookalike from the shipment's lane).

Work items:

- [ ] Rework event models to carry identifiers (vessel/voyage, ports, dates) instead of `leg_index`
- [ ] Existing injectors emit identifiers drawn from the shipment's own legs (they already hold the shipment, so determinism is unchanged)
- [ ] Distractor scenarios producing not-applicable and near-match events, with `should_act=False` expectations
- [ ] `applicable` / `not_applicable` / `near_match` tags, and the correlation split in the decision matrix
- [ ] Confirm the agent prompt exposes leg conveyance identifiers; adjust state serialization if not

Rename (do this in the same change as the rework, not before):

- [ ] `ScenarioInjector` → `ScenarioGenerator`; `inject()` → `stage()`; module `evals/generation/injectors.py` → `scenarios.py`
- [ ] Concrete subclasses: `*Injector` → `*Scenario` (e.g. `ArrivalDelayInjector` → `ArrivalDelayScenario`), including the `INJECTORS` list in `evals/generation/generator.py`
- [ ] `EvalCase.injector` field → `scenario`, plus the per-injector slice in scoring/report aggregation — a better label anyway ("which scenario shape failed" is the question the report answers). Note: this breaks compatibility with previously generated case files and old results JSON; regenerate cases and don't diff across the rename
- [ ] Sweep prose for the old term: README (Events and injectors section, generation bullets, Not built yet), docstrings, log fields (`injected event`, `injector=` in `generator.py`), and test names

## Suggested order

1. Fix the recipients prompt line (item 1) — the live bug every run hits
2. The statistical rigor (item 2, repeats + CIs) — what turns it from "runs evals" into "answers questions about models"
