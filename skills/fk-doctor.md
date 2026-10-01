# fk-doctor — Browser-Only FlowKit Diagnostics

Diagnose Flow/browser-session, FastAPI, worker, reconciliation, paid-gate and
YouTube pipeline errors without mutating the persistent browser profile.

Usage: `/fk-doctor [error-or-context]`

## First principles

1. Flow transport is **browser-only**. The retired Chrome extension/WebSocket RPC
   bridge is not a fallback or recovery target.
2. The existing persistent signed-in Flow profile is authoritative. Never clear
   cookies/storage, sign out, create a replacement profile, copy credentials, or
   delete profile/lease files as a shortcut.
3. Browser readiness is not paid authorization.
4. `effect=unknown`, `RECONCILIATION_REQUIRED` and
   `PAID_RECONCILIATION_REQUIRED` are **non-retryable** until reconciled.
5. Paid generation is never a transport diagnostic.

## Evidence to collect

```bash
curl -s http://127.0.0.1:8100/health
curl -s http://127.0.0.1:8100/api/flow/backend-status
curl -s http://127.0.0.1:8100/api/requests?status=FAILED
curl -s http://127.0.0.1:8100/api/requests?status=PROCESSING
```

Healthy browser transport requires:
- `backend_ready: true`
- `browser_session_ready: true`
- `authentication: "authenticated"`
- `lease_held: true`

Read `reconciliation_required`, `pending_intents` and
`paid_dispatch_enabled` separately. A healthy browser does not grant paid
generation.

## Browser/profile fixed codes

| Code | Meaning | Safe action |
|---|---|---|
| `BROWSER_NOT_READY` | Current browser evidence is not ready | Inspect session/auth/lease fields; do not submit generation |
| `PROFILE_CONFIG_REQUIRED` | No profile binding configured | Point `COMICREELS_FLOW_PROFILE_CONFIG` to the existing binding JSON |
| `PROFILE_CONFIG_INVALID` | Binding JSON is malformed/unsupported | Correct the binding metadata only; do not replace the profile |
| `PROFILE_NOT_FOUND` | Bound profile directory is unavailable | Reconcile the configured existing profile path |
| `PROFILE_CHANGED` | Directory identity changed after binding | Stop and reconcile; do not silently accept a replacement directory |
| `PROFILE_BUSY` / `PROFILE_NATIVE_BUSY` | Another owner/browser process holds the profile | Stop competing ownership and retry readiness later |
| `PROFILE_RECONCILE_REQUIRED` | Lease/ownership is ambiguous | Reconcile ownership explicitly; do not delete lock/profile files |
| `PROFILE_LEASE_REQUIRED` | Browser action has no valid lease | Restore the normal backend lifecycle; do not bypass the lease |
| `IDENTITY_UNVERIFIED` / `IDENTITY_CHANGED` | Signed-in identity evidence is absent/changed | Stop effects and verify the same existing profile/session |

If `authentication="signed_out"`, stop the workflow and perform the approved
interactive sign-in in the **same** bound profile. Do not clear browser state.

## Reconciliation and paid-effect codes

| Code | Meaning | Safe action |
|---|---|---|
| `RECONCILIATION_REQUIRED` | A durable mutation outcome is ambiguous | Inspect durable state; do not auto-resend |
| `PAID_RECONCILIATION_REQUIRED` | Paid image may already have been accepted | Terminal for automatic retry; reconcile intent/receipt |
| `PAID_DISPATCH_DISABLED` | Normal paid switch is locked | Expected unless an approved activation/validation path exists |
| `PAID_AUTHORIZATION_REQUIRED` | Correct in-memory authorization capability absent | Do not synthesize one from env/config/API |
| `PAID_IDEMPOTENCY_REQUIRED` | Durable business key missing | Use persisted request id; never create a retry-specific key |
| `PAID_SINGLE_SHOT_REQUIRED` | Request attempted a multi-variant paid submit | Use exactly one paid image per authorized shot |
| `PAID_VALIDATION_SHOT_ALREADY_USED` | One-shot validation capability consumed | Do not retry through the same session |

## Operation/restart codes

| Code | Meaning | Safe action |
|---|---|---|
| `OPERATION_BINDING_REQUIRED` | Remote operation has no durable project binding | Reconcile the operation/project pair; do not guess and resubmit |
| `OPERATION_BINDING_CONFLICT` | Durable sources disagree on the project | Stop polling/submission until reconciled |
| `POLL_READ_UNAVAILABLE` | Read-only poll failed this round | Keep the same durable operation id; retry the read, not generation |
| `MEDIA_READ_UNAVAILABLE` | Media URL read failed | Retry the read; do not create another remote effect |

SQLite `request.request_id` is the durable remote operation id. Browser state
stores its project binding. After restart, the worker must re-poll that operation
instead of submitting a replacement.

## Flow-native errors

| Error | Safe handling |
|---|---|
| `PUBLIC_ERROR_UNSAFE_GENERATION` | Terminal; revise prompt/content |
| `PUBLIC_ERROR_USER_QUOTA_REACHED` | Terminal until quota/account state changes |
| `PUBLIC_ERROR_MODEL_ACCESS_DENIED` | Use an allowed model/tier |
| `Requested entity was not found` | Use the existing media re-upload recovery path |
| `PUBLIC_ERROR_UNUSUAL_ACTIVITY` | Pause submissions; preserve profile/session; never clear cookies/storage or use paid calls as probes |
| `UNSUPPORTED_ON_BATCH_API` | Terminal for that capability; use documented supported alternative |

## HTTP interpretation

Do not diagnose by HTTP status alone. Prefer fixed `error`, `effect`,
reconciliation state and Flow-native reason.

- 409 with `effect=unknown`: **do not retry the effect**.
- 403 `PAID_DISPATCH_DISABLED`: paid gate is locked, not a browser outage.
- 503 `Browser session not ready`: inspect browser backend status.
- 5xx on a read/poll: retry the read using the same durable operation.
- 5xx after an effect may be ambiguous; if `effect=unknown`, reconcile first.

## Dashboard and event channel

`/ws/dashboard` is an independent event stream for the React dashboard. Its
connection state does **not** prove Flow browser readiness and losing it does not
authorize transport failover.

## YouTube errors

YouTube OAuth/token failures are separate from Flow browser authentication.
Examples:
- `invalidTags`: trim tags to API limits.
- `quotaExceeded`: wait for quota reset.
- `invalid_grant`: re-run the documented YouTube channel auth flow.

## Report format

When reporting a diagnosis, include:

```
Layer:       Browser session | Flow | FastAPI | Worker | YouTube | Env
Code:        <fixed error/reason>
Effect:      completed | unknown | not_submitted | n/a
Retryable:   yes/no (what may be retried: read vs effect)
Durable key: <request/operation id if present>
State:       <backend/session/reconciliation/paid-lock summary>
Action:      <safe next action>
Avoid:       <profile mutation / paid resend if applicable>
```
