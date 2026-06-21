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
├── mobile/                 # Expo app (added in PR 5)
├── docker-compose.yml      # Postgres + Django web + qcluster
└── README.md
```

## Quickstart (Docker)

```bash
cp backend/.env.example backend/.env       # tweak as needed
docker compose up --build                  # postgres + django + qcluster
docker compose exec web python manage.py createsuperuser
```

Visit:
- API root — `http://localhost:8000/`
- Django admin — `http://localhost:8000/admin/`

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

## Tests

```bash
cd backend
pytest                                      # full suite with coverage
pytest players/tests/test_fields.py -v      # single file
pytest --no-cov                             # skip coverage report
```

Coverage targets (enforced via `pytest.ini`):
- `players.fields.LevelField` ≥ 90%
- Per-app models ≥ 80%

See [docs/padel-mvp/spec](docs/spec.md) (PR-2 PRs land richer docs as the
backend fills in).

## Roadmap

PRs are stacked to `main`. Each PR delivers a reviewable work unit:

1. Backend foundation (this PR) — 8 apps, LevelField, base models.
2. Auth (Clerk JWT + webhooks) + Clubs/Courts/Schedule + slot generation.
3. Matches lifecycle + Companions.
4. Chat + Notifications (Q2/Expo/Resend).
5. Mobile foundation + Auth.
6. Match browse + signup.
7. Admin + chat + profile.

See `docs/padel-mvp/...` artifacts for full scope.