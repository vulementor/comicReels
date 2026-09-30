# Independent ComicReels and ThoRemix instances

ComicReels and ThoRemix are independent applications/capabilities. They are not
standard reusable platform toolkits. The shared `agent.private_runtime` module
belongs to this application repository, not KBS/GPTFP/KRP/KAT or platform core.
Different channels select an immutable app release but keep their own settings,
database, receipts, profiles, output and schedules. A new instance does not copy
authentication, unresolved effects, approvals or enabled publication authority.

## Explicit process binding

Install `PrivateRuntime` before importing `agent.config` or starting workers.
It binds once to an app kind (`comic` or `thoremix`), instance ID, mutable home,
explicit profile roles, port numbers and trusted resource providers. The provider
callbacks must verify pinned immutable assets; they must not download or search
ambient caches. The binding is available to worker threads. Rebinding a running
process or importing app configuration against another home/port is refused.

Profile roles are `chatgpt`, `flow`, `social` and `affiliate`; each used role
must have an explicit absolute physical path. `profile_lease_factory(path)`
returns a real common owner context whose `borrow()` context yields a live
borrow with `require_active()`, `profile_dir` and `lease_id`. Sharing Affiliate
with Drama requires the same physical ownership contract on both app sides.
An ownership string by itself cannot substitute for the borrowed object.

Tools selected by name are `camoufox`, `ffmpeg`, `ffprobe`, and the optional
`tts-python` interpreter for the existing OmniVoice feature. Camoufox requires
its pinned adjacent `version.json`. Models resolve to verified local directories:
`whisper-small` for existing ThoRemix audio diagnostics and `omnivoice` only
when that existing TTS feature is requested. Private mode does not fetch models.

## Existing operations and ownership

Chat/image wrappers call only existing public GPTFP methods. Each operation
acquires the real profile borrow on the executing worker thread, supplies an
external profile handle plus explicit browser/media paths and isolated journal
home, and keeps ownership until that synchronous operation has returned. Exact
conversation IDs, callbacks, arguments, returned domain states and exceptions
pass through without an automatic retry or alternate request. Required public
methods must actually exist; the adapter does not advertise a missing method.
No browser handle, audio stream or lazy iterator is exposed by this app facade.

The Flow session provider acquires the common borrow before its existing
Flow/GPTFP-compatible OS lease. It retains both until browser close is confirmed.
An uncertain close keeps ownership and blocks reopening. Flow selectors,
authenticated recipes, paid-effect intent/receipts and backend selection stay
inside the existing app. No FBR checkpoint advancement, extension removal or
default backend cutover is part of this integration.

ThoRemix social publication uses the existing KRP journal with an explicit
logical-to-physical social profile and private-browser lease factory. Affiliate
uses KAT's same ownership contract; a custom session provider must be explicitly
bound to the instance. Actor, idempotency, reconciliation and approval gates remain
unchanged. `private_host.run_thoremix` wraps one existing `tick`, `dispatch`
or local `status` in the host job scope; it never enables a schedule or campaign.

ThoRemix `Settings.root` must equal the bound instance home. Original input
libraries may stay outside that home. Managed output goes to `home/output`;
existing package/receipt paths must be reconciled at migration before resuming.
Installing a binding does not rewrite or copy old data. Comic's database/output
and API/WebSocket ports come from its own binding. Separate instances require
separate port allocations and extension configuration where extension is selected.

Native media uses bound executables. The existing OmniVoice subprocess receives
an explicit private interpreter, local model directory and offline model flags.
This is the existing Flow TTS feature, not a fallback for ChatGPT Web audio.
ChatGPT audio remains governed by its authenticated direct-stream contract.

## Compatibility and source-only status

Without a binding, existing standalone behavior remains. Private mode requires
the new KAT/KRP resource contracts in the coordinated integration set.

Source inspection found that deployed ThoRemix GPTFP includes batch-image and
progress/upload/raw-message capabilities absent from the frozen GPTFP candidate.
Those production capabilities must be reconciled into the candidate before
integration can pass. Never remove callbacks or replay requests to hide the gap.
The deployed ThoRemix app is also marked `source_state=working-tree`; compare
and preserve its source changes before cutover.

Regression cases are authored but not executed under the user's code-first
instruction. No live browser/model, package install, authentication/profile move,
publication or paid generation has been performed by this change. Installed
acceptance and one-time coordinated migration remain pending.

## Catalogued application entry and wheel

The Hatch project builds the agent package as comicreels-app. setup.py remains
its existing AI-tool configuration utility and is not used as a wheel builder.
Dependencies at runtime still come from an explicit complete offline wheel set.

Copy deployment/stable_runtime/entry.py into the immutable entries declared by
the build plan. Comic accepts server; ThoRemix accepts tick, dispatch, status.
Each app has its own declaration under apps/<name>/instances/<id>/instance.json.
Settings require chat_profile_name, api_port, websocket_port and optionally
flow_profile_config (relative to instance home) and visible. Model identifiers
whisper-small and omnivoice are explicitly pinned by runtime-models.json.

Editable models.json and providers.json belong in <instance-home>/config. The
operator seeds them from the preserved existing configuration during final
cutover, or explicitly from packaged defaults for a fresh instance. Missing
files fail instead of recreating state. Model/provider APIs and Omni Flash read
the same files, so UI settings cannot mutate the immutable app release.

The Comic server entry binds before importing agent.config, runs one existing
ASGI app, reports backend connectivity separately, and requests Uvicorn shutdown
when drained. The existing app lifespan drains its workers and closes its
backend. ThoRemix finite results are recorded per unique launch, preserving
existing enabled/publication/receipt semantics. Desktop child-command integration
is a separate required item; these finite entries do not claim to implement it.
