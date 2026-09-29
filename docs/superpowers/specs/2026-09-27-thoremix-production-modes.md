# Thỏ Remix production modes

Owner requests two app modes: produce at a posting slot, or build a daily stock of videos.
Owner clarified that the early quota counts successful completed clips, not attempts. Range
1–1000, default5. Failures skip the source and continue; original files and error evidence
remain available. Completed packages wait for existing posting slots (11:00,18:30).

Settings: production_mode=scheduled|ahead (default scheduled for compatible migration),
daily_production_limit=5. Existing enabled switch controls automatic production/publication;
saving settings does not silently enable the currently paused campaign. Quota uses Vietnam
calendar dates and persists in SQLite. A completed, hash/media-verified package counts once.
Known per-image failures do not count. Ambiguous/interrupted paid production remains held
for reconciliation and never gets a new source identity or blind generation retry.

One finite daily batch fills the remaining quota, stopping at source exhaustion, pause/mode
change, a date change, or a global provider/readiness/credit block. Release the campaign lock
between clips; duplicate workers share a separate batch lease. Configuration/pause uses an
independent settings lock so the owner can stop before the next clip. No AI scheduler loop.
Windows Scheduled Tasks wake the early-production dispatcher every5minutes. It prioritizes
posting slots due within30minutes so long generation cannot silently drop a due post. No
older-day or all-day catch-up. GUI closed/tray state has no scheduling authority.
Posting triggers persist an independent due-slot request before acquiring the busy runner.
A slot crossed by an owned production batch is handled after its current clip finishes,
even beyond the normal 30-minute discovery window. A generation-only slot from yesterday
expires after reconciliation so its completed story can enter today's ready queue.

Publication slots durably bind exactly one ready FIFO package before submit. Repeated slots
return/reconcile that same job. Never publish the entire ready backlog at a single slot.
In scheduled mode, an empty slot may produce one clip then publish its validated package.
Ahead mode never starts paid production from an empty posting queue.

GUI: mode radio buttons, validated1–1000 limit, save, run early batch, successful/target,
ready/error/uncertain counts, daily safe report with per-source failure codes and log path.
No raw signed URLs/credentials in general logs. No source overwrite or deletion on error.

Known boundary: FlowKitProducer currently advertises automatic_story_ready=false. This
change must retain that truth: install working controller/queue/settings, report the provider
block before reserving any source, and do not claim actual automatic video production passed.
Completing the single-story Flow producer remains its existing separately unfinished task.
