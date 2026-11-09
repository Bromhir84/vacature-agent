# Vacature Agent

Containerized multi-site vacancy scanner for **detachering / extern / inlener** roles.

- Config-driven **json**, **html**, and **agent** adapters
- Deterministic staffing gate + STACKIT LLM classifier
- Web dashboard with **New / Open / Removed** listing inbox
- Admin discovery (propose career pages, portal harvest, broker denylist)

Seeded employer sources:

1. **Werken bij ANWB** — JSON API filtered on `Dienstverband=Inhuur`
2. **Werken bij NS** — HTML list at `/vacatures?keywords=Inhuur`

Add more via **Admin → Sources → Quick add** or **Admin → Discover**.

## Quick start (Docker Compose)

Requirements: Docker Desktop (or Docker Engine + Compose v2).

```bash
git clone https://github.com/Bromhir84/vacature-agent.git
cd vacature-agent

cp .env.example .env
# edit .env and set LLM_API_KEY (STACKIT AI Model Serving token)

docker compose up --build -d
```

On Windows PowerShell:

```powershell
git clone https://github.com/Bromhir84/vacature-agent.git
cd vacature-agent
Copy-Item .env.example .env
# edit .env → LLM_API_KEY=...
docker compose up --build -d
```

| Service | URL |
| --- | --- |
| UI | http://localhost:43218 |
| API health | http://localhost:8000/api/health |

Useful commands:

```bash
docker compose ps
docker compose logs -f api
docker compose up --build -d          # rebuild after code changes
docker compose down                   # stop
docker compose down -v                # stop + wipe SQLite volume
```

Then open **Admin → Sources → Scan all** (or wait for the scheduled interval).

## Local development (without Compose)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env   # then edit LLM_API_KEY
set DATABASE_URL=sqlite:///./data/vacature.db
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8000`.

## STACKIT LLM

| Variable | Default |
| --- | --- |
| `LLM_BASE_URL` | `https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1` |
| `LLM_MODEL` | `Qwen/Qwen3.8-27B` |
| `LLM_API_KEY` | your STACKIT token |

Without `LLM_API_KEY`, scans still discover listings; the deterministic gate can promote matches (useful for smoke tests). You can also set the key later in **Admin → Settings**.

## Adapters

### json
Point `list_url` at a vacancy JSON API and map fields in `config.item_map`.

### html
Point `list_url` (+ optional `query`) at an SSR overview page and configure CSS selectors. Supports Hippo CMS fragments (`hippo_component`) and `pagination.page_param`.

### agent
LLM tool loop (`http_get`, `extract_links`) for arbitrary employer career pages.

Optional Playwright sidecar:

```bash
docker compose --profile browser up -d
```

## API sketch

- `GET/POST /api/sources`
- `GET /api/listings?status=new|open|removed`
- `POST /api/listings/{id}/view`
- `POST /api/scans/run`
- `POST /api/discovery/propose` / `harvest`
- `POST /api/crawl/run`
- `GET/PATCH /api/settings`

Admin UI: `/admin/sources`, `/admin/discover`, `/admin/runs`, `/admin/settings`, `/admin/filters`.
