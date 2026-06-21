# Padel MVP

Self-service padel: club admins manage courts and schedules, players sign up
for 2v2 matches with level matching, per-match chat, and push + email
notifications.

## Stack

- **Backend**: Django 5.2 LTS + DRF 3.15 + PostgreSQL 16 + django-q2 (ORM
  broker locally, Redis in production) + Clerk (JWT auth, webhooks) +
  django-unfold admin theme.
- **Mobile**: Expo SDK 55 + Router + React Query + Zustand + Clerk Expo.
- **Notifications**: Expo Push + Resend (email).

## Repo layout

```
.
├── backend/                # Django project (apps/, settings, requirements)
│   ├── clubs/              # Club, Court, Schedule
│   ├── match_slots/        # MatchSlot (eager-generated booking windows)
│   ├── matches/            # Match, MatchPlayer (host-first, ±0.25 levels)
│   ├── companions/         # Anonymous per-match players
│   ├── players/            # Custom User model + LevelField
│   ├── chat/               # Per-match polling chat (XOR author)
│   ├── notifications/      # NotificationLog (push + email audit)
│   └── auth_clerk/         # Clerk JWT + webhooks (scaffolded; PR 2)
├── mobile/                 # Expo app (added in PR 5)
├── docker-compose.yml      # Postgres + Django web + qcluster
└── README.md
```

## Apps at a glance

| App | Models | Notes |
|-----|--------|-------|
| `clubs` | Club, Court, Schedule | Club.address required (CheckConstraint) |
| `match_slots` | MatchSlot | Unique on (court, start_time) |
| `matches` | Match, MatchPlayer | Derived status: open/full/in_progress/finished |
| `companions` | Companion | Anonymous, per-match, counts toward 4-cap |
| `players` | User | Clerk-backed, LevelField default 3.00 |
| `chat` | ChatMessage | XOR author_user XOR author_companion |
| `notifications` | NotificationLog | Push + email audit trail |
| `auth_clerk` | — | JWT middleware + webhooks land in PR 2 |

## Quickstart (Docker)

```bash
cp backend/.env.example backend/.env       # tweak as needed
docker compose up --build                  # postgres + django + qcluster
docker compose exec web python manage.py createsuperuser
```

Visit:
- API root — `http://localhost:8000/`
- Django admin — `http://localhost:8000/admin/`
- Q2 dashboard — `http://localhost:8000/admin/django_q/`

## Quickstart (local Python)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # tweak DATABASE_URL etc.
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

In a second terminal:

```bash
python manage.py qcluster                   # async task worker
```

For PR 1 the database can be SQLite for quick iteration:

```bash
DATABASE_URL=sqlite:///db.sqlite3 python manage.py migrate
DATABASE_URL=sqlite:///db.sqlite3 pytest
```

## Tests

```bash
cd backend
pytest                                      # full suite with coverage report
pytest players/tests/test_fields.py -v      # single file
pytest --no-cov                             # skip coverage report
pytest -k "LevelField"                      # by keyword
```

Coverage targets (configured in `pytest.ini`, enforced via `pytest-cov`):

| Layer | Target |
|-------|--------|
| `players.fields.LevelField` | ≥ 90% |
| Per-app model layer | ≥ 80% (added as PRs mature) |
| Top-level `--cov-fail-under` | 0 (PR 1 — raised in later PRs) |

## Environment variables

Copy `backend/.env.example` to `backend/.env` and adjust. The full set is:

| Var | Purpose | Required |
|-----|---------|----------|
| `SECRET_KEY` | Django secret key | yes (prod) |
| `DEBUG` | Django debug flag | yes |
| `DATABASE_URL` | Postgres URL (or sqlite:///path for dev) | yes |
| `ALLOWED_HOSTS` | Comma-separated host list | yes |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origin list | yes |
| `TIME_ZONE` | Django TZ (default `Europe/Madrid`) | no |
| `MEDIA_ROOT` / `MEDIA_URL` | User-uploaded files | no |
| `CLERK_SECRET_KEY` | Clerk SDK auth | PR 2 |
| `CLERK_PUBLISHABLE_KEY` | Clerk mobile config | PR 2 |
| `CLERK_JWKS_URL` | Clerk JWT verification | PR 2 |
| `CLERK_WEBHOOK_SECRET` | Svix signature secret | PR 2 |
| `RESEND_API_KEY` | Email sender | PR 4 |
| `EXPO_ACCESS_TOKEN` | Expo Push auth | PR 4 |
| `MVP_ENABLED` | Feature flag (kills writes when false) | no |

## Roadmap

PRs are stacked to `main`. Each PR delivers a reviewable work unit:

| PR | Scope | Status |
|----|-------|--------|
| 1 | Backend foundation (8 apps, LevelField, base models) | ✅ this PR |
| 2 | Auth (Clerk JWT + webhooks) + Clubs/Courts/Schedule + slot generation | pending |
| 3 | Matches lifecycle + Companions | pending |
| 4 | Chat + Notifications (Q2/Expo/Resend) | pending |
| 5 | Mobile foundation + Auth | pending |
| 6 | Match browse + signup | pending |
| 7 | Admin + chat + profile | pending |

Design decisions and rationale live in `sdd/padel-mvp/...` Engram
artifacts (`mem_search "sdd/padel-mvp/..."`).