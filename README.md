# Wallet-Based Per-Minute Session Billing

A Django + Django REST Framework backend for paid 1:1 consultations. Users keep a prepaid
wallet and top it up through a mock payment-gateway webhook. They run sessions with providers
through a strict state machine and are charged per completed minute. The system ends a session
automatically when the wallet can't cover the next minute.

- **Stack:** Python 3.13, Django 6.1, DRF 3.18, SQLite (default) or PostgreSQL
- **Auth:** DRF token authentication, with `USER` and `PROVIDER` roles
- **Docs:** [State and ER diagrams](docs/DIAGRAMS.md) · [Design notes](docs/DESIGN_NOTES.md)

---

## 1. Setup

```bash
python -m venv venv
# Windows:  venv\Scripts\activate      macOS/Linux:  source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The API runs at `http://127.0.0.1:8000/`.

### Environment variables (all optional)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file `db.sqlite3` | e.g. `postgres://user:pass@localhost:5432/billing` |
| `DJANGO_SECRET_KEY` | insecure dev key | Set in production |
| `DJANGO_DEBUG` | `1` | `0` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `PAYMENT_WEBHOOK_SECRET` | `dev-webhook-secret` | Shared secret the mock gateway sends |

To use PostgreSQL, set `DATABASE_URL` and run `migrate`. Row locks (`select_for_update`) and the
partial unique index are fully enforced on PostgreSQL. SQLite serialises writes instead.

---

## 2. Running the tests

```bash
python manage.py test            # whole suite (56 tests)
python manage.py test -v 2       # show each test name
python manage.py test consultations.tests.BillingTests   # one class
```

Time-dependent billing is tested with `freezegun`, which moves the clock instead of sleeping.
Tests use a fast password hasher, so the suite runs in about 2 seconds.

### Required scenarios → tests

| # | Scenario | Test |
|---|---|---|
| 1 | Less than 5 minutes of balance → cannot start | `consultations.tests.StartEndTests.test_cannot_start_with_less_than_5_minutes_balance` |
| 2 | Happy path: recharge → create → accept → start → bill 2 min → end | `consultations.tests.BillingTests.test_happy_path` |
| 3 | Balance runs out → auto-end, never negative, reason recorded | `consultations.tests.InsufficientBalanceTests.test_balance_runs_out_session_auto_ends` |
| 4 | Invalid transition (end before start) → 400 | `consultations.tests.StartEndTests.test_end_before_start_returns_400` |
| 5 | Duplicate recharge callback → credited once | `wallet.tests.RechargeTests.test_duplicate_success_callback_credits_only_once` |
| 6 | Duplicate billing of the same minute → charged once | `consultations.tests.BillingTests.test_duplicate_billing_does_not_charge_twice` |

Further tests cover the full transition table, role and ownership checks, the rate lock,
catch-up billing, late billing that can't go negative, database constraints, and the billing command.

---

## 3. API

Every endpoint except register, token and the webhook needs the header
`Authorization: Token <key>`.

### Auth
| Method | URL | Who | Body |
|---|---|---|---|
| POST | `/api/auth/register/` | anyone | `{"username", "password", "role": "USER"\|"PROVIDER", "per_minute_rate"}` (rate required for providers) |
| POST | `/api/auth/token/` | anyone | `{"username", "password"}` → `{"token"}` |
| GET | `/api/auth/me/` | logged in | — |

### Wallet and recharge
| Method | URL | Who | Body |
|---|---|---|---|
| GET | `/api/wallet/` | USER | — |
| POST | `/api/wallet/recharge/` | USER | `{"amount": "500"}` → `pending` recharge with a `reference` |
| POST | `/api/wallet/recharge/callback/` | gateway (header `X-Webhook-Secret`) | `{"reference", "status": "success"\|"failed"}` |

The callback is idempotent. A repeated call returns `200` with `"already_processed": true` and does
not credit again.

### Sessions
| Method | URL | Who | Transition |
|---|---|---|---|
| POST | `/api/sessions/` | USER | creates `unassigned` |
| GET | `/api/sessions/` · `/api/sessions/{id}/` | participants | — |
| POST | `/api/sessions/{id}/assign/` `{"provider_id"}` | owner (USER) | `unassigned → assigned` |
| POST | `/api/sessions/{id}/accept/` | assigned PROVIDER | `assigned → accepted_by_provider` |
| POST | `/api/sessions/{id}/start/` | owner (USER) | `accepted_by_provider → in_progress` |
| POST | `/api/sessions/{id}/bill/` | participants | bills elapsed minutes; may auto-end |
| POST | `/api/sessions/{id}/end/` | user or provider | `in_progress → completed` |
| POST | `/api/sessions/{id}/cancel/` | participants | `unassigned / assigned / accepted → cancelled` |

### Errors
Business-rule violations return JSON in the form `{"error": "<code>", "detail": "<message>"}`:

| Code | HTTP | When |
|---|---|---|
| `invalid_transition` | 400 | Action not allowed from the current status |
| `insufficient_balance` | 400 | Balance < 5 × rate at start |
| `active_session_exists` | 400 | User already has a session in progress |
| `invalid_amount` | 400 | Non-positive amount |
| `not_allowed` | 403 | Wrong participant for this action |
| `not_found` | 404 | Unknown session, provider or recharge reference |

A missing or invalid token returns `401`, the wrong role returns `403`, and a session you don't
take part in returns `404`.

---

## 4. Periodic billing

Billing is idempotent, so it can be triggered as often as you like:

```bash
python manage.py bill_active_sessions     # bills every in-progress session
```

In production a scheduler (cron, Windows Task Scheduler or Celery Beat) would run this every
minute. Clients may also call `POST /api/sessions/{id}/bill/`, and ending a session always bills
the remaining full minutes.

---

## 5. Example walkthrough (PowerShell)

```powershell
$b = "http://127.0.0.1:8000"
Invoke-RestMethod -Method Post "$b/api/auth/register/" -Body @{username="drsharma"; password="Str0ngPass!"; role="PROVIDER"; per_minute_rate="50"}
Invoke-RestMethod -Method Post "$b/api/auth/register/" -Body @{username="riya"; password="Str0ngPass!"; role="USER"}
$pt = (Invoke-RestMethod -Method Post "$b/api/auth/token/" -Body @{username="drsharma"; password="Str0ngPass!"}).token
$ut = (Invoke-RestMethod -Method Post "$b/api/auth/token/" -Body @{username="riya"; password="Str0ngPass!"}).token
$U = @{Authorization="Token $ut"}; $P = @{Authorization="Token $pt"}

$ref = (Invoke-RestMethod -Method Post "$b/api/wallet/recharge/" -Headers $U -Body @{amount="500"}).reference
Invoke-RestMethod -Method Post "$b/api/wallet/recharge/callback/" -Headers @{"X-Webhook-Secret"="dev-webhook-secret"} -Body @{reference=$ref; status="success"}

$me  = Invoke-RestMethod "$b/api/auth/me/" -Headers $P
$sid = (Invoke-RestMethod -Method Post "$b/api/sessions/" -Headers $U).id
Invoke-RestMethod -Method Post "$b/api/sessions/$sid/assign/" -Headers $U -Body @{provider_id=$me.id}
Invoke-RestMethod -Method Post "$b/api/sessions/$sid/accept/" -Headers $P
Invoke-RestMethod -Method Post "$b/api/sessions/$sid/start/"  -Headers $U
# ...wait 2+ minutes...
Invoke-RestMethod -Method Post "$b/api/sessions/$sid/bill/"   -Headers $U
Invoke-RestMethod -Method Post "$b/api/sessions/$sid/end/"    -Headers $U
Invoke-RestMethod "$b/api/wallet/" -Headers $U
```

---

## 6. Project layout

```
config/          settings, root URLs
accounts/        custom User (role, per_minute_rate), register/token/me, role permissions
common/          DomainError hierarchy + DRF exception handler (→ 400/403/404)
wallet/          Wallet, WalletTransaction (ledger), RechargeTransaction; credit/debit + webhook services
consultations/   ConsultationSession, BillingRecord, state machine, session + billing services,
                 bill_active_sessions management command
docs/            diagrams and design notes
```
