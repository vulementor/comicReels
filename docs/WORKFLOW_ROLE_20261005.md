# ComicReels / FlowKit — workflow role

Documentation reconciliation: 2026-10-05. Source reviewed:
`vulementor/comicReels@5aecee7ef007b34e1ec732a3a382c80ff393546c`.
This document separates available interfaces, historical evidence and agreed targets.
No runtime, model, browser or production acceptance was performed for this docs change.

**SHARED BY CONTRACT, ISOLATED BY RUNTIME.**

## Capability and consumer ownership

FlowKit owns Flow generation semantics, projects/scenes, queue state, media identity,
review/regen and the operation evidence for work it performs. It can supply a stage
in an agent-composed workflow without requiring a new app repository. Consumer policy,
campaign timing, affiliate selection and destination authorization belong to the caller.
KBS remains generic browser infrastructure; it does not own Flow product semantics.

ThoRemix is an independent consumer application. `agent/thoremix` and older embedded
documentation remain historical source in this upstream tree; current integration must
use the standalone app's reviewed adapters/contracts rather than assume shared internals.
See the common architecture for the standalone ownership reconciliation.

## Available interface and qualification

The local FastAPI API and `agent/sdk` are present. The latter is an in-repository SDK
requiring its configured repository/services; a independently packaged CLI/SDK and
universal chat control interface are not claimed. A finite read-only API example is:

```powershell
curl.exe --fail --silent http://127.0.0.1:8100/health
```

This reads an already running, caller-selected instance; it does not start one or
authorize generation. At this reviewed upstream, selected extension transport still
uses `extension_connected`. [Browser-first migration](comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md)
and [checkpoint rules](comicreels/CHECKPOINTS.md) remain distinct from that current
surface. Evidence from a different imported/branch snapshot does not prove main cutover.

## Deterministic work, receipts and review

Submit bounded groups through the existing batch API; software owns queue limits,
polling, backoff and completion checks. `done` means requests left the queue;
`all_succeeded` is the separate success aggregate. The model is used for creative
planning or bounded visual review, not each poll. Reuse already completed media only
while input/scene/model/config bindings still match; regeneration invalidates downstream
artifacts according to existing rules.

Keep operation/request IDs and provider/media receipts with the caller's job. Unknown
paid effects require reconciliation, never automatic resend. Existing review APIs,
review skills and dashboard are current surfaces. A future CLI/chat adapter must show
the exact artifact hash/revision and write review decisions to the authoritative state
used by the same workflow. New content or action scope invalidates an old binding;
do not add a second effect journal or use chat history alone as approval evidence.
Token/call counts should be recorded when supplied; unavailable metrics remain UNKNOWN.

## Documentation acceptance and remaining work

An integrator can distinguish extension health, future browser readiness, paid permission,
queue completion and successful media. Browser-only acceptance, distributable interfaces,
generic chat approval integration and update coordination require their own implementation
and evidence. Generated `AGENTS.md` is maintained through its generator inputs, not edited
directly by this alignment. This proposal does not change any transport or runtime gate.

## Source deployment and launcher boundary

The agreed deployment target is Python source copied/synced from an exact upstream
revision into a new immutable release directory, paired with its compatible Python
environment and dependency identity. An optional Windows EXE only resolves that
binding and launches the entrypoint. Routine toolkit or workflow logic updates do
not rebuild an app EXE; only a changed launcher needs a launcher release. Existing
native/UI packaging is historical implementation until a separate migration proves
this target.

Prepare and verify the complete source/environment pair before admitting new jobs.
Do not copy over a live source tree or mutate its environment: Python may import
modules during a job. Running work keeps its actual source, environment, model and
resource bindings until a safe boundary. State, profiles and media stay outside
source releases. A source rollback does not undo state migrations or external effects.
Cross-consumer update coordination and automatic compatible promotion are TARGET
requirements here, not a claim that this repository ships an ecosystem updater.

## Shared contracts

The common documents define integration requirements, not additional commands or a
second runtime registry:

- [Current architecture](https://github.com/vulementor/kabin-kit/blob/310fc79ecb9d38de629081297566c922a962debf/docs/architecture/CURRENT_ARCHITECTURE.md)
- [Workflow operations](https://github.com/vulementor/kabin-kit/blob/310fc79ecb9d38de629081297566c922a962debf/docs/architecture/WORKFLOW_OPERATIONS.md)
- [Capability contract](https://github.com/vulementor/kabin-kit/blob/310fc79ecb9d38de629081297566c922a962debf/docs/architecture/CAPABILITY_CONTRACT.md)
- [Workflow contract](https://github.com/vulementor/kabin-kit/blob/310fc79ecb9d38de629081297566c922a962debf/docs/architecture/WORKFLOW_CONTRACT.md)
- [Release consumption](https://github.com/vulementor/kabin-kit/blob/310fc79ecb9d38de629081297566c922a962debf/docs/architecture/RELEASE_CONSUMPTION.md)
