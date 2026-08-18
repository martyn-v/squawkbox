# Roadmap

Findings from a harness review (2026-08-15), roughly in order of how much they hurt. Completed items are trimmed as they land.

## Status (2026-08-17)

The project is at a natural stopping point. Everything the README claims is built and working — generate → run → score → summarize → compare → Langfuse mirror — and the gaps are honestly labeled (Not built yet, FIXMEs, this file). Measured against its own question ("how far can deterministic scoring carry agent evaluation"), the answer is in: far — answer keys for free, deterministic diffs, slice reporting, run comparison, no judge needed.

Two caveats if parked as-is: (1) the numbers are estimates without error bars — overall n is fine now (100 cases / 10 templates as of 2026-08-17; at 82/100 the 95% CI is roughly ±8pp) but nothing computes it, and the fault slices are starved by imbalance, not count: routine is always applicable so clean cases take ~57% of the uniform draw, leaving slices like customs_hold at n=4 — meaningless at any overall count; (2) the second half of the research question ("where agents break as subtlety increases") is unprobed — events pre-solve correlation via `leg_index`, and clean cases are one generic ETA confirmation.

The close-out plan: one short push — CI computation in the aggregate plus injector-mix weighting (the "Injector configuration" item from README's Not built yet), plus the policy-in-prompt labeled comparison (item 1's open bullet) — then park. That converts the project from "harness that runs" to "harness that produced a defensible finding". Per-case repeats (item 2) are demoted to optional: with case count already scaled, they only buy trustworthy per-case flips in `compare`. The correlation rework stays documented below as the next chapter, worth doing only for its own interest, not as wrap-up. The smaller items (run ergonomics, hybrid report, tie-breaking) are polish for a user this project may never have — skip.

## 1. The prompt contradicts the schema

`src/squawk/agent.py:15` tells the model `"recipients" is a list of recipient names`, but the schema demands full `Contact` objects (`{name, email}`). A model that follows the prose emits `["Jane Doe"]`, validation fails, and the case is recorded as an error failure.

Related prompt/model inconsistencies:

- [x] Fix the recipients prompt line to match the schema
- [ ] The prompt never tells the agent _when_ to escalate, or who "the customer contact" is — the expectation encodes a specific policy (notify customer contact; escalate iff a later leg exists) the agent must guess. Fine if deliberate (measuring whether models infer it), but it should be a choice, not an accident.

## 2. No statistical rigor around a stochastic system

The runner does one attempt per case at temperature 0.5 and reports point estimates. Case count is already scaled (100 cases / 10 templates) — with one independent sample per case, more cases is a statistically valid substitute for repeats at the aggregate level, and it buys scenario coverage too. Remaining:

- [x] **Confidence intervals** — `SliceScore.pass_rate_ci` (95% Wilson via statsmodels `proportion_confint`) is a computed field, so it lands in every report JSON automatically, and `compare` renders it as `0.82 [0.73, 0.88] → …`. Note if repeats are ever added: attempts within a case are correlated, so CIs must stay case-level, never pooled over attempts (docstring on the field says the same)
- [ ] **Injector-mix weighting** — the real slice-size problem is imbalance, not count: routine is always applicable and takes ~57% of the uniform draw, leaving fault slices at n=4–17. Weight the draw (or set a clean-case ratio) so fault slices reach useful n. This is README's "Injector configuration" not-built-yet item. Caveat (found 2026-08-18): draw weighting alone has a ceiling for narrow-window injectors — customs_hold applies only in the final-arrived-not-delivered slot (~8 of 100 generated shipments; in that slot the pool is just {routine, customs_hold}, hence n=4). Reaching useful n there also means biasing the lifecycle progression point toward the states a starved injector needs, not just reweighting the draw among applicable injectors
- [ ] *(optional, demoted)* **Repeats/trials per case** — only needed to make `compare`'s per-case flips trustworthy (distinguish "went 5/5 → 0/5" from "always was 3/5 flaky") and to measure per-case consistency. The attempt-level diff scorer is unchanged; the cost is schema (attempt field), case-grouped aggregation, and redefining what a flip means when pass is a rate

## Smaller items

- [ ] **Hybrid report: template the metrics, LLM only for failure narrative**: the report LLM currently transcribes precision/recall/pass rates from `summary` into prose — small local models get numbers wrong, for zero gain, since `AggregateScore` already computes them. Render the metrics/slice tables deterministically (f-string/Jinja) and scope the LLM prompt down to one job: read the sampled failure diffs and describe recurring failure patterns, appended as an analysis section. Each tool does what it's good at; numbers in the report become trustworthy enough to quote
- [x] **Inconsistent defaults**: the CLI now imports `DEFAULT_MODEL` / `DEFAULT_MODEL_TEMPERATURE` from `src/squawkbox/llm.py`, and the agent falls through to the same factory defaults — one source of truth for every entry point (`default_model()` and its temperature-0 default are gone)
- [x] **Dead dependency**: `langgraph` is in `pyproject.toml` but never imported — the agent is a single LLM call
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

## Considered: configurable rules — Events → Impact → Actions

Today the operating policy (delay → update dates, notify customer, escalate unless final leg) is hardcoded three times over: implicitly in each injector's expectation-building, in README prose, and nowhere in the prompt — the agent has to guess it (the deliberate-or-accident question flagged in item 1). In production a user would configure this policy, not inherit it from eval code. The move: make policy a declarative rule set that is the single source of truth for both the answer key and the prompt. That reframes the eval itself — from "can the model guess our conventions" to "can the model follow configured policy", which is the actual production job.

Design decisions (settled in discussion, 2026-08-17):

- **Three stages, and the middle one earns its place.** *Impact functions* (code, one per event type) compute what an event means for a shipment — pure date/state arithmetic producing a normalized `Impact` (field changes + flags like `connection_at_risk`). *Rules* (data) match on impact and bind actions. Matching on impact rather than raw event type means `arrival_delay` and `rolled_sailing` share the same rules; a new event type needs an impact function, not a new rule set. Users never configure date arithmetic.
- **Rules are YAML parsed into pydantic, with a closed predicate vocabulary** (`flag`, `any_flag`, `has_field_changes`, `event_type`, `transport_mode`) — not an expression DSL (jsonlogic/CEL rejected: unvalidatable, unrenderable as prose, YAGNI at five event types). The vocabulary grows one named predicate at a time when a real need appears. Recipients are roles (`customer_contact`) resolved against the shipment at evaluation time. All matching rules contribute actions (additive, deduped); each rule carries a `rationale` string.
- **One engine, two consumers.** `evaluate(rules, shipment, event) -> Expectation` in a new `src/squawkbox/rules/` module; injectors call it instead of hand-building expectations (no matching rules → `should_act=False`), and tags can derive from matched rule names + impact flags. `rules_to_prompt_text(rules)` renders each rule as a policy bullet (condition prose + rationale + action) into the system prompt, alongside `actions_to_prompt_text()` — same derive-don't-duplicate principle as the vocabulary-blocks item.
- **Behavior-preserving by construction.** The default rule set must reproduce today's hardcoded expectations exactly — a golden test pins this. `Expectation`, scorer, and runner are untouched. Per-tenant rule storage is a production concern, out of scope; the default rule set is a YAML file in the repo.
- **Putting policy in the prompt is an eval-design change to task difficulty** (same caveat as describing events): the guess-the-policy baseline disappears. Make the before/after a deliberate `--label`ed comparison run — that comparison is itself interesting data.

Work items:

- [ ] `Impact` model + per-event-type impact functions (registered by `type` tag)
- [ ] Rule/predicate pydantic models + YAML loading, with the default rule set mirroring current policy
- [ ] `evaluate()` engine: match rules, expand action templates, resolve roles → `Expectation`
- [ ] `rules_to_prompt_text()` + wire into the agent system prompt (labeled comparison run)
- [ ] Slim injectors to applicability + event synthesis; expectations and tags come from the engine
- [ ] Golden test: default rules reproduce current hardcoded expectations exactly; snapshot test on the renderer

**Does the LLM still have a job at that point?** For the core loop, honestly, no — once the event is structured and policy is deterministic rules, `evaluate()` *is* the agent, and running an LLM to re-derive what a pure function computes is paying latency and stochasticity for nothing. The LLM earns its place exactly where the rules stop:

- **Messy input.** Real events arrive as carrier emails, EDI fragments, portal scrapes — not as `ArrivalDelayEvent`. Normalizing raw input into a structured event, and deciding whether it applies to this shipment at all, is judgment work. This is what the correlation rework is reaching for; that's the LLM-shaped part of the job.
- **The uncovered tail.** The event that matches no rule still needs a decision — act, or escalate intelligently with a reason a human can use. An LLM handling the open world beats a rule engine silently doing nothing.
- **The generative fringe.** Notification prose, escalation reasons, run summaries — the parts of the action models already marked "judge material".

So the production architecture inverts: **rules execute, LLM interprets** — the LLM normalizes/correlates raw input into events, rules deterministically produce actions. Or the softer variant: LLM proposes, rules verify — the same `evaluate()` doubles as a runtime guardrail, with disagreement → escalate. Either way one engine serves evals and production, which is a point for this item, not against it. The eval still measures something real: following configured policy over messy state is what you need to trust the model at the edges rules can't check, and the labeled before/after comparison decomposes current failures into policy ignorance vs reasoning failure — a split that only exists because the rule system does. The rule system doesn't obsolete the LLM; it evicts it from the part of the job it was always the wrong tool for.

**Scope call (2026-08-17): out of scope for this project.** This is a production/product feature; this project is an eval harness. The Impact stage, YAML rules, predicate vocabulary, and `rules_to_prompt_text()` only pay off when a real user is configuring real policy — parked here, not planned. The one slice that *is* eval work, and cheap: put the policy in the prompt as a hand-authored paragraph (2–3 sentences — update dates, notify customer, escalate when a later leg exists), no rule engine, then do the `--label`ed before/after run. That alone yields the policy-ignorance-vs-reasoning-failure decomposition and settles item 1's open question ("agent must guess the policy — deliberate or accident?") by making it a measured choice.

Sequencing, if ever built: after the correlation rework — it renames/reshapes the injector family this builds on, and impact functions want the identifier-carrying event models, not `leg_index`.

