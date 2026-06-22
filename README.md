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
├── mobile/                 # Expo SDK 55 app — web + native from one codebase
│   ├── src/app/            # Expo Router v3 file-based routes (route groups)
│   └── src/lib/            # apiGet<T> networking primitive (PR 5)
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
| 5 | Mobile foundation + Auth | 🚧 PR 5a in flight (web foundation landed; PR 5b native auth next) |
| 6 | Match browse + signup | pending |
| 7 | Admin + chat + profile | pending |

Design decisions and rationale live in `sdd/padel-mvp/...` Engram
artifacts (`mem_search "sdd/padel-mvp/..."`).

## Mobile app notes

- **Toolchain**: Expo SDK 55 + Expo Router v3 + TypeScript + TanStack React
  Query v5 + Clerk Expo. One codebase serves web and native.
- **Web first**: PR 5a shipped web sign-in via Clerk's prebuilt components
  (`mobile/src/app/(auth)/sign-in.web.tsx`, `sign-up.web.tsx`); PR 5b will
  add native email/password, OAuth, and forgot-password flows.
- **Auth provider wiring**: `ClerkProvider` (outer) → `QueryClientProvider`
  → `Slot` in `mobile/src/app/_layout.tsx`. `ClerkProvider` must be
  outermost so `apiGet<T>` can call `useAuth().getToken()` from inside
  any `useQuery`.
- **Token persistence**: `@clerk/expo/token-cache` — SecureStore on native,
  `localStorage` on web. Required for reload-persists-session (A04).

### Quickstarts

- [Expo SDK 55 quickstart](https://docs.expo.dev/tutorial/introduction/)
- [Clerk Expo quickstart](https://clerk.com/docs/quickstarts/expo)
- **OAuth (Google/Apple)**: after deploying, register `padelito-clubito://oauth-callback` as an allowed redirect URL in the Clerk dashboard.

### Gotchas

- `expo start --web` requires **Node 20.19+** (we run 22.22.3 locally).
- `EXPO_PUBLIC_API_URL` defaults to `http://localhost:8000/api/v1`, which
  only works on the dev machine. For a **physical device**, replace it
  with your machine's LAN IP (e.g. `http://192.168.1.42:8000/api/v1`) —
  see [Expo's networking guide](https://docs.expo.dev/get-started/start-developing/#tunnel-urls)
  for the alternatives (LAN, tunnel, localhost).
- pnpm 11+ requires `pnpm approve-builds` (interactive) before
  `pnpm install` will run transitive native build scripts. Run this
  locally once after pulling.
- Don't paste a real `pk_live_*` into `mobile/.env.example` — only the
  documented variable names belong there.