# Vacature Agent

Containerized multi-site vacancy scanner for **detachering / extern / inlener** roles.

- Config-driven **json**, **html**, and **agent** adapters
- Deterministic staffing gate + STACKIT LLM classifier (`Qwen/Qwen3.8-27B`)
- Web dashboard to manage sources and approve/reject listings

Seeded sources (employer career sites):

1. Werken bij ANWB — JSON API filtered on `Dienstverband=Inhuur`
2. Werken bij NS — HTML list at `/vacatures?keywords=Inhuur`
3. WerkenvoorNederland ICT (+ inhuur term) — agent
4. WerkenbijdeOverheid, Belastingdienst, Amsterdam, Defensie, Achmea
5. Enexis + Radboudumc (HTML), Port of Rotterdam (agent)
6. Rijkswaterstaat / Kadaster / DICTU ICT via WerkenvoorNederland (agent)

Add more via **Admin → Sources → Quick add career URL** (creates an agent source).

## Quick start (Docker)

```bash
cp .env.example .env
# set LLM_API_KEY to your STACKIT AI Model Serving token

docker compose up --build -d
```

- UI: http://localhost:43218
- API: http://localhost:8000/api/health

Then open **Admin → Sources → Scan all** (or wait for the scheduled interval).

## Local development

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

Uses the same OpenAI-compatible endpoint as `coa-equal-rewards`:

| Variable | Default |
| --- | --- |
| `LLM_BASE_URL` | `https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1` |
| `LLM_MODEL` | `Qwen/Qwen3.8-27B` |
| `LLM_API_KEY` | your STACKIT token |

Without `LLM_API_KEY`, scans still discover listings and the deterministic gate can promote matches to `candidate` (useful for smoke tests).

## Adapters

### json
Point `list_url` at a vacancy JSON API and map fields in `config.item_map`.
Supports root-array responses (`pagination.items_path: "$"`), `employment_map`, and client-side `filter`.

### html
Point `list_url` (+ optional `query`) at an SSR overview page and configure CSS selectors.

### agent
LLM tool loop (`http_get`, `extract_links`) for arbitrary employer career pages.
Supports `focus_keywords` in config to bias discovery (inhuur / ICT by default).
Optional Compose profile:

```bash
docker compose --profile browser up -d
```

## API sketch

- `GET/POST /api/sources`
- `GET /api/listings?status=candidate`
- `POST /api/listings/{id}/review`
- `POST /api/scans/run`
- `POST /api/crawl/run` (open-web vacature URL crawler + heuristic relevance score)
- `GET/PATCH /api/settings` (LLM key/base/model + filters; secrets masked in responses)

Admin UI at `/admin/sources`, `/admin/discover`, `/admin/runs`, `/admin/settings`, and `/admin/filters`.
