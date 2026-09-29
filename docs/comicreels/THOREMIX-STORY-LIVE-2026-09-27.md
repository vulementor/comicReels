# One source story → one native Flow video, 2026-09-27

## Result

The authorized live ComicReels run completed one independent 10-second AI animation.
One source image contains four panels; all four become one video in reading order.
No other source story and no static-frame replacement were concatenated into it.

- Campaign job: `7edf50707f5746c0b3f8b6f2b69af913`, now `video_ready`.
- ComicReels project: `5092595b8e99437e9b0f099a923541df`.
- Source: `119732036_3788849114459038_6754165596934606518_n.jpg`.
- Source SHA-256: `bbc9d3085f09bd736b81f33e2fb0276ffa976b2520f3b9dc9d197e653a19a409`.
- Package directory: `D:\Thỏ Remix\video\119732036_3788849114459038_6754165596934606518_n`.
- Final MP4 has the source basename. SHA-256:
  `0ec2c153568d9e291c4eadcff3ff0bfab4c3dce5fc34b433187084dfb7382a9e`.
- Original source and four generated reference PNGs are archived in that directory.
- The reviewed publication manifest contains GPT FullProxy caption, hashtags and description,
  plus the previously verified affiliate product/link. Its public comment omits the owner's
  rejected automatic affiliate sentence. No new social publication occurred in this run.

## Observed execution

GPT FullProxy analyzed the whole original image and generated one batch of four separate
portrait references. Their order and key poses were reviewed: rabbit walks dog; both see
the prohibition sign; rabbit thinks; upright dog walks the rabbit on all fours.
There is no source dialogue. Analysis conversation `6ab915e6-2a80-83ec-adad-06045d391573`,
assistant `8b8fcb1b-29e9-4e58-b66d-277319d82b60`. The same conversation supplied the image batch.

The older installed SDK initially reported uncertain analysis and could not recognize the
modern completed assistant turn. The first draft was observed unsubmitted before any send.
The later submitted response was reconciled from that exact conversation without resending.
The image collector's old generating flag missed the Vietnamese `Ngừng` label; completion
was therefore confirmed from four gallery images and the native completed-response state.
These are remaining SDK integration gaps, not automatic production acceptance.

The leased persistent Flow Camoufox session uploaded four references using a validated
browser-authenticated nonpaid `maseQ` recipe. Authentication and native CAPTCHA execution
remained inside the browser. No credential export or challenge bypass was used.
Filename selection was checked against actual ordered composer media IDs:

1. `c2366ea7-0a50-49e2-b070-3cfd1834ec72`
2. `7ae18684-5b59-4238-9420-f7471792271d`
3. `934468e8-d322-44ff-b22e-e3c90e4beaef`
4. `fd38ea25-f694-42a1-9e40-95df342ff4ec`

A durable intent preceded exactly one native generation. Its request was checked against
the full prompt and all four reference IDs. Preset: Omni 1.1 Flash, Ingredients, 9:16,
10 seconds, 360p, x1; UI quote was 7 credits, not an independently audited billing total.

- Flow project: `487247a1-00f4-4de3-83c1-4c16ce834b93`.
- Native media: `e0fc2531-f0b0-4c61-bfad-5fd4f8f10c5d`.
- Workflow: `185996fa-84e6-41f9-829a-d151fdfa7fb7`.
- KBS exchange `nreq-000130`: `CAE`, outcome 3. `nreq-000131`: exact media video URL present.
- Download choices: GIF270p, original360p, upscaled720p. Selected highest video720p.
- Upscale exchange `nreq-000157`: completed outcome3. Both downloads reached full local bytes
  before closing the browser/profile owner. No paid result remains uncertain.

The original was reviewed before upscale. The highest download was fully decoded and
reviewed in 40 samples. All four scenes and key reference actions appeared in order, with
no visible speech balloons in those samples. This is not pixel identity or every-frame proof.
ASR on original sound returned low-confidence nonsensical text, which was not accepted as
source dialogue. For this silent source, all generated audio was muted. Final decoded PCM
is all zero; the H.264 video stream hash is unchanged:
`ef7086f23959432f2c99e262c68264d5151161179d62cefcf14556dcf1b0b3c1`.
Final media:720×1280,10.000s,24fps,240frames,H.264+AAC; complete decode passed.

Caption generation used the current canonical GPT FullProxy text-recovery implementation,
conversation `6ab91d79-1878-83ec-be1d-d750ec040e09`, assistant
`38557424-811f-4eea-b9c8-69d66f38ad7d`; SDK result `verified`.

## Source changes and verification

- `story_video_prompt`: one ordered story prompt; no panel truncation or silent splitting;
  explicit verified dialogue and duration budget.
- `StoryReceipt`: exclusive pre-submit intent, exact project/media/workflow binding, uncertain
  intent cannot be resubmitted, completed package binds the same archived source and video bytes.
- `flow_browser_upload`: bounded image read, byte-identical MIME verification, persistent upload
  receipts, main-world authenticated request, bounded full response transfer and no automatic retry.
- Native composer supports four observed references; larger batches remain unverified.
- Actual-JavaScript regressions cover CAPTCHA field-only injection, project navigation during
  CAPTCHA wait, response byte budget and malformed UTF-8. No secret is put into a filename.

Independent review found three initial issues and one final archived-source verification gap.
All were reproduced with failing tests and fixed. Full unit suite:977 passed/83.46s before
the final source-byte check; final affected suite:43 passed; actual-JavaScript tests:4 passed.
Critical-error Ruff and `git diff --check` passed. The first broad test attempt used a Python
environment missing timezone data; rerun used the installed bundle's verified timezone database.

Local evidence: `D:\StableApp\ThoRemix\data\story-run-20260927` includes submit/upload/download
receipts, ordered image review, original/highest downloads, final-media QA, frozen package
receipt, copy provider receipt and test reports. Signed media URLs and credentials are not
stored in repository docs or test fixtures.

## Exact continuation boundary

This is a successful operator-driven run through ComicReels components, not unattended
production acceptance. `FlowKitProducer.status().automatic_story_ready` remains false.
The installed EXE still needs the deterministic whole-story orchestration, modern GPTFP
text/image capability combination, reconciliation and content QA wired into its producer.
Do not enable daily production or count this operator run as a five-clip quota test.

Campaign remains disabled, scheduled mode, default5 successful clips/day. FBR2 is unmerged;
extension remains selected as the application's default backend. Current source is dirty
at ComicReels `4ddd23f3906ba28011bd0c7e8c93db691f9aae29`, equal to the fetched remote
integration branch before these local changes. The live run used KBS
`b539e9820d433c8c9d667b4e5d9007b6a80b8abd`. Final freshness check found six newer remote
commits; the clean canonical KBS checkout was fast-forwarded to current `origin/main`
`b1a78e1f5905c57228a2a67987bc7dea42a7569d`. The application's pinned release is unchanged.
Post-update compatibility checks passed102 browser session/auth/discovery/backend/upload/semantic tests.
No backend cutover or new stable deployment occurred.
