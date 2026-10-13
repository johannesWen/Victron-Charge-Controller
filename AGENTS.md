# Repository agent instructions

## Orca coordination

Use Orca to coordinate substantial implementation work automatically. The main
agent owns task decomposition, worker supervision, integration, and the final
response. Choose roles and models without asking the user to assign them.
Keep trivial edits, such as a typo or a small documentation correction, with one
agent; do not create workers merely to fill every role.

Before delegating, load the installed `orca-cli` and `orchestration` skills and
their version-matched guides. Resolve the CLI as those skills describe. Use real
Orca workers, messaging, and managed worktrees; do not substitute another
subagent system or guess CLI commands, model IDs, or flags. If Orca is unavailable,
report the error and stop Orca operations. Continue suitable local work and state
that delegation could not run.

## Roles and ownership

| Role | Responsibility | When to use |
| --- | --- | --- |
| Coordinator | Inspect the request and repository, choose models, define dependencies and acceptance criteria, supervise workers, integrate results. | Main agent for every task. |
| Investigator | Trace behavior and callers, reproduce failures, identify relevant constraints. | Unclear requirements, unfamiliar code, or uncertain root cause. |
| Coder | Implement one bounded change with its affected callers, tests, and fixtures. | Substantial implementation; split independent areas between coders. |
| Tester | Exercise acceptance criteria, regressions, and failure paths; report reproducible failures. | Complex behavior or validation that benefits from a separate worker. |
| Reviewer | Independently inspect the actual diff and connected code for correctness, compatibility, and unnecessary complexity. | Every substantial implementation, before completion. |
| Security reviewer | Inspect trust boundaries, authorization, input validation, secrets, dependencies, and relevant physical safety risks. | Changes to HTTP/services, credentials, external data, workflows, dependencies, or battery/grid safety controls. |

Reviewers start read-only and return findings with severity, file locations,
concrete failure scenarios, and suggested fixes. The coordinator assigns fixes
to the owning coder and requests re-review of material fixes. A worker must not
be the sole reviewer of its own implementation.

## Automatic model selection

Before starting each worker, assess its scope, uncertainty, and consequence of
failure. Select the least costly available model capable of completing it
reliably. Role names alone do not determine model strength.

| Difficulty | Examples | Model capability and reasoning |
| --- | --- | --- |
| Low | Focused discovery, mechanical edits, documentation, running established checks. | Fast/lightweight model; low reasoning. |
| Medium | Bounded bug fixes, ordinary backend/frontend changes, regression tests, routine review. | Standard coding model; medium reasoning. |
| High | Unclear root cause, async/state interactions, changes across components, complex scheduling or persistence. | Strong coding/reasoning model; high reasoning. |
| Critical | Security-sensitive logic, battery/grid safety, difficult concurrency, unresolved high-impact findings. | Strongest available reasoning model; high or maximum reasoning. |

Resolve these tiers to the models actually exposed by the installed Orca runtime
and configured provider. Consult its guide/help for supported model discovery
and selection; pass an explicit supported model and reasoning setting when
available. Do not assume that a model available in the parent session is available
to Orca. Honor explicit user model or budget constraints.

Record each worker's role, selected model, difficulty, and a short reason in the
task dispatch. If a preferred model is unavailable, choose the next capable
available model. If model selection is unsupported, disclose that the configured
default is being used. Never claim to have changed the running coordinator's
model; delegate work above its capability to an appropriate worker.

Escalate one tier when a worker cannot explain a failure, repeats an unsuccessful
approach, or discovers greater risk. Send its evidence and remaining question to
the stronger worker instead of restarting the investigation. High-risk changes
require an independent reviewer at the same or a stronger capability tier.

## Execution workflow

1. Inspect the working tree and applicable instructions. Identify affected code,
   callers, tests, configuration, and user-visible behavior before assigning work.
2. Split work along independent file or component boundaries. Each dispatch must
   include the objective, relevant context, allowed files, acceptance criteria,
   dependencies, validation commands, and expected handoff.
3. Use Orca-managed child worktrees for concurrent code changes. Give each file
   one writer at a time; serialize overlapping work. Preserve existing user edits.
4. Run independent tasks concurrently within runtime and budget limits. Start
   dependent tasks only after their prerequisites are available. Give reviewers
   the exact candidate diff or commit, including integrated changes.
5. Supervise through Orca's documented messaging and completion events. Resolve
   worker questions within the authorized scope; ask the user only for decisions
   that cannot be inferred. Do not abandon workers after dispatch.
6. Require handoffs to include changed files/commits, checks and outcomes, findings,
   and remaining limitations. Integrate completed work, resolve conflicts, and
   validate the combined result. Resolve blocking correctness/security findings
   before declaring success.
7. Report the outcome, checks performed, and any remaining risks or unavailable
   delegation/model capabilities. Delegation does not authorize deployment,
   release publishing, live device changes, or destructive operations.

## Repository context and validation

- Home Assistant integration: `custom_components/victron_charge_control/`.
  Use the `ha-integration-knowledge` skill for integration work when available.
- Dashboard card: `frontend/src/`; reuse existing Lit components and patterns.
- Python tests: `tests/`. CI uses Python 3.14 and `requirements-dev.txt`;
  run focused tests during development and
  `pytest --cov=custom_components --cov-report=xml --cov-report=term`
  for integration-wide changes.
- Frontend checks, from `frontend/`: `npm test` and `npm run build`.
  The build writes the bundled card into the integration's `static/` directory;
  coordinate ownership of that generated file as well as its sources.
- CI and release validation: `.github/workflows/` and `.github/scripts/`.
  Match checks to the changed behavior; documentation-only edits need diff review,
  not application test runs.
- Preserve SOC protection, hysteresis, grid setpoint limits, watchdog behavior,
  and restored schedules. Exercise affected boundaries and unavailable-sensor
  paths in tests; do not validate by operating live battery/grid hardware.
- Prefer the smallest complete change. Reuse existing helpers and dependencies;
  avoid speculative abstractions and unrelated cleanup.
