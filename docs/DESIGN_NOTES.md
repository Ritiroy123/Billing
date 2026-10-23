# Design Notes

These are the decisions that matter most for correctness, with the alternatives considered.

## 1. Architecture: thin views, a service layer, domain errors

- Views only parse input, call a service and serialise the result. All business rules live in
  `wallet/services.py` and `consultations/services.py`, so money logic exists in exactly one place.
- Services raise typed `DomainError`s (`InvalidTransition`, `InsufficientBalance`, …). A custom
  DRF exception handler (`common/exceptions.py`) maps them to `{"error", "detail"}` with
  400/403/404, so views need no `try/except`.

## 2. Money

- **`Decimal(12, 2)` everywhere, never float.** Floats can't represent amounts like 0.1 exactly.
  DRF serialises decimals as strings, so clients don't turn them back into floats.
- **The balance can never be negative, enforced twice.** `debit()` refuses when `balance < amount`,
  and a database `CheckConstraint(balance >= 0)` is the last line of defence.
- **Ledger.** Every credit and debit writes a `WalletTransaction` with `balance_after` and a
  reference, so every rupee is auditable.

## 3. Concurrency: pessimistic locking

- Every wallet mutation and every session transition runs in `transaction.atomic()` and locks
  the row with `select_for_update()`. Two concurrent requests therefore can't both read the same
  stale balance or status.
- **Lock order is always session, then wallet**, to avoid deadlocks.
- I chose this over optimistic locking (a version column with retries) because it is simpler and
  always correct, and contention on a single wallet or session is low. On PostgreSQL these are
  real row locks. SQLite ignores `select_for_update` but serialises writers.

## 4. Session state machine

- One transition table (`consultations/state_machine.py`) maps each action to the statuses it is
  allowed from and the status it moves to. Every endpoint goes through `apply_transition()`,
  which raises `InvalidTransition` (→ 400).
- **Actions, not field updates.** Clients call `/accept/`, `/start/` and so on, and can never
  `PATCH` a status. Each action carries its own permission check and side effects.
- `cancelled` is separate from `completed`. Only sessions that never started can be cancelled,
  and a running session must be ended so that it gets billed.
- **One active session per user** is checked in code for a clear message and enforced by a
  partial unique index (`UNIQUE(user) WHERE status = 'in_progress'`) to cover races. The save
  sits in a savepoint so the `IntegrityError` can be turned into a 400.
- **Rate snapshot.** At start, the provider's current `per_minute_rate` is copied onto the
  session. Later price changes don't affect a running session.

## 5. Start rule

Starting needs `balance ≥ 5 × rate`. This is a gate, not a charge: nothing is debited at start.

## 6. Per-minute billing (idempotent)

- Billing is **calculated from time, not counted from calls**:
  `elapsed = floor((now − started_at) / 60s)`, and only minutes
  `billed_minutes + 1 … elapsed` are charged. `billed_minutes` acts as a bookmark.
  - Repeated or concurrent triggers in the same minute charge nothing more.
  - Missed triggers catch up on the next call.
- There are three guards against double charging. The bookmark is read under the session lock,
  `BillingRecord` has a unique `(session, minute_number)`, and the ledger has a unique
  `(kind, reference)` with references like `session-7-minute-2`.
- **Rounding:** only completed minutes are billed (floor), so a partial final minute is free.
  This matches "3 minutes = ₹150". Switching to ceiling is a one-line change.
- **Triggering:** `POST /sessions/{id}/bill/`, the `bill_active_sessions` management command for
  cron, and every `end` call, which bills the remainder. Because billing is idempotent, the
  triggers can be combined safely. Celery Beat would be the production choice.

## 7. Insufficient balance

Auto-end happens inside the billing routine, in the same locked transaction as the charges:

- If a minute can't be paid, billing stops immediately and the wallet never goes negative.
- After billing, if `balance < rate` (the next minute is unaffordable), the system ends the
  session: `status=completed`, `ended_by=system`, `end_reason=insufficient_balance`.
  Example: ₹290 at ₹50/min → 5 minutes billed → ₹40 left → session ended, wallet stays ₹40.
- Both `billed_minutes` (billable time) and `talk_seconds` (actual time) are persisted. They can
  differ when billing runs late.
- When a user or provider ends the session, the "next minute" check is skipped because there is
  no next minute. If unpaid minutes are found, it is still recorded as a system end, because the
  money genuinely ran out.

## 8. Mock recharge (idempotent webhook)

- Recharge happens in two phases. Initiating creates a `pending` `RechargeTransaction` with an
  unguessable `RCH-<uuid>` reference, and the gateway's webhook completes it.
- Gateways deliver webhooks at least once, so the callback locks the recharge and processes it
  **only while it is `pending`**. Duplicates return `200` with `already_processed: true` so the
  gateway stops retrying. `success` and `failed` are terminal.
- The credited amount always comes from our stored record, never from the callback payload.
- The webhook skips token auth and verifies a shared secret header with `hmac.compare_digest`
  (constant time). A real gateway would use an HMAC signature of the raw body.

## 9. Security

- `IsAuthenticated` is the global default, and endpoints are opened explicitly.
- Role permission classes (`IsUserRole`, `IsProviderRole`) check roles, and services check
  ownership.
- Querysets are scoped to the requesting user. The wallet is resolved from `request.user`, and
  sessions are filtered to participants, so other users' objects return 404 (no IDOR).
- `on_delete=PROTECT` on all financial relations, so history can't be cascade-deleted.

## 10. Known simplifications and next steps

- Anyone can register as a provider. In production providers would be verified or onboarded.
- The user picks the provider. Auto-matching by availability would be a natural extension.
- No reconciliation job yet. A periodic task should query the gateway for stale `pending`
  recharges, settle them through the same idempotent service, and expire very old ones.
- Webhook authentication uses a plain shared secret. Production would use an HMAC signature of
  the body, with the secret kept in an environment variable or a secrets manager.
- Tokens don't expire. JWT with short-lived access tokens, or token expiry, would be added.
- Users could be warned one minute before their balance runs out, which needs a push channel.
- Providers have no earnings or payout ledger.
