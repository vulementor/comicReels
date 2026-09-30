# Managed ThoRemix desktop

The application keeps its existing six-view Tk desktop and canonical CLI. ComicReels
service behavior is unchanged. No browser, AI generation or publication runs when
opening the desktop; buttons still invoke their existing application behavior.

New immutable host manifests can catalogue desktop, desktop-command and desktop-smoke
to deployment/stable_runtime/entry.py alongside help/status/campaign-status.
A declared host must be enabled to open desktop; this does not turn on the separate
ThoRemix Settings.enabled or Settings.publication_authorized gates.

The private entry appends only a catalogued native/thirdparty dependency payload.
On Windows it retains os.add_dll_directory handles for catalogued
native/media/ffpyplayer/{ffmpeg,sdl}/bin. It never adds legacy source or PYTHONPATH.
Tk/Tcl and the real dependency closure must be packaged in the new release.

Use a valid instance identity, explicit home/config/settings.json with a matching root,
and the private binding settings/profile declarations. The child receives the same
retained release, home, profiles and settings. Its bounded desktop_command request adds
command/arguments and parent/child identity. Commands cannot supply --root or recursively
open desktop. Each child binds before importing the CLI and runs under context.job.

ManagedCommandRunner uses public prepare_deployment/start_host/inspect_instance APIs.
It writes a dispatch receipt before start, never automatically retries an ambiguous
start, and waits for child process termination before returning the bounded CLI output.
Children are independent hosts and are not killed when the GUI closes. Existing app
journals still own effect idempotency and reconciliation.

The singleton is namespaced by app identity and home. Optional display_title is a short
user-facing window title; otherwise the instance ID appears in the title. Readiness
is reported after Tk creation and first refresh. Cooperative drain closes the GUI.

desktop-smoke is an explicit finite test entry. It navigates all six existing views,
captures only this window, refreshes and invokes status through the ordinary GUI worker
and managed child runner. Its receipt records views, screenshots, dimensions and child
lineage, then it closes the GUI. No browser/provider/generation command is run.

Optional smoke_source is used only by desktop-smoke. It must be a direct file in
Settings.input_dir == home/input. The SDK reserves it under the fixed desktop-smoke slot
and a durable host job; this creates local campaign state and a real thumbnail row.
Normal desktop never performs that reservation. Smoke settings should keep both enabled
and publication_authorized false. Existing production state and profiles must remain
separate from the fresh test instance.

Focused tests: tests/unit/test_managed_desktop.py. Installed GUI/child-host smoke is a
separate check; passing unit tests alone does not prove a rendered working window.
