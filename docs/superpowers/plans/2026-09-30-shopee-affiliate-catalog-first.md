# Shopee Affiliate catalog-first integration — development plan

Date: 2026-09-30
Status: **DEVELOPMENT COMPLETE — VALIDATION/FIX DEFERRED**

## Goal

ThoRemix must select Shopee Affiliate products from the Product Offer listing using the fields
already visible on cards, instead of opening each candidate detail page before selection.

## Development-first execution rule

- Finish this complete plan in GitHub source before any local/runtime validation.
- Remote Desktop is validation/observation only after development completion and must never edit source.
- Any later defect is fixed in GitHub source first, then canonical source is updated and validation reruns.
- Stable/AppData/runtime source is never hotfixed directly.

## C1 — Product Offer card parser — COMPLETE

- Exact Product Offer identity is preserved.
- Price and observed sold count are read from the card.
- Displayed commission is read from the card.
- Vietnamese + English labels are supported:
  - `Tỉ lệ/Tỷ lệ hoa hồng`
  - `Comm Rate/Commission Rate`
  - `lượt bán`
  - `sold`
- Unknown or ambiguous observations remain unknown.

## C2 — Catalog-first selection — COMPLETE

- Price cap and sold threshold are applied before detail work.
- ThoRemix commerce ordering remains:
  1. commission percentage descending;
  2. price ascending;
  3. observed sold descending.
- Listing commission is the normal selection basis.
- `detail_count=0` on the normal path.
- Product Offer detail is bounded fallback only when no eligible listing card exposes a usable rate.

## C3 — Fallback detail contract — COMPLETE

- Fallback keeps component evidence separate from card-displayed commission.
- Social/Other Content and Facebook/Instagram Reels rows support Vietnamese/English labels.
- The conservative cross-channel fallback rate remains the lower verified placement total.

## C4 — Durable Get Link mutation — COMPLETE

- Intent is persisted before the external effect.
- Intent freezes exact Product Offer/product ID plus selected evidence.
- Listing is re-read before mutation.
- Exactly one Product Offer card must match the selected product.
- Title/price/sold/commission must remain unchanged.
- Get Link executes on the selected card, not the detail page.
- An ambiguous/timeout activation is not repeated blindly.
- Short link is stored before read-only destination reconciliation.
- Browser destination must resolve to the selected product ID.
- `shop_id` is learned from verified destination only.

## C5 — KAT integration boundary — COMPLETE

KAT owns generic Product Offer/parser/filter contracts. ThoRemix retains its production-specific
durable receipt/idempotency/reconciliation adapter.

ThoRemix now passes the sold threshold through `SelectionPolicy.sold_min` and requires the
catalog-first KAT contract before Stable promotion.

Canonical KAT feature merge:
`a575a78d4ad6663cc7b796575b9f532f3620fb24`

Canonical ThoRemix consumer merge:
`5e93f1a61ccec63fa3f034613fcf7b34cf1b7224`

## C6 — Build/deployment contract — COMPLETE

`Build-Stable.ps1` contains a fail-closed contract check for:

- KAT `sold_min` / `commission_min`;
- `catalog_first=True`;
- legacy public-search fallback disabled by default;
- canonical Product Offer surface.

The development contract is complete. Whether a particular runtime staging path satisfies it is
a **validation concern**, not a reason to edit deployment code during the development phase.

## C7 — Docs/rules/checkpoint — COMPLETE

- THOREMIX-STABLE documents catalog-first behavior and KAT dependency.
- AGENTS separates development completion from validation.
- This plan is the durable scope boundary.

## Required deployment order for the later validation phase

1. canonical KAT;
2. update local KAT checkout;
3. canonical comicReels/ThoRemix;
4. run validation;
5. fix any reproduced defect in GitHub source;
6. only after validation acceptance, build/promote Stable.

## Deferred validation/fix backlog

The following observations were produced before the owner reasserted the development-first rule.
They are recorded but intentionally **not fixed inside this development plan**:

- a staged-build smoke observed a KAT contract mismatch when using an older installed/staged KAT;
- a broad ThoRemix regression observed an unrelated review-window frame-count failure;
- GitHub Actions runner availability may fail before any CI step starts.

These items belong to the next validation/fix checkpoint. They must be reproduced against the
completed canonical development state before any repair is accepted.

## Out of scope

- Shopee authenticated web-session/API replay transport optimization;
- changing Stable application state during this development checkpoint;
- unrelated desktop/media fixes;
- direct local/runtime code edits.

## Completion gate

C1–C7 are complete in canonical GitHub source/docs. Development is therefore complete.
Testing, runtime validation and defect repair begin only in the next checkpoint.
