# Squawkbox

An agent that watches shipment state changes and squawks when action is needed.

## What this is

Squawkbox is an evaluation harness for manage-by-exception freight agents. It answers one question: given a shipment's current state and an incoming event, does an LLM agent correctly decide whether to act, and does it pick the right actions?

The project has three parts:

1. **A case generator** (`evals/generation/`) that produces synthetic shipments from lane templates, progresses each one through its lifecycle to a random point, then injects a fault. Because cases are generated from known lane data and fault injectors, every case ships with its own answer key. No hand-labeling.
2. **An agent under test** (`src/squawk/`) that receives the shipment state plus the incoming event in a single prompt and replies with zero or more actions — or an empty list, meaning "nothing to do here".
3. **An eval runner** (`evals/runner.py` + `evals/scoring/`) that runs the agent over a case file and scores its actions deterministically against the answer key.

## Commands

The eval tooling is a click CLI invoked as a module. Running the agent requires a local [Ollama](https://ollama.com) instance.

```sh
uv run -m evals --help      # list available commands
uv run -m evals generate    # generate cases into evals/cases/cases.jsonl
uv run -m evals run         # run the agent over the cases, write a scored report to evals/results/
uv run -m evals summarize   # LLM-written markdown summary of a run report, picked interactively
```

`generate` takes `--seed` (default 42) and `--count`/`-n` (default 30, total cases; lane templates are cycled round-robin). `run` takes `--model` (default `gemma4:31b`) and `--temperature` (default 0.5), plus `--label` to record what the run is testing and `--summarize` to write the markdown summary immediately after the run. `summarize` takes `--results-file` (omit it to pick from a list) and its own `--model` and `--temperature` (default 0.2 — summarization wants less creativity than the agent under test). All accept path overrides; see `--help` on each.

## Layout

```
src/squawk/          the agent under test
  models.py          domain models: Shipment, Leg, Event, incoming events, actions
  agent.py           prompt construction + one LLM call, JSON reply parsed into actions
  llm.py             default Ollama model config
evals/
  models.py          the case contract: EvalCase, Expectation
  generation/        templates, shipment synthesis, fault injectors, generate loop
  scoring/           result models, action matching, aggregation
  runner.py          run loop: agent per case, score, aggregate, write report
  report.py          LLM-written markdown summary of a run report
  cli.py             click entry points
  data/data.yaml     lane templates and locations (the generator's input)
  cases/             generated cases (jsonl, git-ignored)
  results/           timestamped run reports (json)
```

## The core model

- A **shipment** is a state object (contacts, locations, one or more legs with ETD/ATD/ETA/ATA) plus an append-only list of events (`booked`, `gate_in`, `departed`, `arrived`, `delivered`) and a `current_time`.
- An **incoming event** is one of the event types listed under [Events and injectors](#events-and-injectors). The event describes what happened; it is *not* pre-applied to the shipment. Reconciling state is the agent's job.
- The **agent's reply** is a list of actions:
  - `update_property` — correct a field, addressed by path (e.g. `legs[0].eta`)
  - `notify` — inform stakeholders (the message text is reserved for a future LLM judge, never diffed)
  - `escalate` — hand over to a human operator (likewise, the reason text is judge material)

The expected reply for a delay: update the affected dates, notify the customer contact, and escalate when a later leg puts a connection at risk. For a routine confirmation: do nothing.

## How cases are generated

- **Lanes live in data, not code.** `evals/data/data.yaml` defines lane templates (currently Rotterdam→Singapore direct ocean, Rotterdam→Cartagena via Panama transshipment, Bogotá→Miami air) with per-leg transit-time and dwell-time bounds, plus the location list. Parties and references come from Faker.
- **Everything is seeded.** Each case gets a child seed (`seed-template-variant`) recorded on the case, so any single case can be regenerated exactly.
- **Timelines are derived, not authored.** Leg dates are drawn within the template's bounds, then the shipment is progressed through its milestone sequence (booking, gate-in, per-leg departure/arrival, delivery) to a random point. That determines what has actually happened when the incoming event lands.
- **Faults come from injectors.** An injector is a class that says whether it applies to a shipment and, if chosen, produces the event *plus* the expected actions and tags. Each case picks uniformly at random among the injectors applicable to its shipment; the routine injector is always applicable, so the pool is never empty. All injectors are cataloged under [Events and injectors](#events-and-injectors).
- **Cases carry slicing metadata.** Tags like `direct`/`transshipment`, `pre_departure`/`underway`/`arrived`, `final_leg`/`connection_risk`, and `clean` let the report break results down by scenario shape.

## Events and injectors

Two distinct kinds of "event" exist. **Milestone events** (`booked`, `gate_in`, `departed`, `arrived`, `delivered`) are the shipment's own append-only history, written by the generator as it progresses the timeline. **Incoming events** (`src/squawk/models/events.py`) are the single stimulus the agent must react to; each is produced by exactly one injector.

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

## How scoring works

Scoring is a deterministic diff between the agent's action list and the expected one, with one-to-one matching:

1. **Exact pass** — agent actions claim expected actions they match completely.
2. **Near-miss pass** — leftover agent actions pair with unclaimed expectations of the same type (a notify to the wrong recipient, an ETA moved to the wrong date), recording human-readable field mismatches.
3. Whatever remains is **extra** (agent did it, nobody asked — false positive) or **missing** (expected, never done — false negative).

A case passes only when all three failure buckets are empty. The report aggregates:

- **Precision and recall**, micro-averaged overall and per slice (by injector, by tag, by action type)
- **A decision matrix** for the act/stay-quiet call itself — including the false-alarm rate on clean cases, because a noisy agent gets ignored by ops staff
- **Per-case latency**

Each run writes a timestamped JSON report to `evals/results/` containing the summary plus every per-case diff.

## Run summaries

The JSON report is exhaustive but not readable. `summarize` hands the whole report to an LLM, which writes a stakeholder-facing markdown summary next to it (`<run>.md`): headline metrics, notable failures with concrete examples, and recommendations. This is presentation only — all numbers come from the deterministic scorer, and the LLM has no part in deciding whether a case passed. It is also not the planned LLM judge (see below), which would score individual message quality rather than narrate a finished run.

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
