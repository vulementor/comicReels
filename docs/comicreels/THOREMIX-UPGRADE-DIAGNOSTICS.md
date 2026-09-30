# ThoRemix upgrade move diagnostics

## A3.9-2f scope

Add failure-time observations to `deployment/thoremix/Build-Stable.ps1`.
This is instrumentation, not a fix for the observed `source` rename denial.
Do not infer that a build succeeded or a blocking process was identified.

Each failed `Move-UpgradePart` attempt emits one stderr line prefixed with
`THOREMIX_MOVE_FAILURE ` followed by JSON. The existing build supervisor must
continue capturing stderr in its durable build log.

Recorded fields:
- UTC timestamp, build-process PID, PowerShell version and both working directories.
- Exact source/destination paths, observed attributes and metadata lookup state.
  An unreadable lookup stays `unreadable`, rather than being called `missing`.
- Move label (including promotion/rollback direction), attempt and maximum attempts.
- PowerShell error ID/category and at most six exception-chain entries.
- Each entry's type, HRESULT and bounded message (600 characters maximum).
- `native_win32_code` only when a captured exception is a Win32Exception.
- `hresult_win32_code` only for an HRESULT_FROM_WIN32 encoding; otherwise null.

A generic managed HRESULT is not mislabeled as a native Windows error.
No later GetLastWin32Error value is used as evidence for an earlier cmdlet call.
The PID identifies the build process, NOT a process holding a directory handle.

Retry count/backoff, runtime-only mirror fallback, promotion order and rollback
code are unchanged. A diagnostic failure emits
`THOREMIX_MOVE_DIAGNOSTIC_UNAVAILABLE`; it must not mask the original move error.
No process enumeration/termination, ACL changes, environment dumps, command-line
collection, file-content collection or additional rename probe is performed.

## Isolated verification

Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
 deployment/thoremix/Test-UpgradeMoveDiagnostics.ps1` (on one command line).

The test parses the build script and imports only its top-level function
 definitions; it NEVER runs the build body or accesses the installed bundle.
It exercises successful moves, deterministic repeated faults and retry recovery,
logger failure, native-versus-managed error distinction, and a real Windows
sharing failure on a temporary file. All temporary mutations are under a uniquely
owned test folder; no installed Stable path is a test target.

A3.9-2f verification on VULE-PC: the test first failed on the uninstrumented
script because no diagnostic events were emitted. After instrumentation:
6 cases passed, 0 failed, process exit 0. These are focused helper tests, not a
full application regression or a production build/rollback exercise.

No rebuild, promotion, app launch, scheduler enablement or social action was
performed for this checkpoint. The next controlled retry still requires the
reviewed change to be merged and the isolated build input pin to be updated.
