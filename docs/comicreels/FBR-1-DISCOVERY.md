# FBR-1 — read-only Flow discovery

Status: LOCAL_PASS / LIVE_PASS; owner acceptance and merge pending.
Base integration `1675ea5eb92793383b9636eae6e3d8efbdaa7091`;
branch `fbr/1-flow-readonly-discovery`; KBS pin `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.

The owner subsequently requested continuation until every checkpoint is complete. FBR-1 is
authorized to proceed; the ultimate deliverable remains the accepted browser-first migration
and a real final video. Individual checkpoint evidence is not that final deliverable. Exact
paid preset/cost remains a separate input before any credit-consuming call. The clip is the
existing ComicReels project `1d2463a90e624eb59cc05979c38d31db`, not a replacement demo.

## Live surface and capability map

Observed on 2026-09-27 using the accepted persistent `flow-browser` provider, no project changes:

| Capability | Evidence | Execution classification |
|---|---|---|
| Project list | Home page contains visible `Mở dự án` links with `/project/<UUID>` hrefs | Read-only semantic UI, live verified |
| Open/resume project | Opened existing `487247a1-00f4-4de3-83c1-4c16ce834b93` from its observed link | Read-only navigation, live verified |
| Active project | Exact `/project/<UUID>` URL, project navigation and editable title control visible | Read-only UI/URL; no title edits |
| Project media / refreshed URLs | UI navigation emitted POST `Zzl0ze`; bounded response captured and replayed | Browser-page replay verified; KBS request-context replay remains unavailable under the strict unknown-size policy |
| Media lookup | Three image tiles visible in the opened project; source parser reads media UUIDs and signed URLs | Project-media read currently observed; individual `as29s` RPC not yet live validated |
| Create project | Home `New project` button; source builder `create_project_request` uses `jHPbke`, inner `[projects/*,[null,[title]],[null,22]]` | Mutation: semantic UI or future guarded browser RPC; FBR-2 live validation required |
| Upload image | Project add-media menu and source `upload_request`; `maseQ` RPC with context/base64/MIME/name/client IDs | Mutation: source-backed candidate only, no upload executed in FBR-1; FBR-2 verifies disposable project |
| Generate | Create button in project; existing generation RPC constants in `flow_batch.py` | Forbidden in FBR-1; never passed to read replay |

Endpoint: `https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute`.
The live `Zzl0ze` form has one `f.req` envelope and an auth field; only the envelope is decoded.
Its observed inner shape is `[projects/<UUID>, null, null, null, [1]]`, matching the existing
`project_media_request` builder. Authentication fields and values are never recorded here.

Home navigation also observed RPC identifiers `o30O0e`, `NfrxTb`, `cPZSdc`, `Yizz8d`, `KV2T2d`,
`UpteDb`, `nzlxg`, `xI9TVb`. Their meaning is **unclassified**; occurrence during page load does
not authorize replay. Only the positively classified project-media read enters the allowlist.

Key observed project controls: home navigation, project title textbox, search, filter/sort,
add-media menu, grid settings, account information, media-type navigation, image tiles, prompt
input, add-component button and generation settings. No generating/deleting/renaming controls
were activated. Account identity stays in provider memory and is omitted from this document.

## Implementation and constraints

`flow_browser_discovery.py` wraps KBS NetworkObserver, BodyCaptureService and ApiReplayService.
It retains only live handles and structural evidence; it does not install a generation backend.

- Request guard validates HTTPS origin/port, POST endpoint, one RPC query, one decoded form key
  per name, known field names, one matching envelope, exact observed read shape and UUID.
- Response capture is opt-in, maximum three captures of at most 512 KiB each. Unknown size and
  streaming bodies stay unavailable. No artifact sink, request-body capture, raw previews or
  response scalar/object-key persistence. Body projection bounds depth/width/node count.
- A replay ticket requires a fresh authenticated provider, same live session and navigation
  epoch, request age <=60 seconds, unchanged classified envelope and a captured shape baseline.
- Each observed exchange is bound once per discovery window. Ticket consumption precedes the
  call; ambiguous outcome cannot be retried via a second ticket. At most three bound exchanges.
- The narrowly constructed KBS replay policy permits the validated read POST with zero retries
  and zero redirects. It reuses the live browser Request handle; it exports no auth bindings.
- Response structure drift invalidates the window. Public diagnostics use fixed codes only.
- Observer and additional navigation/request listeners are detached before provider close;
  partial registration and independent removal failures have explicit cleanup tests.

Ruling: generic KBS discovery expects ordinary JSON, while Flow uses XSSI/batchexecute envelopes —
reuse Flow's existing parser after bounded KBS body capture — wrong inference blocks replay
rather than expanding the allowlist. KBS remains unchanged and generic.

The request-context limitation has a live-verified explicit alternative, `replay_in_page`.
It consumes the same one-use ticket, rebuilds only the validated `Zzl0ze` envelope
and runs Flow's observed request convention in the current page. WIZ authentication values stay
in that page. Camoufox main-world evaluation is enabled explicitly by the profile provider.
The stream reader enforces a cumulative 512-KiB limit and a 15-second abort, rejects redirects,
awaits EOF, validates UTF-8 and transfers the complete response for transient structural parsing.
It rechecks navigation, request freshness, session and authentication after the fetch. Requests
observed while the explicit channel runs cannot authorize another replay. There is no automatic
fallback or rebind of an attempted exchange; each channel needs a separately observed native read.

## Verification ledger

- Initial 20 tests failed before implementation; initial implementation passed them.
- Added original-request age/navigation tests; both failed, then passed after tracking request
  observation times and clearing bindings on navigation.
- Independent review found encoded duplicate keys, rebinding an attempted exchange, missing
  pre-effect shape baseline and incomplete listener rollback. Reproducing tests failed before
  repairs. Boolean-vs-integer ambiguity also has a failed-then-passing regression.
- 36 targeted tests pass, including successful matching replay, changed response shape and
  an integration-style fake using real KBS observation/body/replay policy. It verifies the
  original Request handle is passed, retry/redirect limits are zero and response disposal occurs.
- Targeted Ruff passes. Full regression: 564 unit PASS, SDK 30 PASS / 7 SKIP, npm ci/build/lint PASS.
- Exact tested source digest: `ff1c4cf05f8336eb8792ecf099480eee40046bae91493bb7bb597e7507a4cfde`.
  Local evidence: `local-test-data/source-batch-1675ea5-b31b4cb0b1c6403491769a0784ddfb76/`.
- Live adapter result: `READ_CAPTURE_PASS_REPLAY_UNVERIFIED`. Native capture succeeded;
  replay returned HTTP 200 with `body_size_unknown`. This is not successful replay or a full
  live pass. The response-size guard was not relaxed. Both profile opens authenticated as the
  same account; observer closed, both leases released and the owned marker removed.
- The legacy signed-image-URL parser reports `image_count=0` for this response; this is not an
  asset inventory. Three image tiles were observed in the UI. No generation or mutation occurred.
- The real ComicReels project still has one FAILED shot and two READY shots; all three video
  paths are null. Its three approved portrait files match their recorded hashes. The earlier
  failed submission recorded `PUBLIC_ERROR_UNUSUAL_ACTIVITY`; no paid retry was attempted.
- New in-page channel and provider tests: 76 targeted PASS, including seven tests executing
  the actual shipped JavaScript against chunked, oversized, interrupted and aborted streams.
  A second review limited to this new channel found missing post-flight invalidation and replay
  self-observation. Both findings reproduced as failures and pass after one repair cycle.
  Fresh full regression and browser live verification of these added bytes passed as recorded below.

## Final pre-merge gate

- Source digest: `f790f2740a196bda56cd9e24352d9aeb0b08eae090f2ea1d4cfb61261c64c35a`.
- Exact source deployment: `source-batch-1675ea5-855df4fb65394e989c51ed83fa16568b`.
  Detailed local evidence is in the same named directory under ignored `local-test-data/`.
- Regression: **583 unit PASS, SDK 30 PASS / 7 SKIP, npm ci/build/lint PASS**, targeted Ruff PASS.
- Live receipt `flow-discovery-page-live.json`: **PASS**, 2026-09-27 07:15:28Z.
  Native project read captured 10,365 bytes; browser-page replay reached EOF with 10,363 bytes
  and matched the structural baseline. Both bodies are transient; published evidence is sanitized.
- Both opens authenticated in the same profile/account; post-read health remained ready.
  Observer closed, both leases released, owned marker removed. Zero paid effects or mutations.
- The actual provider, auth adapter, discovery module and JavaScript file matched the tested
  manifest before live use. Only evidence documentation changed after this gate.
- KBS remains unchanged at `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
- Known limitations: request-context replay is not validated; arbitrary RPCs remain forbidden;
  create/upload and media UUID/URL operation parity await FBR-2. The clip is not rendered.
- Rollback: `1675ea5eb92793383b9636eae6e3d8efbdaa7091`; active extension backend unchanged.
- Owner decision: continuation authorized implementation; explicit checkpoint merge acceptance
  remains pending under the supplied handoff. No FBR-2 implementation or paid work has started.

## Next gates

Commit/push the coherent FBR-1 checkpoint, obtain owner merge acceptance, then verify the exact
merged revision before closing FBR-1. FBR-2 supplies non-paid backend parity after authorization.
No paid generation or destructive action is allowed during discovery.
