# Plants Tracker — Changelog & Bug Log

## Architecture

- **Bot**: `main.py` + `handlers.py` + `db.py` (aiosqlite async)
- **Web (standalone)**: `web.py` — Flask app, used for local dev only
- **Web (production)**: `server/panel/plants_routes.py` — Flask blueprint mounted at `/plants/` inside the control panel at port 9000
- **DB**: `~/apps/plants/plants.db` on VM a-bot (Tailscale: `100.79.128.124`)
- **Panel repo**: `github.com/dataSci-rigo/control_panel` → deployed at `~/apps/panel/`
- **Plants repo**: `github.com/dataSci-rigo/plants` → deployed at `~/apps/plants/`

---

## Upgrades

### 2026-06-29 — Pest, Disease & Treatment Tracking
**Files changed:** `db.py`, `handlers.py`, `i18n.py`, `main.py`, `web.py`, `templates/plant.html`, `server/panel/plants_routes.py`

New DB tables:
- `issues` — pest/bug infestations and fungal diseases (rust, mold). Fields: category (bug/fungal/other), description, severity, resolved flag, observed_at, resolved_at
- `treatments` — treatments applied. Boolean columns for each ingredient (soap, spinosad, neem, kaolin) + optional notes

New bot commands:
- `/pest <plant> <description>` — log a bug infestation
- `/disease <plant> <description>` — log rust/mold/fungal issue
- `/treat <plant> [soap] [neem] [spinosad] [kaolin] [notes]` — log treatment; ingredients detected by keyword in any order
- `/issues <plant>` — show open (unresolved) issues

Available treatment ingredients: pure castile soap, spinosad concentrate, pure neem oil, white kaolin clay. All mixed with water and can be combined.

Web UI additions on plant detail page:
- **Pests & Diseases** section: inline log form (category dropdown + description), issue list with ✓ Resolve button
- **Treatments** section: ingredient checkboxes + notes field, history table with color-coded ingredient badges

---

### 2026-06-25 — Log Watering Button (Web UI)
**Files changed:** `templates/plant.html`, `web.py`, `server/panel/plants_routes.py`

Added POST route `/plant/<id>/water` and a 💧 Log watering form on the plant detail page. Amount field pre-fills with the plant's default `watering_amount_ml`.

---

### 2026-06-25 — /help Telegram Command
**Files changed:** `handlers.py`, `main.py`, `i18n.py`

Added `/help` command that returns the full command list (same text as `/start`). Registered in both EN and ES.

---

### 2026-06-25 — Plants Web UI via Panel Blueprint
**Files changed:** `server/panel/plants_routes.py` (new), `server/panel/app.py`, `templates/plants_list.html` (renamed from `index.html`)

Moved plants web UI from a standalone Flask server (port 8002/5060) into a blueprint mounted at `/plants/` on the control panel (port 9000). This is the correct pattern — all web UIs live inside the panel app, never on separate ports.

Key decisions:
- Template renamed `index.html` → `plants_list.html` to avoid collision with the panel's own `templates/index.html`
- All internal links use `{{ url_prefix }}` variable: `""` for standalone `web.py`, `"/plants"` for blueprint
- `_PLANTS_DIR` resolved dynamically: checks `~/apps/plants` first (VM), falls back to `~/Documents/plants` (local)

---

### 2026-06-24 — Jasmine Added to DB
First plant added. Details: pot, 10in × 11in (approx 25cm × 28cm), 40cm tall, northeast facing, potting soil (Home Depot), no fertilizer, AI-suggested watering schedule.

---

## Bug Fixes

### 2026-06-25 — Relative DB Path (Critical)
**Symptom:** Data not saving; web server read an empty/nonexistent database.
**Root cause:** `DB_PATH = "plants.db"` in both `db.py` and `web.py`. When the panel Flask app runs, its CWD is `~/apps/panel`, not `~/apps/plants`, so it opened a different (empty) file.
**Fix:** `DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plants.db")` — absolute path resolved relative to the source file.

---

### 2026-06-25 — Port Mismatch
**Symptom:** `web.py` standalone server started on port 8002, but the panel serves everything on 9000.
**Root cause:** `web.py` read `PORT_PLANTS` env var (8002); panel uses `CONTROL_PANEL_PORT` (9000).
**Fix:** `web.py` now checks `CONTROL_PANEL_PORT` first, then `PORT_PLANTS`, then falls back to 5060. Moot for production (blueprint handles it), but keeps local dev working.

---

### 2026-06-25 — Template Collision
**Symptom:** `/plants/` returned the control panel's home page instead of the plants list.
**Root cause:** Both the panel and the plants blueprint had `templates/index.html`. Flask resolves templates by checking the app's templates folder first, so the panel's `index.html` won.
**Fix:** Renamed plants list template to `plants_list.html`.

---

### 2026-06-25 — Git Conflict on VM After Direct SCP
**Symptom:** `git pull` on VM failed with "local modifications" error after files were SCP'd directly.
**Root cause:** SCP'd `app.py` and `plants_routes.py` directly to VM, then tried `git pull` — conflict.
**Fix:** `git stash && git pull origin main` on VM, then re-deploy via git push from local.

**Rule going forward:** Never SCP files that are tracked in a git repo. Always commit + push locally, then `git pull` on the VM. Only SCP files that aren't in any repo (e.g., one-off scripts, local `.env` patches).

---

## Pending / Known Issues

- [ ] Verify `scheduler.py` jobs are running on VM (check `systemctl status app-plants` logs for daily recommendation and biweekly height reminder job output)
- [ ] `app.py` in panel repo has uncommitted changes (panel services listing update) — needs a separate commit
- [ ] No severity selector in the web UI issue form yet (currently always defaults to "mild")
- [ ] No way to link a treatment to a specific issue from the web UI (issue_id FK exists in schema but not wired up)
