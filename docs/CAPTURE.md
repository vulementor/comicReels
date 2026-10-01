# Capturing Flow browser payloads

Flow Kit only implements RPC shapes that were observed from a real
`flow.google.com` UI action. Discovery happens through the browser/KBS path,
not through the retired Chrome extension.

## Safety boundary

- Capture only during an explicitly approved validation/discovery session.
- Reuse the existing persistent signed-in profile under its normal lease.
- Never clear cookies/storage, sign out, clone/replace the profile or export
  credentials.
- Never use paid generation merely to diagnose transport.
- If a paid effect outcome becomes unknown, stop and reconcile it before any
  resend.
- Never commit raw cookies, auth headers, CSRF values, profile databases or
  unredacted browser dumps.

## Preferred discovery flow

1. Start from the exact source revision and pinned KBS revision.
2. Open/resume the existing Flow profile through `BrowserFlowBackend`.
3. Observe the relevant UI/network action using KBS/browser observation tools.
4. Capture only the minimum sanitized request/response structure needed to
   identify `rpcid`, `f.req` positional shape and response parsing.
5. Store discovery material only in approved scratch space. Redact identity,
   cookies, headers, signed URLs and other live credentials.
6. Diff the inner payload against the nearest builder in
   `agent/services/flow_batch.py`.
7. Encode the learned shape as a validated browser contract/recipe plus authored
   coverage.
8. Delete scratch captures after extracting the non-secret structural fixture.

## Existing browser RPC building blocks

| Capability | rpcid / source |
|---|---|
| image generation | `ogiZ0b` |
| video generation | current builders in `flow_batch.py` |
| operation polling | `jwpduf` |
| project media listing | `Zzl0ze` |
| media URL read | `as29s` |
| upload | `maseQ` |

Do not infer support from an old extension capture. The current
`flow.google.com` UI plus the pinned browser recipe is the authority.

## Validation rules

**Accepted is not the same as used.** A positional payload can return HTTP 200
while silently ignoring a field. Verify the resulting media/operation semantics,
not only the status code.

**Read vs effect matters.** Read-only discovery can be retried when safe. A
generation/effect cannot be blindly replayed after timeout or ambiguous browser
failure.

**Signed URLs are ephemeral.** Persist stable media/operation UUIDs, then refresh
URLs through the current read path when needed.
