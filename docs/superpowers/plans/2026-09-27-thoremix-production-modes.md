# Thỏ Remix production modes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; a fresh reviewer checks the final change.

**Goal:** Add durable daily advance-production quotas, a ready queue and one-package posting slots.
**Architecture:** SQLite ledger plus finite toolkit methods; Windows Scheduler owns wake-ups.
**Tech Stack:** Existing Python/Tk/SQLite/PowerShell, existing FlowKit/KRP adapters.
**Spec:** docs/superpowers/specs/2026-09-27-thoremix-production-modes.md

## Global Constraints

- 1–1000 successful clips/day, default5; Vietnam timezone; no blind retry of unknown effects.
- Default scheduled mode; preserve paused state, existing sources/packages, KRP journal and tray.
- Local-source-first; preserve unrelated FBR2 changes; no merge or paid live generation requested.
- Actual producer readiness remains false until its existing integration is complete.

## Review Focus

- Restart/crash after package promotion but before quota update: reconcile and count once.
- Unknown generation and quota reduction: never bypass unresolved work or exceed the new cap.
- Pausing/changing mode during a batch: stop before next source; leave current operation owned.
- Posting during a long batch: serialized single-package slot, no backlog burst or duplicate effect.
- Malformed images, exhausted sources and global outage: bounded logs, no infinite source loop.

### Task1: Config and durable production/posting ledgers

Files: config.py, core.py, new production_queue.py; new test_thoremix_production_queue.py.
Interfaces: ProductionQueue.summary(now), produce_ahead(settings,...), run_slot(settings,clock,...),
dispatch(settings,...), configure_production(settings,mode,limit), set_enabled(settings,enabled).
- [x] Write failing tests for validation/migration, success quota with failures, restart, uncertainty,
  date boundary, empty input, paused/global block and one FIFO package per slot.
- [x] Implement with real local package validation, SQLite receipts and per-clip locks.
- [x] Run focused tests and relevant existing core/publication tests; inspect failures.

### Task2: CLI, SDK, GUI and scheduler

Files: cli.py, sdk.py, desktop.py, dashboard.py, Install-Schedule.ps1; core/dashboard tests.
- [x] Test settings CLI/SDK persistence and passive GUI, bind the finite queue APIs.
- [x] Add production mode controls, daily progress/error report and durable scheduled dispatcher.
- [x] Verify pause controls are available while an early batch is active.

### Task3: Review, install and acceptance

- [x] Fresh independent review focused on the above five failure classes; repair material findings.
- [x] Run full unit suite, lint; build stable from canonical source preserving current runtime.
- [x] Inspect real GUI, native tray lifecycle and scheduled action definitions.
- [x] Verify installed real-provider readiness block consumes no source/paid effect and does not
  alter paused state. Clearly report the still-unfinished actual video producer.
- [x] Update current-truth documentation and ledger. No unrelated commits/merges.

