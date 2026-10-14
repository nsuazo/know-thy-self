# Know Thy Self

A personal self-reflection journal: one entry per day from a fixed template, todos that carry
forward until finished, full-text search, and a nightly Markdown export. Later phases add LLM
review panels, summaries, a profile, and a questions page using a local OpenAI-compatible model.

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
| `LLM_BASE_URL` | `http://192.168.1.80:8090/v1` | OpenAI-compatible endpoint (Phase 2+) |
| `LLM_MODEL` | `gemma-official` | Model name (Phase 2+) |
| `PUID` / `PGID` | `99` / `100` | Owner of `/data` (Unraid nobody:users) |

## Data

- `/data/know-thy-self.db`: the source of truth.
- `/data/export/YYYY/YYYY-MM-DD.md`: one Markdown file per day, rewritten nightly and on demand
  from the History page. Only changed files are written.
