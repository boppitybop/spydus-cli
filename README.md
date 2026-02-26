# spydus-cli

`spydus-cli` automates common Spydus account workflows from the terminal.

## What it can do

- Login with cached session reuse
- Prompt for credentials and save them to `.env`
- Switch between multiple library profiles
- List current loans (with reserve counts)
- Renew overdue loans by default, or all loans when explicitly requested
- Show renewal failures per item
- Show account sections:
  - available for pickup
  - reservations not yet available
  - requests
  - history
- Query whether an item appears in the catalogue
- Filter catalogue queries by item type (book, ebook, audiobook, dvd, music-cd)
- Submit hold requests (direct URL or selected catalogue match)
- Output machine-ingestible JSON

## Quick start

### Option A: with `uv` (recommended)

```bash
uv sync
uv run spydus-cli --help
```

### Option B: with pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
spydus-cli --help
```

## Credentials

You can configure credentials in multiple ways:

1. CLI flags: `--user`, `--password`
2. Environment variables in `.env`
3. Interactive prompt (`--setup-creds` or automatic prompt when needed)

Create `.env` from example:

```bash
cp .env.example .env
```

Supported variables:

```bash
# Default profile
SPYDUS_BASE_URL=https://your-library.spydus.com
SPYDUS_USER=your_card_number
SPYDUS_PASSWORD=your_password

# Optional: selected library profile key
SPYDUS_LIBRARY=act

# Profile-specific credentials (example: ACT)
SPYDUS_ACT_BASE_URL=https://librariesact.spydus.com
SPYDUS_ACT_USER=your_card_number
SPYDUS_ACT_PASSWORD=your_password

# Additional profile (example)
SPYDUS_CITY_BASE_URL=https://citylibrary.spydus.com
SPYDUS_CITY_USER=other_card
SPYDUS_CITY_PASSWORD=other_password
```

## Common usage

```bash
# Setup credentials interactively and save locally
uv run spydus-cli --setup-creds --save-creds

# Check current loans
uv run spydus-cli --check-loans

# Renew all overdue renewable loans
uv run spydus-cli --renew-all

# Explicit overdue-only renewal command
uv run spydus-cli --renew-overdue

# Renew all renewable loans (overdue + non-overdue)
uv run spydus-cli --renew-all-loans

# Renew with confirmation before each
uv run spydus-cli --renew-confirm

# Show account sections
uv run spydus-cli --check-account

# Select account sections
uv run spydus-cli --check-account --account-sections pickups,reservations,requests,history

# Search catalogue
uv run spydus-cli --catalogue-query "Atomic Habits" --catalogue-limit 5

# Search catalogue with item-type filter
uv run spydus-cli --catalogue-query "World War Z" --catalogue-type book,audiobook

# Search and switch to a specific library profile
uv run spydus-cli --library act --catalogue-query "Atomic Habits" --catalogue-limit 5

# Place hold with direct hold URL
uv run spydus-cli --place-hold-url "https://.../RSVC..."

# Start reservation flow (lists matching candidates)
uv run spydus-cli --place-hold-item "Atomic Habits"

# Submit reservation for selected candidate index
uv run spydus-cli --place-hold-item "Atomic Habits" --place-hold-item-index 2

# Submit reservation with optional pickup branch
uv run spydus-cli --place-hold-item "Atomic Habits" --place-hold-item-index 2 --pickup-branch "Belconnen"

# Strict machine-readable output
uv run spydus-cli --check-loans --check-account --output json
```

## Output modes

- `--output table`: readable table output
- `--output compact`: concise one-line records with status badges
- `--output json`: strict JSON payload on stdout for automation pipelines

## Catalogue type filters

`--catalogue-type` accepts a comma-separated list of types to narrow catalogue results.

| Type | Aliases | Spydus codes |
|---|---|---|
| `book` | `books` | BK |
| `ebook` | `e-book`, `e-books` | EBK |
| `audiobook` | `audio-book`, `audio-books` | EAUD, AB |
| `eaudiobook` | `eaudio`, `e-audio` | EAUD |
| `dvd` | `dvds` | DVD, VD |
| `music-cd` | `cd`, `music`, `musiccd`, `music-cds` | CD, MCD, MU |

Examples:

```bash
# Single type
uv run spydus-cli --catalogue-query "Everybody scream" --catalogue-type music

# Multiple types
uv run spydus-cli --catalogue-query "World War Z" --catalogue-type book,audiobook
```

Notes:
- When a single Spydus format code is resolved, it is sent as the `RECFMT` query parameter for server-side filtering.
- When multiple codes match, results are filtered client-side by checking `RECFMT` values, `03902\\<format>` signals, and details text.
- Some tenants expose mixed formats on one work record (e.g. `BK,EBK`), so filters include records that match **any** requested format.

## Compliance and usage notes

- This tool is intended for your own account operations.
- Respect each library's terms, robots policy, and rate limits.
- Avoid high-frequency scraping or abusive usage.
- Confirm automation is allowed for your account and jurisdiction before use.
- This project does not provide legal advice.

## Security notes

- `.env` is ignored by git.
- Session cookies are cached locally at `~/.cache/spydus-cli/session.json` with `0600` permissions.
- Session cookies are cached per profile at `~/.cache/spydus-cli/session-<profile>.json` with `0600` permissions.
- Avoid passing `--password` in shared shell history environments.

## Development

```bash
uv run poe check
```

This runs linting, formatting, and tests.
