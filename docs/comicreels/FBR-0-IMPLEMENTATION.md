# FBR-0 implementation ledger

Scope authority: [browser architecture](FLOW-BROWSER-FIRST-ARCHITECTURE.md) and
[checkpoint plan](../superpowers/plans/2026-09-27-flow-browser-refactor.md).
Current status/owner gates: [CHECKPOINTS.md](CHECKPOINTS.md).

## Design and decisions

- Implement in the canonical local checkout on `fbr/0-flow-browser-bootstrap`, as explicitly
  requested. No separate worktree; no commits or pushes for intermediate fixes.
- `agent/services/flow_browser_session.py` owns config, an OS-backed profile lease and one
  synchronous persistent Camoufox context. KBS wraps that existing page; it owns no lifecycle.
- KBS semantic capture is synchronous. Using an async page would risk treating a coroutine as
  captured text. FBR-0 uses a synchronous provider on one owning thread.
- The permanent profile guard matches the explicitly authorized local login helper. A helper
  marker still present after obtaining the guard requires reconciliation, never automatic deletion.
- Closing the owned browser must succeed before releasing the lease. An uncertain close blocks
  reopening. Directory identity is checked before each acquisition.
- Review repair: persist a provider owner marker under the OS guard. A crashed owner leaves the
  marker and the next acquisition requires reconciliation; clean close removes only its own
  marker. The local login helper also refuses an unreconciled provider marker.
- Passive `health()` is diagnostic only and never returns current readiness from cached auth.
  Only a fresh `capture_health()` can report readiness. An identity change latches the block.
- Auth evidence is separate from launch and semantic support. No default authenticated state;
  an account-identity probe must be grounded in the live Flow UI before use. Account identity
  remains in memory; public diagnostics expose only state/counts/logical profile name.
- No health HTTP request launches a browser. The provider is currently an opt-in shadow
  foundation, not an active generation transport. Extension and creative/business code stay intact.
- KBS optional dependency pin: `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
- `scripts/source_snapshot.py` snapshots current tracked bytes (including `git add -N` entries),
  respects deletions and refuses untracked inputs. It copies no ignored local data and refuses
  existing destinations. A hash manifest identifies exact test/deployment content.
- `scripts/verify_windows_batch.ps1 -WorkingTree` validates a fresh isolated local source
  snapshot and checks source stability afterward. Default committed mode remains available.
  The isolated snapshot is suitable for a dedicated read-only browser smoke; do not start the
  full application worker just to test FBR-0 because historical jobs may still exist.

## Execution ledger

- Provider/lease tests first failed because the implementation did not exist.
- Initial provider run found a missing installed KBS implementation (namespace import had no
  BrowserSession). Exact canonical KBS was installed in an isolated test-only package directory;
  neither the KBS checkout nor the application's runtime environment was changed.
- Provider/lease suite: 15 PASS, including real subprocess lock contention and fake browser
  close/reopen. This is offline evidence, not real Flow session continuity.
- Snapshot tests first failed because the helper did not exist; implementation then passed
  all four tests (current edits/additions/deletions, untracked omission guard, destination safety).
- First full local snapshot regression: 509 unit tests PASS; SDK 30 PASS / 7 SKIP;
  frontend build/lint PASS. These results preceded review repairs and do not validate later edits.
- Independent review found nondurable uncertain-close state and stale passive readiness;
  reproducing tests failed for each. Repairs plus a latched identity-change guard now pass:
  21 provider tests and 4 snapshot tests. Async-page rejection, entry-failure cleanup and
  wrong-thread ownership were also exercised.
- Frontend validation now installs its own `npm ci` from the snapshot lockfile instead of
  borrowing mutable runtime node_modules. The post-review full gate passed 515 unit tests,
  SDK 30 PASS / 7 SKIP, frontend clean install/build/lint. Targeted Python Ruff initially
  reported style issues; imports/literals/test context formatting were corrected, and deliberate
  exception sanitization/cleanup boundaries documented. Targeted Ruff now passes.
- Final verification after lint edits: `verify_windows_batch.ps1 -WorkingTree` PASS on VULE-PC,
  515 unit tests, SDK 30 PASS / 7 SKIP, npm ci/build/lint PASS. Snapshot digest:
  `e1bb144297509591a966566df21c270bcbcaf35f5db0f994af49e3e521d7bfbf`.
  Only evidence documentation was updated after this gate; implementation/test bytes unchanged.

## Owner login, observed adapter and final live gate

- Owner reported login complete on 2026-09-27. Login-helper PID 41132 returned
  CLOSED_LEASE_RELEASED before the test provider acquired the same profile.
- Observed real vi-VN UI at `https://flow.google.com/`: the visible account-information button
  contains a Google-account button with display name and email. Existing projects were visible;
  none were selected, created, renamed, deleted or generated.
- `flow_browser_auth.observe_flow_account` requires exactly one visible scoped account control
  with an explicit identity. It only reads the UI, returns UNKNOWN on missing/ambiguous/changed
  evidence and exceptions, and retains identity only in provider memory.
- Adapter tests: 12 initially failed (missing implementation), then passed. First live adapter
  smoke remained UNKNOWN because the DOM aria-label has a newline absent from the flattened
  semantic display. A new test reproduced that failure; whitespace normalization repaired it.
  The failed smoke closed its page and released the lease; no authenticated success was inferred.
- Final tests after repair: 528 unit PASS, SDK 30 PASS / 7 SKIP, fresh npm ci/build/lint PASS,
  targeted Ruff PASS. Exact tested source digest:
  `8a7e2bccd5176da8ef86fcf5325fb0df0e6b93b77703de4fac6c75bfb271719c`.
- Final live test used that isolated deployment, verified imported provider/auth module hashes
  and installed KBS direct_url commit. Two fresh captures at 06:17:35Z / 06:17:41Z returned
  authenticated and ready=true. Both produced supported nonempty KBS captures, blocked a
  competing lease and verified unchanged profile identity. One provider compared the account
  across reopen in memory. Both closes verified page.is_closed(), released lease and no owned
  durable marker. The receipt contains booleans/counts, never account identity or credentials.
- Evidence directory: `local-test-data/source-batch-e3f1408-5e90b33ed52e4f9ca7de76a6eaebc39f`.
  The active application's runtime and extension selection were not changed.
- Independent review of the new adapter found no material correctness issue. Optional stronger
  fixture assertions are deferred: explicit nested-selector regex assertion and outer-container
  count-zero case. Live newline repair is covered by RED-to-GREEN plus full-suite evidence.

Ruling: retain UNKNOWN for unobserved layouts/locales and absent explicit adapter injection —
only the observed vi-VN surface is verified — a future layout change blocks readiness and needs
new read-only evidence instead of silently accepting a different account.

Read-only usage on the owning synchronous thread, after acquiring the configured profile:

```python
from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_session import FlowBrowserSessionProvider, FlowProfileConfig

provider = FlowBrowserSessionProvider(FlowProfileConfig.load(), auth_probe=observe_flow_account)
with provider:
    health = provider.capture_health()  # UNKNOWN while UI is loading; never infer success.
```

The live gate bounded read-only capture retries to 35 seconds per open. The provider itself
does not wait for auth, register a worker, or change the selected application backend.

## Remaining gates

- Implementation committed/pushed at `c903fce89e98929c77e4ece4c91baba1481b592c`, with
  local/remote equality verified. This documentation-only receipt follows that checkpoint.
  OWNER_CONFIRM_REQUIRED before merge.
- After explicit owner confirmation: merge to the integration branch, verify exact merged SHA
  and final smoke/regression, record ACCEPTED/CLOSED. No FBR-1 or paid generation is authorized.
