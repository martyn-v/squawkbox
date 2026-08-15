# Roadmap

Findings from a harness review (2026-08-15), roughly in order of how much they hurt. Completed items are trimmed as they land.

## 1. The prompt contradicts the schema

`src/squawk/agent.py:15` tells the model `"recipients" is a list of recipient names`, but the schema demands full `Contact` objects (`{name, email}`). A model that follows the prose emits `["Jane Doe"]`, validation fails, and the case is recorded as an error failure.

Related prompt/model inconsistencies:

- [ ] Fix the recipients prompt line to match the schema
- [ ] `src/squawk/models.py:80` documents `path` as "a JSON pointer" while the prompt and injectors use bracket notation (`legs[0].eta`). No path canonicalization in the scorer, so `legs.0.eta` or `/legs/0/eta` becomes a near-miss even when the agent meant the right field.
- [ ] The prompt never tells the agent _when_ to escalate, or who "the customer contact" is — the expectation encodes a specific policy (notify customer contact; escalate iff a later leg exists) the agent must guess. Fine if deliberate (measuring whether models infer it), but it should be a choice, not an accident.

## 2. No statistical rigor around a stochastic system

The runner does one attempt per case at temperature 0.5 and reports point estimates. Missing:

- [ ] **Repeats/trials per case** (or a pass@k / consistency metric) — at t=0.5 a single sample tells you little; run-to-run precision will wobble
- [ ] **Run comparison tooling** — results carry the model name, but nothing diffs two runs (model A vs B, prompt v1 vs v2), which is the main thing an eval harness exists for. Design settled below ("Planned: run comparison")
- [ ] **Confidence intervals, or at least n per slice surfaced prominently** — with 30 cases (3 templates × 10 variants), per-tag slices get small fast

## Smaller items

- [ ] **Hybrid report: template the metrics, LLM only for failure narrative**: the report LLM currently transcribes precision/recall/pass rates from `summary` into prose — small local models get numbers wrong, for zero gain, since `AggregateScore` already computes them. Render the metrics/slice tables deterministically (f-string/Jinja) and scope the LLM prompt down to one job: read the sampled failure diffs and describe recurring failure patterns, appended as an analysis section. Each tool does what it's good at; numbers in the report become trustworthy enough to quote
- [ ] **Inconsistent defaults**: `default_model()` uses temperature 0 (`src/squawk/llm.py:8`) while the CLI defaults to 0.5 — two different "defaults" for the same agent depending on entry point
- [ ] **Dead dependency**: `langgraph` is in `pyproject.toml` but never imported — the agent is a single LLM call
- [ ] **Abstract the LLM model/provider**: `ChatOllama` is hardcoded in three places (`src/squawkbox/llm.py:6`, `evals/runner.py:35`, `evals/report.py:85`) — the harness can only evaluate Ollama-served models. Route construction through one factory that takes a provider + model spec (LangChain's `init_chat_model` covers this), so hosted models (Claude, GPT) can be compared against local ones. Pairs with the run-comparison tooling in item 2, and provenance should record provider alongside model name
- [ ] **No run ergonomics**: no way to run a subset (`--limit`, filter by tag/case-id) for quick iteration, no progress indication beyond debug logs, no token counts (only latency)
- [ ] **Near-miss tie-breaking**: pairing picks the candidate with the fewest mismatch strings (`evals/scoring/scorer.py:108`), but for `update_property` both "wrong path" and "wrong value" produce exactly one reason, so a completely-wrong-field action ties with an almost-right one. Greedy pairing is fine at this scale, but the tie means near-miss quality isn't distinguished
- [ ] **Derive prompt vocabulary blocks from the models, not hand-written prose**: the "Available actions" block in `src/squawk/agent.py:12-15` duplicates the docstrings in `src/squawk/models/actions.py` and has already drifted (the recipients bug, item 1). Generate it by walking the discriminated union (`typing.get_args` + `__doc__` + `model_fields`) — the union is the registry; don't build a separate one. Do the actions block first (fixes the live drift class), and extend to events when they grow (natural moment: the correlation rework). Note: the prompt currently describes *zero* events — the model reads raw payloads cold, which is part of what's being measured. Describing events is an eval-design change to task difficulty, not a refactor; make it a deliberate, `--label`ed comparison run. Prompt-hash provenance already captures the resulting prompt changes

## Planned: run comparison — `evals compare`

Diff two results files to answer "did this change help": model A vs B, prompt v1 vs v2. Fills the run-comparison bullet in item 2. `evals/picker.py` already supports picking exactly N files, so the interactive flow is pre-built.

Design decisions (settled in discussion, 2026-08-15):

- **CLI**: new `compare` command: `evals compare [FILE_A] [FILE_B]`. Omit the files to pick two interactively via the existing `pick_results_files(count=2)`. Older run = baseline, newer = candidate (timestamp filenames already sort). Prints markdown to stdout; optional `-o` writes it alongside the results.
- **Comparison logic** in a new `evals/scoring/compare.py`, tests-first. A `RunComparison` pydantic model built from two `EvalRun`s:
  - **Header** — model, temperature, label, git_sha, prompt hash for each side, so the diff says *what changed* between runs.
  - **Metric deltas** for overall + each slice (`by_injector`, `by_tag`, `by_action_type`): pass rate, precision, recall, plus decision-matrix rates, shown as `baseline → candidate (Δ)` with each slice's `n` visible (surfaces the small-n caveat without building CIs yet).
  - **Case flips**, joined on `case_id`: fixed (fail→pass), regressed (pass→fail), still-failing, plus cases present in only one run. Regressions listed with their diff reasons — the actionable part.
- **Guardrails**: refuse to compare when `cases_hash` differs (different dataset = meaningless deltas), overridable with `--force`, which skips case flips and marks deltas as not-like-for-like. Differing git_sha/prompt hash is fine — that's usually the point — but flagged in the header.
- **Rendering is deterministic** — f-string/table markdown, no LLM. Consistent with the hybrid-report direction in Smaller items: numbers come from computed fields, never a model.
- **Out of scope** (separate roadmap items): repeats/pass@k, confidence intervals, provider abstraction.

Work items:

- [ ] `RunComparison` model + comparison logic in `evals/scoring/compare.py` (tests first)
- [ ] Markdown rendering of header, delta tables, and case flips
- [ ] `compare` CLI command with interactive picker fallback, `-o`, and `--force`

## Planned: event applicability — raw events, agent-side correlation

Today's incoming events pre-solve the hardest real-world step: `arrival_delay` carries a `leg_index`, so the agent is told which leg is affected. In reality the event arrives as a vessel, voyage, and new ETA, and deciding *whether it applies to this shipment at all* is the first decision of manage-by-exception. Moving correlation into the agent's job is the most decision-relevant realism available (it passes the anti-goal test cleanly), and it enables the product-shaped use case of running one event against a set of shipments.

Design decisions (settled in discussion, 2026-08-15):

- **Events carry real-world identifiers, not `leg_index`.** Vessel/voyage (legs already have a faked conveyance string), port pair, dates. The agent correlates against the shipment state it already receives — no new prompt structure needed, but verify conveyance identifiers survive state serialization into the prompt.
- **The eval unit stays pairwise `(shipment, event)`.** The fan-out — one event against N shipments — is a runtime/product feature; the eval expresses it as N pairwise cases, some applicable, some distractors. This preserves the one-state-one-event-one-diff shape the scorer, reporter, and decision matrix are built on. Do not broaden the case to a shipment set.
- **Determinism is preserved.** The generator knows ground truth: it either derived the event from the shipment's own leg (applicable) or perturbed identifiers (not applicable). Answer keys still come free; a non-matching event is a new species of clean case with `should_act=False`.
- **Distractors are the new near-miss family.** Same vessel / different voyage, same lane / different vessel, same voyage / shipment already discharged. This is a better answer to the "richer scenario classes" gap than more `eta_confirmed` noise.
- **Applicability is scored as its own axis.** A failed case must distinguish "didn't match the event" from "matched it and acted wrong": tag cases `applicable` / `not_applicable` (plus `near_match` on lookalikes) and add a correlation row to the decision matrix.
- **"Injector" is renamed along with the rework.** "Inject" promises the event lands *in* this shipment; a distractor event is only staged *near* it. The contract — given a shipment, produce an event, the answer key, and tags — is authoring a scenario, not injecting a fault. One name for the whole family: do **not** split into Injector-vs-Distractor class families — same interface, same pipeline, and the report wants them as one slice dimension. `distractor` is a tag, not a class family. `is_applicable` keeps its name with a shifted reading: "can this scenario be staged against this shipment" (a distractor answers yes when it can build a convincing lookalike from the shipment's lane).

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
2. The statistical and comparison tooling (item 2) — what turns it from "runs evals" into "answers questions about models"
