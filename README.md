# Squawkbox

An agent that watches shipment state changes and squawks when action is needed.

## What this is

Squawkbox is an evaluation harness for manage-by-exception freight agents. It answers one question: given a shipment's current state and an incoming mutation, does an LLM agent correctly decide whether to act, and does it pick the right actions?

The project has three parts:

1. **A scenario generator** that produces synthetic shipments with full Event histories, then applies a mutation. Because scenarios are generated from known lane data and fault injectors, every test case ships with its own answer key. No hand-labeling, ever.
2. **An agent under test** that receives the shipment state plus the incoming mutation and responds with zero or more follow-up mutations (update ETA, notify a party, flag a risk) or explicitly does nothing.
3. **An eval runner** that scores agent output deterministically against the answer key, and uses an LLM judge only for the genuinely fuzzy part: the quality of any human-facing message the agent drafts.

## Commands

The eval tooling is a click CLI invoked as a module:

```sh
uv run -m evals --help      # list available commands
uv run -m evals generate    # generate evaluation cases into evals/cases/
```

## The core model

Everything is a mutation against a shipment.

- A shipment is a state object plus an append-only list of Events.
- An incoming mutation is either an appended Event (vessel departed, container gated out) or a direct property change (ETA revised, consignee updated). Incoming mutations are already applied when the agent sees them. The agent reacts to what happened; it is not a gatekeeper.
- The agent's response is itself a set of mutations. Scoring applies the agent's mutations and deep-diffs the resulting state against the expected state.

This symmetry keeps the test format uniform: state in, mutations out, diff to score.

## What gets measured

**Deterministic (runs on every commit):**

- Intervention precision and recall: did the agent act when it should, stay quiet when it shouldn't
- Action correctness: do the agent's mutations match the expected state change
- False-alarm rate on clean and near-miss scenarios, because a noisy agent gets ignored by ops staff

**LLM-as-judge (fuzzy outputs only):**

- Clarity and appropriateness of drafted notifications
- Whether the agent's stated reasoning cites the events that actually matter

Judge calibration uses synthetic contrast pairs: deliberately degraded message variants that the judge must rank below clean ones. No human labels required.

## How scenarios are generated

- **Reference data lives in data files, not code.** A curated set of real UN/LOCODE ports, plausible carriers, and Faker-generated parties.
- **Lanes, not random port pairs.** Lanes are defined in data with origin, destination, optional transshipment, and transit-time bounds. Randomness is seeded and lives inside lane bounds, so scenarios look varied but stay reproducible.
- **Timelines are derived, not authored.** A per-shipment-type template (booking, gate-in, departure, transshipment, arrival, gate-out) combined with lane transit times produces the clean Event sequence. The same derivation logic serves as the reference implementation that computes answer keys.
- **Faults are injected by choice, not chance.** Each fault injector is a plugin that takes a clean shipment and returns a mutated event plus the expected follow-up actions. A run config selects which injectors apply and at what ratio. The injected fault and expected outcome are recorded alongside the scenario.

Interesting scenario classes include subtle exceptions (a delay on a transshipment leg that breaks a tight connection), near-misses (an ETA slip that self-corrects), and pure noise streams that test the agent's ability to do nothing.

## What this is not

This is an eval fixture, not a freight simulator. Explicit anti-goals:

- No real sailing schedules or live data sources
- No exhaustive port or carrier lists
- No statistically weighted realism distributions
- No production TMS features

If a piece of realism does not change what the agent must decide, it does not belong here.

## Why this exists

Evaluating generative agents on operational decisions is an open problem. Manage-by-exception is the core workflow of freight operations, and it compresses that problem into a crisp, measurable shape: one state, one event, one decision, one diff. This project explores how far deterministic scoring can carry agent evaluation before an LLM judge is needed, and where agents break as scenario subtlety increases.
