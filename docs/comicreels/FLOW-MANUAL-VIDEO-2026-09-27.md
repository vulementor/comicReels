# Native Flow video evidence — 2026-09-27

## Owner requirement and current verdict

The owner authorized native Camoufox operation in the existing Flow project, followed by
code changes based on observed UI and API behavior. The current requirement is **one
10-second video containing all three uploaded frames in order**, preserving their exact
artwork and compositions, with Vietnamese dialogue as audio only. Remove all speech
balloons, including any present in the source, and download the highest available resolution.
This replaces the earlier interpretation of one 10-second generation per panel.

**Artifacts exist; final animated reference fidelity is NOT accepted.** The cleaned Flow
animation has no visible speech balloons in the 40 inspected samples, but the last character
pose is still wrong and compositions differ. A separate exact-frame version uses static
approved images with the same Flow audio. It is not presented as native animation.

FBR-1 remains accepted. FBR-2 remains in progress: the optional browser backend still lacks
its concrete driver and a live nonpaid integration gate. No FBR-2 merge or application
cutover occurred. Manual generation used the accepted FBR-1 session provider and native UI.

## Identity, scope and completed attempts

- Flow project: `487247a1-00f4-4de3-83c1-4c16ce834b93`.
- ComicReels project: `1d2463a90e624eb59cc05979c38d31db`.
- Ordered uploaded images: `1a8271d1-283a-483b-84bc-f036897dd45e`,
  `8a282727-0063-4130-a589-5833e85b2e74`, `aabe6bae-d4c0-429b-bb64-c6c6c6633708`.
- Native preset: Omni 1.1 Flash, Ingredients, 9:16, 10 seconds, 360p, x1.
  The submit UI displayed 7 credits. This is an observed quote, not a billing assertion.
- One initial trial incorrectly covered scene 1 only. The owner corrected the scope.
- Full-story attempt 1: media `25924b82-1c27-49f8-bfc3-9cbfc29178b2`, workflow
  `02727698-3eb4-4c01-8098-85d7b6dd9b93`; rejected for balloons and composition drift.
- Full-story attempt 2: media `c0262f5c-3091-47c5-905e-14c97b08e4cf`, workflow
  `7fd70aab-f6b7-4da6-982b-267063b0e026`; completed, downloaded and postprocessed.
- Each submission was reconciled to its own completed media. No unknown paid outcome was
  resubmitted. No browser generation is pending; the persistent session closed cleanly.

## UI and API observations now represented in source

`flow_browser_semantics.py` captures reusable, non-submitting UI checks:

- The recent image grid was ordered 3, 2, 1. Select exact filenames, inspect the preview,
  and compare actual component UUIDs against the expected prefix after each attachment.
- Pressing Enter on a picker option once selected a stale preview. The observed click
  handler plus verified preview avoids assuming that keyboard selection chose the image.
- Verify the exact project, ordered image UUIDs and whitespace-normalized composer text.
  Do not retain signed image URL query strings in receipts.
- The observed download menu contained GIF 270p, original 360p and upscaled 720p. Select
  720p. Unknown resolution labels require new observation rather than silently choosing
  a lower option. Native upscale began before the download event; await all bytes.

Production receipt fixes in `flow_batch.py` and `omni_flash.py`:

- Native `MZZa6b` slot 2 contains workflow metadata; slot 3 contains the media record.
  Preserve both IDs in the existing `batch_media` descriptor and poll `as29s` by media ID.
  Do not change only the operation ID: legacy listing lookup expects a workflow ID.
- Keep legacy operation-only receipts compatible. Malformed native media receipts fail
  parsing without substituting workflow metadata or sending another generation request.
- `CAE` occurs with queued outcome 6 and running outcome 2. Completion is outcome 3;
  upscale also completed with `CAI` + 3. Outcome 4 remains a nonterminal diagnostic.
- A poster-only media record remains pending. A video URL is required for completion.
  The regression test persists the descriptor through JSON and polls with a fresh client.
- Prompt builders now explicitly remove source speech balloons while retaining spoken
  dialogue. A prompt instruction alone is not proof that the generated video obeyed it.

The semantic helpers are additive and are not yet wired into the unfinished FBR-2 driver.
The existing per-panel storyboard is not silently repurposed as a full-story job; that
product integration remains separate. No old shot was marked completed using these files.

## Local artifacts and QA

Evidence directory: `local-test-data/manual-flow-20260927/` (ignored; contains local media).

| File | Role | SHA-256 |
|---|---|---|
| `comicreels-10s-720p-no-bubbles.mp4` | Flow animation, cleaned; fidelity rejected | `edcf3d28e9b2f24a10ece2944982ab0097dd2539da7a26da027fda7ae37f1a6d` |
| `comicreels-10s-720p-original-frames.mp4` | Static images 1 → 2 → 3 with Flow audio | `a533c1ff06c7c9440cd2ed1379db1052e59cba43fc0f3422a1a9104a8349ee9b` |

Both files are 10.000 seconds, 720×1280, 24 fps, 240 frames, H.264 + AAC. Full decode passes.
The decoded audio hash equals the downloaded source in both outputs:
`40141d5f6d47a3c49817d63a337795db463e6999041e3185a18cde0210a62ea0`.

For the animation, the first 3.2 seconds' balloon region was replaced with the same
shot's clean background from 3.2 seconds: full-width top 442 pixels, above the horn.
This is local video cleanup, not a claim that native generation removed the balloon.
The static variant uses original frames during 0–4, 4–7.25 and 7.25–10 seconds.

ASR (`faster-whisper` small, Vietnamese) found exactly three utterances in story order
and no repeated utterance, so no audio was muted. It transcribed a tone and pronoun
differently from the script; exact pronunciation has not been independently certified.
`final-media-qa.json` records these limitations explicitly, alongside full decode results.

Native sanitized receipts: `network2-nreq-000018.json` / `000055` (submission), `000025`
(running), `000032` (complete), `000041` (upscale complete), `000057` (queued).
The committed fixture retains only the minimal response shape with synthetic identifiers;
no credentials, balance, prompt, or browser profile contents are committed.

## Source verification

On the canonical working tree: **699 unit tests pass** (`unit-final.xml` / `unit-final.log`),
including 178 focused receipt, polling, prompt and semantic cases. Tests ran with
`PYTHONUTF8=1` and `PYTHONPATH` pointing to the canonical KBS `src` at pinned revision
`b539e9820d433c8c9d667b4e5d9007b6a80b8abd`. New semantic files pass full Ruff; edited legacy
files pass critical-error Ruff; `git diff --check` passes. Existing broad lint findings in
legacy files were not represented as a clean whole-repository lint result.

Independent read-only review found a delayed-picker-confirmation race and incomplete native
receipt validation. Both were repaired with failing-then-passing regressions. A second review
found no further actionable defects in the bounded changes. No review invoked live generation.

Both remotes were fetched. ComicReels HEAD equals remote integration `4ddd23f`; its history
also contains remote default tip `e6407be` (225 commits ahead, zero behind). Uncommitted FBR-2
and live-observation changes remain in the canonical checkout. KBS `main` is clean and equal
to remote. This records source freshness, not FBR-2 completion or a deployment.
