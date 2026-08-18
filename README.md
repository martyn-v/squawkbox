# Squawkbox

An agent that watches shipment state changes and squawks when action is needed.

## What this is

Squawkbox is an evaluation harness for manage-by-exception freight agents. It answers one question: given a shipment's current state and an incoming event, does an LLM agent correctly decide whether to act, and does it pick the right actions?

The project has three parts:

1. **A case generator** (`evals/generation/`) that produces synthetic shipments from lane templates, progresses each one through its lifecycle to a random point, then injects a fault. Because cases are generated from known lane data and fault injectors, every case ships with its own answer key. No hand-labeling.
2. **An agent under test** (`src/squawkbox/`) that receives the shipment state plus the incoming event in a single prompt and replies with zero or more actions — or an empty list, meaning "nothing to do here".
3. **An eval runner** (`evals/runner.py` + `evals/scoring/`) that runs the agent over a case file and scores its actions deterministically against the answer key.

## Commands

The eval tooling is a click CLI invoked as a module. Running the agent requires a local [Ollama](https://ollama.com) instance.

```sh
uv run -m evals --help      # list available commands
uv run -m evals generate    # generate cases into evals/cases/cases.jsonl
uv run -m evals run         # run the agent over the cases, write a scored report to evals/results/
uv run -m evals summarize   # LLM-written markdown summary of a run report, picked interactively
uv run -m evals compare     # diff two run reports: metric deltas per slice and per-case flips
uv run -m evals push        # upload the cases file to Langfuse as a dataset
```

**`generate`**

- `--seed` — default 42
- `--count`/`-n` — default 30; total cases, lane templates cycled round-robin

**`run`**

- `--model` — a `provider/model` spec, default `ollama/gemma4:31b`
- `--temperature` — default 0.5
- `--label` — free-text record of what the run is testing
- `--summarize` — write the markdown summary immediately after the run
- `--no-langfuse` — skip [Langfuse mirroring](#langfuse)

**`summarize`**

- `--results-file` — omit it to pick from a list
- `--model`, `--temperature` — its own model settings, default temperature 0.2: summarization wants less creativity than the agent under test

**`compare`**

- two results files as arguments — omit them to pick two from a list
- `-o` — also write the comparison markdown to a file
- `--force` — compare across differing case files anyway

All commands accept path overrides; see `--help` on each.

## Layout

```
src/squawkbox/          the agent under test
  models/            domain models: shipment (Shipment, Leg, Event), events (incoming), actions
  agent.py           prompt construction + one LLM call, JSON reply parsed into actions
  llm.py             default Ollama model config
evals/
  models.py          the case contract: EvalCase, Expectation
  casefile.py        case file parsing, validation, and identity hash
  generation/        templates, shipment synthesis, fault injectors, generate loop
  scoring/           result models, action matching, aggregation, run comparison
  runner.py          run loop: agent per case, score, aggregate, write report
  report.py          LLM-written markdown summary of a run report
  langfuse.py        dataset push and the run-mirroring gate
  cli.py             click entry points
  data/data.yaml     lane templates and locations (the generator's input)
  cases/             generated cases (jsonl, git-ignored)
  results/           timestamped run reports (json)
```

## The core model

- A **shipment** is a state object (contacts, locations, one or more legs with ETD/ATD/ETA/ATA) plus an append-only list of events (`booked`, `gate_in`, `departed`, `arrived`, `delivered`) and a `current_time`.
- An **incoming event** is one of the event types listed under [Events and injectors](#events-and-injectors). The event describes what happened; it is *not* pre-applied to the shipment. Reconciling state is the agent's job.
- The **agent's reply** is a list of zero or more actions, cataloged under [Actions](#actions).

The expected reply for a delay: update the affected dates, notify the customer contact, and escalate when a later leg puts a connection at risk. For a routine confirmation: do nothing.

## How cases are generated

- **Lanes live in data, not code.** `evals/data/data.yaml` defines ten lane templates — direct ocean (e.g. Rotterdam→Singapore, Shanghai→LA), ocean transshipments up to a three-leg relay (e.g. Haiphong→Gothenburg via Singapore and Rotterdam), and air both direct and via hub (e.g. Bogotá→Miami, Amsterdam→Nairobi via Dubai) — with per-leg transit-time and dwell-time bounds, plus the location list. Parties and references come from Faker.
- **Everything is seeded.** Each case gets a child seed (`seed-template-variant`) recorded on the case, so any single case can be regenerated exactly.
- **Timelines are derived, not authored.** Leg dates are drawn within the template's bounds, then the shipment is progressed through its milestone sequence (booking, gate-in, per-leg departure/arrival, delivery) to a random point. That determines what has actually happened when the incoming event lands.
- **Faults come from injectors.** An injector is a class that says whether it applies to a shipment and, if chosen, produces the event *plus* the expected actions and tags. Each case picks uniformly at random among the injectors applicable to its shipment; the routine injector is always applicable, so the pool is never empty. All injectors are cataloged under [Events and injectors](#events-and-injectors).
- **Cases carry slicing metadata.** Tags like `direct`/`transshipment`, `pre_departure`/`underway`/`arrived`, `final_leg`/`connection_risk`, and `clean` let the report break results down by scenario shape.

## Events and injectors

Two distinct kinds of "event" exist. **Milestone events** (`booked`, `gate_in`, `departed`, `arrived`, `delivered`) are the shipment's own append-only history, written by the generator as it progresses the timeline. **Incoming events** (`src/squawkbox/models/events.py`) are the single stimulus the agent must react to; each is produced by exactly one injector.

### Incoming events

| Type | Fields | Meaning |
|---|---|---|
| `arrival_delay` | `leg_index`, `delay_days` | A leg currently underway will arrive late |
| `departure_delay` | `leg_index`, `delay_days` | A leg not yet departed will leave late |
| `rolled_sailing` | `leg_index`, `new_conveyance`, `new_etd`, `new_eta` | Cargo bumped to a later vessel/voyage |
| `customs_hold` | — | Shipment held at destination customs |
| `eta_confirmed` | `leg_index`, `eta` | Routine confirmation of the existing ETA — a no-op |

### Injectors

All injectors live in `evals/generation/injectors.py` and subclass `ScenarioInjector` (`is_applicable` + `inject`). Delay injectors draw 1–5 days; a rolled sailing shifts a fixed 7 days.

| Injector | Applicable when | Expected actions | Tags |
|---|---|---|---|
| `RoutineEventInjector` | Always | None — the agent must stay quiet | `routine`, `clean` |
| `ArrivalDelayInjector` | A leg is underway (ATD set, no ATA) | Update that leg's `eta`; notify the customer contact; escalate unless it's the final leg | `arrival_delay`, then `final_leg` or `connection_risk` |
| `DepartureDelayInjector` | A leg has not yet departed (no ATD) | Update that leg's `etd` and `eta`; notify; escalate unless final leg | `departure_delay`, then `final_leg` or `connection_risk` |
| `RolledSailingInjector` | Ocean shipment with a not-yet-departed leg | Update that leg's `conveyance`, `etd`, and `eta`; notify; escalate unless final leg | `rolled_sailing`, then `final_leg` or `connection_risk` |
| `CustomsHoldInjector` | Last milestone is `arrived` and the final leg has an ATA | Notify only | `customs_hold` |

Delay and roll injectors always target the *first* matching leg. `connection_risk` marks cases where a later leg exists, so a rebooking may be needed — hence the expected escalation. `RoutineEventInjector` is a placeholder (see its FIXME): it confirms an existing leg ETA rather than generating varied routine traffic.

**Known limitation — narrow-window injectors are starved.** Each case draws uniformly among the injectors applicable to its shipment, so slice sizes are a product of two filters: how wide the injector's lifecycle window is, and how crowded the pool is inside it. `CustomsHoldInjector` is the worst case: it applies only in the final-arrived-but-not-delivered slot (~1 lifecycle position, and transshipment arrivals don't count), where the only other applicable injector is routine — so roughly (shipments that stopped there) × ½. In a 100-case file that yielded n=4, a slice whose CI spans half the axis. Weighting the draw (see roadmap) can't fully fix this: the eligible-state count is a ceiling, so useful n for these injectors also needs biasing the lifecycle progression point toward the states they require.

### Future events (ideas, not implemented)

Candidates that would each test a decision shape the current events don't. Per the anti-goals, an event only earns a place if it changes what the agent must decide.

| Type | Meaning | What it tests that current events don't |
|---|---|---|
| `early_arrival` | An underway leg will arrive ahead of schedule | Updating dates in the *other* direction, and not escalating good news |
| `missed_connection` | Cargo failed its transshipment — the connection is already lost, not merely at risk | Escalation on certain damage vs. `connection_risk`'s possible damage |
| `customs_released` | A previously held shipment is cleared | Reacting to a resolution: notify, but nothing to fix or escalate |
| `cutoff_missed` | Cargo missed the gate-in cut-off and will not make its booked departure | Inferring the consequence (a roll is now inevitable) before the carrier says so |
| `booking_cancelled` | Carrier cancels the booking outright | Pure escalation — no property update can express this state |
| `port_congestion_advisory` | Advisory that the destination port is congested; no dates changed yet | Staying quiet on ambient noise that *sounds* actionable — a richer clean case than `eta_confirmed` |
| `cargo_damage` | Damage reported at a handling point | Free-text notification/escalation quality — material for the planned LLM judge |

## Actions

The vocabulary the agent replies with (`src/squawkbox/models/actions.py`). All payload fields are diffed by the scorer except those marked judge material.

### Current actions

| Type | Fields | Meaning |
|---|---|---|
| `update_property` | `path`, `new_value` | Correct a field on the shipment, addressed by path (e.g. `legs[0].eta`) |
| `notify` | `recipients`, `message` | Inform stakeholders; the message text is judge material, never diffed |
| `escalate` | `reason` | Hand over to a human operator; the reason text is judge material, never diffed |

### Future actions (ideas, not implemented)

Same admission rule as future events: an action earns a place only if it creates a decision boundary the current set can't express, and only if the generator can still produce a deterministic answer key.

| Type | Meaning | What it tests that current actions don't |
|---|---|---|
| `request_info` | Ask a party for missing information (hold reason, revised schedule, docs status) | The act-vs-ask boundary — declining to commit when the event doesn't say enough. The existing `customs_hold` already has this shape, so no event changes needed |
| `defer` | Note the event and re-check at a date | Act-now-vs-wait — calibrated patience on delays absorbed by buffer, a richer quiet than the binary stay-silent |
| `rebook_leg` | Pick one of the alternative sailings offered in the event | Optimization among valid options, not just recognition — a worse-but-valid pick is a natural near-miss. Requires `rolled_sailing` to carry alternatives, so it belongs with the event-correlation rework |
| `cancel_booking` | Abandon the booking outright | Severity calibration — almost never the expected action, so any emission is a clean false positive measuring trigger-happiness |

`request_info` and `defer` blur the act/stay-quiet binary: the decision matrix would need an "asked/deferred" cell (or tag), otherwise a model that defers everything looks conservatively good.

## How scoring works

Scoring is a deterministic diff between the agent's action list and the expected one, with one-to-one matching:

1. **Exact pass** — agent actions claim expected actions they match completely.
2. **Near-miss pass** — leftover agent actions pair with unclaimed expectations of the same type (a notify to the wrong recipient, an ETA moved to the wrong date), recording human-readable field mismatches.
3. Whatever remains is **extra** (agent did it, nobody asked — false positive) or **missing** (expected, never done — false negative).

A case passes only when all three failure buckets are empty. The report aggregates:

- **Precision and recall**, micro-averaged overall and per slice (by injector, by tag, by action type)
- **95% confidence intervals** (Wilson, via statsmodels) on every pass rate, overall and per slice — so a thin slice reads as the anecdote it is instead of masquerading as a measurement
- **A decision matrix** for the act/stay-quiet call itself — including the false-alarm rate on clean cases, because a noisy agent gets ignored by ops staff
- **Per-case latency**

Each run writes a timestamped JSON report to `evals/results/` containing the summary plus every per-case diff.

## Run summaries

The JSON report is exhaustive but not readable. `summarize` hands the whole report to an LLM, which writes a stakeholder-facing markdown summary next to it (`<run>.md`): headline metrics, notable failures with concrete examples, and recommendations. This is presentation only — all numbers come from the deterministic scorer, and the LLM has no part in deciding whether a case passed. It is also not the planned LLM judge (see below), which would score individual message quality rather than narrate a finished run.

## Comparing runs

`compare` diffs two run reports to answer "did this change help" — model A vs B, prompt v1 vs v2. The older run is the baseline, the newer the candidate, regardless of argument order. The report has three sections:

- **Header** — what was tested on each side (model, temperature, label, git sha, prompt hash), with differing rows flagged. Differing git sha or prompt hash is normal — that's usually the point of the comparison.
- **Summary deltas** — pass rate, precision, and recall as `baseline → candidate (Δ)` for overall and each slice (injector, tag, action type) with each slice's `n` visible, plus the decision-matrix rates (false alarm, missed act). Pass rates carry their 95% CI as `±` half-width (e.g. `0.82 ±0.07`) — approximate, since Wilson intervals are asymmetric; the exact bounds are in the report JSON.
- **Case flips** — joined on case id: regressed cases first with their diff reasons, then fixed, still-failing, and cases present in only one run.

Comparing runs from different case files is refused — deltas across datasets are meaningless. `--force` overrides: the deltas are flagged as not like-for-like and case flips are omitted. Rendering is deterministic markdown (rich in the terminal, plain text via `-o`); no LLM is involved anywhere.

## Langfuse

Runs can optionally be mirrored to a local [Langfuse](https://langfuse.com) instance for the trace and experiment-comparison UI. The local JSON report stays the source of truth — Langfuse is a mirror, and everything about it is best-effort: if the server is down, credentials are missing, or the dataset doesn't match, `run` logs a warning and proceeds locally as if Langfuse didn't exist.

### Setup

Langfuse runs locally via its self-contained compose file (it pulls published images; expect ~6 containers and a couple of GB of RAM):

```sh
curl -O https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml
docker compose up -d
```

Then create an organization, project, and API key pair in the UI at `http://localhost:3000`, and put the keys in `.env` at the repo root (the CLI loads it):

```sh
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://localhost:3000
```

### Usage

`push` uploads the cases file as a dataset named `cases-seed{seed}-n{count}`, one item per case keyed by `case_id`, with the case-file identity hash in the dataset metadata. Items are upserted, so re-pushing the same generation is idempotent; a different generation gets a different dataset name, keeping old runs attached to the cases they actually ran against.

`run` then mirrors automatically: each run becomes a Langfuse experiment on that dataset (named `{label} {timestamp}`), with one trace per case and the deterministic scores (`passed`, `precision`, `recall`) attached. The experiment machinery is transport only — scoring is the same diff written to the local report, and cases that error produce an unscored trace marked ERROR, matching the local `diff: null`. The hash gate means a run never attaches to a dataset that doesn't match the local case file; regenerate → re-push → run.

Experiments on a v4 server are append-only — there is no delete, in the API or the UI — so give throwaway runs an obvious `--label`, or skip mirroring entirely with `--no-langfuse`.

## Not built yet

- **LLM-as-judge** for the fuzzy outputs — notification message and escalation reason quality. The action models already set those fields aside as judge material; nothing consumes them yet.
- **Richer scenario classes** — near-misses (an ETA slip that self-corrects) and noise streams currently exist only as intent; today's clean cases are a single generic ETA confirmation (see the FIXME on `RoutineEventInjector`).
- **Injector configuration** — which injectors run, and at what ratio, is currently a hardcoded list rather than run config.

## What this is not

This is an eval fixture, not a freight simulator. Explicit anti-goals:

- No real sailing schedules or live data sources
- No exhaustive port or carrier lists
- No statistically weighted realism distributions
- No production TMS features

If a piece of realism does not change what the agent must decide, it does not belong here.

## Why this exists

Evaluating generative agents on operational decisions is an open problem. Manage-by-exception is the core workflow of freight operations, and it compresses that problem into a crisp, measurable shape: one state, one event, one decision, one diff. This project explores how far deterministic scoring can carry agent evaluation before an LLM judge is needed, and where agents break as scenario subtlety increases.
