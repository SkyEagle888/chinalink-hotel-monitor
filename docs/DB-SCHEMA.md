# DB-SCHEMA.md — Database Definitions

> Format: `.md` | Exempt from 50KB token budget

## Status: N/A

This project has **no database**. All data is processed in-memory per run; persistent state is limited to a single file.

| File | Schema | Purpose |
|---|---|---|
| `last_hash.txt` | 64-char hex string (SHA-256) | Change detection across runs |

## In-Memory Data Structures

For reference (defined in `scrape_and_notify.py`):

### `promo` dict
- `title: str` — promotion name from `<h4><a>`
- `date: str` — publish date `YYYY-MM-DD`
- `content: str` — body text from `<span class="d-block">`
- `url: str` — canonicalized absolute URL

## Migration History
None — no database migrations applicable.
