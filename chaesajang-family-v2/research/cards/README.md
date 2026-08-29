# Research evidence cards

`../index.jsonl` is the normalized, append-only evidence index. Each line has the
ten research-protocol fields plus a derived `status`:

- `actionable`: connected, non-low-confidence official, peer-reviewed, or technical evidence.
- `watchlist`: low-confidence evidence and every preprint or blog; it cannot alone justify a candidate change.

Use the primary source URL and its publication date when that page exposes one.
For an unversioned living document, record version provenance in `source_date`
(for example an official `Last-Modified` value or the documented release it
describes), state that basis in `evidence`, and never substitute a retrieval
date. `checked_at` is the date the card was reviewed. Every card must name a
local decision and a test that could falsify the claim.
