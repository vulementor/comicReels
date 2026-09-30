# Private runtime entries

This entry belongs to the independent comic / thoremix application.
It is loaded by the verified private host; do not execute entry.py as a raw script.

## Administrative preview

Catalogue help and status to deployment/stable_runtime/entry.py in the immutable
host manifest, and declare exact operation mappings:
`"entries": {"help": "help", "status": "status"}`.
Keep the deployment disabled. These two entries need only the platform package
and Python standard library. They do not import the app, create app state, open
business ledgers, resolve native tools, borrow profiles or run model/browser work.

From the installed platform interpreter, use:

```powershell
& <platform-python> -m stable_toolkit_runtime.cli --root D:\StableApp\build deployment-run manifests/instances/app/comic/preview-a.json help --launch-id comic-help-001
& <platform-python> -m stable_toolkit_runtime.cli --root D:\StableApp\build deployment-run manifests/instances/app/comic/preview-a.json status --launch-id comic-status-001
```

Each invocation uses a fresh launch ID. The result is emitted as JSON and saved
to the host launch's app-result.json. Status describes the retained deployment
and configuration presence only: execution_readiness stays NOT_CHECKED and
domain_state stays NOT_READ. A successful administrative result does not prove
the business workflow, desktop, browser, model or media pipeline works.

A minimal disabled preview uses empty settings and profiles and the host's
registered release_id, consumer_id, candidate channel and app instance data path.
The platform must support safe help/status dispatch for disabled declarations;
older hosts reject them with DEPLOYMENT_DISABLED. Never enable a deployment just
to bypass that check, and never alias status/help to a business entry.

## Business entries and desktop boundary

Business entries require an enabled, fully configured instance and prepared
native/model/app dependencies. Required settings: `chat_profile_name`, `api_port`, `websocket_port`.
Per-instance files are required at home/config/models.json and home/config/providers.json.
They are not loaded by help/status and are never silently copied from another instance.

Comic uses server. ThoRemix uses tick, dispatch and campaign-status.
The renamed campaign-status retains the earlier
domain status operation and its durable context.job scope. Administrative status
does not run it. Existing business journals, authorization, enabled/paused gates,
leases and uncertainty handling remain authoritative.

Private desktop launch returns UNSUPPORTED / BOUND_CHILD_LAUNCH_UNAVAILABLE before
app imports. The legacy standalone desktop is unchanged; it is not a supported
launcher for a private instance. In particular, raw child Python commands do
not inherit the process binding or resource leases. A verified platform child
launch contract is required before enabling private desktop commands.

## Light smoke

```powershell
python -B deployment/stable_runtime/test_entry.py -v
```

Tests guard against business imports and use temporary directories only.
They do not constitute workflow or production acceptance.
