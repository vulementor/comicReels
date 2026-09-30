# Private runtime entries

This repository packages the reusable ComicReels kit and the independent ThoRemix
application in one distribution, `comicreels`. ComicReels supports comic videos
and general Google Flow video creation; it is not a ThoRemix-specific workflow.
The existing project, scene-chain, reference, generation, review, TTS, concatenation,
branding and API capabilities remain owned by the kit.

The only accepted deployment identities are:

| Consumer | Kind | Name | Report schema |
| --- | --- | --- | --- |
| ComicReels kit | service | comicreels | stable.service.entry.v1 |
| ThoRemix app | app | thoremix | stable.app.entry.v1 |

Old `app/comic` and mismatched kind/name pairs fail closed. There is no implicit
compatibility alias. The public package name introduced by this candidate is
`comicreels`; the earlier candidate name `comicreels-app` is superseded.
Only one source checkout and one wheel are needed for both consumers.

## Administrative preview

The verified private host loads this entry; do not execute entry.py as a raw
script. Catalogue help and status to deployment/stable_runtime/entry.py in the
immutable host manifest, with exact declaration operation mappings:
`"entries": {"help": "help", "status": "status"}`.

Keep declarations disabled. These entries need only the platform package and
Python standard library. They do not import business code, create consumer
state, open business ledgers, resolve native tools, borrow profiles or perform
provider/browser/model work.

From the installed platform interpreter:

```powershell
& <platform-python> -m stable_toolkit_runtime.cli --root D:\StableApp\build deployment-run manifests/instances/service/comicreels/preview-a.json status --launch-id comicreels-status-001
& <platform-python> -m stable_toolkit_runtime.cli --root D:\StableApp\build deployment-run manifests/instances/app/thoremix/preview-a.json help --launch-id thoremix-help-001
```

Each invocation uses a fresh launch ID. JSON is emitted and saved to the host
launch's app-result.json, whose filename is shared by the host entry convention.
ComicReels identifies itself with `kind=service`, `name=comicreels` and
`service=comicreels`; ThoRemix uses `kind=app`, `name=thoremix` and `app=thoremix`.

A minimal disabled preview uses empty settings and profiles, the registered
release_id and consumer_id, candidate channel and the platform's canonical
consumer state path. Version roots are services/comicreels/versions/<version>
and apps/thoremix/versions/<version>.

Status describes retained deployment and configuration presence only:
execution_readiness stays NOT_CHECKED and domain_state stays NOT_READ.
Successful administrative status does not prove workflow readiness. The
platform must support safe help/status for disabled declarations; never enable
a consumer merely to bypass an older host's DEPLOYMENT_DISABLED check.

## Execution and desktop boundaries

ComicReels exposes its general Flow server through `server`. This change does not
replace or narrow the kit's creative capabilities, nor run the FBR transport
refactor. ThoRemix uses `tick`, `dispatch` and `campaign-status`; those entries
are rejected for ComicReels. ThoRemix cannot use the toolkit's server entry.

Execution requires an enabled, configured consumer and prepared native/model
dependencies. Required settings: chat_profile_name, api_port and websocket_port.
Per-instance home/config/models.json and home/config/providers.json must be
seeded explicitly; help/status neither loads them nor copies another consumer's
configuration. PrivateRuntime uses explicit consumer_kind and consumer_name.

ThoRemix campaign-status retains its durable context.job scope. Existing
authorization, enabled/paused gates, journals, leases and uncertainty handling
remain authoritative. Administrative status does not run campaign-status.

Private desktop returns UNSUPPORTED / BOUND_CHILD_LAUNCH_UNAVAILABLE before
business imports. The legacy standalone ThoRemix desktop remains available;
its raw Python children cannot inherit private bindings and leases. A verified
bound-child launch contract is required before enabling private desktop commands.

## Light smoke

```powershell
python -B deployment/stable_runtime/test_entry.py -v
```

These temporary-directory checks guard against business imports. They do not
constitute workflow, provider, browser, model or production acceptance.
