# Know Thy Self

A personal self-reflection journal: one entry per day from a fixed template, todos that carry
forward until finished, full-text search, and a nightly Markdown export. A local OpenAI-compatible
model adds review panels, weekly/monthly summaries, a versioned profile, and a Questions page that
asks you direct questions to build your profile and personal history.

See [docs/SPEC.md](docs/SPEC.md) for the full design.

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload --port 8480
```

Open http://localhost:8480.

## Deploy on Unraid

1. Push to `main`. GitHub Actions builds `ghcr.io/<owner>/know-thy-self:latest`.
2. The repo is private, so the image is private too. On the Unraid terminal, log in to GHCR once
   with a classic personal access token that has only `read:packages`:
   ```bash
   docker login ghcr.io -u <github-user>
   ```
3. Copy `unraid/know-thy-self.xml` to
   `/boot/config/plugins/dockerMan/templates-user/my-know-thy-self.xml`, replace `CHANGEME` with
   your GitHub username, then in the Docker tab choose **Add Container** and pick
   **know-thy-self** from the template list.
4. Open `http://<unraid-ip>:8480`.

To update: push to `main`, wait for the workflow, then **Check for Updates** → **Apply Update**
in Unraid's Docker tab.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` | SQLite DB and `export/` |
| `TZ` | `America/Chicago` | Logical day and export schedule |
| `DAY_CUTOFF_HOUR` | `4` | Writing before this hour counts as the previous day |
| `EXPORT_HOUR` | `3` | Nightly Markdown export hour; `-1` disables |
| `LLM_BASE_URL` | `http://192.168.1.80:8090/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `gemma-official` | Model name sent with each request |
| `LLM_TIMEOUT` | `600` | Seconds to wait for an answer (no retry: a timeout is reported as an error) |
| `LLM_MAX_TOKENS` | `16384` | Output limit; thinking counts against it |
| `LLM_ENABLE_THINKING` | `true` | `false` sends `enable_thinking=false` (test it first) |
| `LLM_SUMMARY_THINKING` | `false` | Thinking for weekly/monthly summaries (the profile and reviews use `LLM_ENABLE_THINKING`) |
| `CONTEXT_BUDGET_TOKENS` | `90000` | Prompt size budget; oldest entries are dropped first |
| `CONTEXT_MIN_DAYS` | `14` | Recent days always included as context |
| `ALLOWED_HOSTS` | _(empty)_ | Extra host names to accept, comma-separated (e.g. a reverse-proxy domain). IPs, `localhost`, single-label names like `tower`, and `.local`/`.lan`/`.home.arpa`/`.internal` names are always accepted. `*` turns the check off. |
| `PUID` / `PGID` | `99` / `100` | Owner of `/data` (Unraid nobody:users) |

## Testing the LLM connection

Standard library only, so it runs anywhere with Python 3:

```bash
python3 scripts/test_llm.py
```

It lists the server's models, makes a chat request with the server's default thinking, and tries
`enable_thinking=false`, then tells you whether that switch works. The first request after the
model was idle can take 20-30 seconds while it loads.

## Data

- `/data/know-thy-self.db`: the source of truth.
- `/data/export/YYYY/YYYY-MM-DD.md`: one Markdown file per day, rewritten nightly and on demand
  from the History page. Only changed files are written.
