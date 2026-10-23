# Diagrams

GitHub renders the Mermaid blocks below as diagrams.

## Session state machine

```mermaid
stateDiagram-v2
    [*] --> unassigned : USER creates
    unassigned --> assigned : assign (owner picks provider)
    assigned --> accepted_by_provider : accept (assigned provider)
    accepted_by_provider --> in_progress : start (owner, balance ≥ 5 × rate, rate locked)
    in_progress --> completed : end by user / provider (remaining minutes billed)
    in_progress --> completed : system end (can't cover next minute)
    unassigned --> cancelled : cancel
    assigned --> cancelled : cancel
    accepted_by_provider --> cancelled : cancel
    completed --> [*]
    cancelled --> [*]
```

Any other action returns **HTTP 400 `invalid_transition`**. The whole table lives in
`consultations/state_machine.py`:

| Action | Allowed from | Moves to |
|---|---|---|
| `assign` | `unassigned` | `assigned` |
| `accept` | `assigned` | `accepted_by_provider` |
| `start` | `accepted_by_provider` | `in_progress` |
| `end` (user, provider or system) | `in_progress` | `completed` |
| `cancel` | `unassigned`, `assigned`, `accepted_by_provider` | `cancelled` |

A completed session records `ended_by` (`user` / `provider` / `system`) and `end_reason`
(`user_ended` / `provider_ended` / `insufficient_balance`).

## Recharge lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending : USER initiates
    pending --> success : webhook "success" → wallet credited once
    pending --> failed : webhook "failed"
    success --> success : duplicate webhook → no-op (200, already_processed)
    failed --> failed : any later webhook → no-op
```

## Entity-relationship diagram

```mermaid
erDiagram
    USER ||--o| WALLET : "has (USER role only)"
    USER ||--o{ RECHARGE_TRANSACTION : initiates
    WALLET ||--o{ WALLET_TRANSACTION : "ledger entries"
    USER ||--o{ CONSULTATION_SESSION : "books (as user)"
    USER |o--o{ CONSULTATION_SESSION : "serves (as provider)"
    CONSULTATION_SESSION ||--o{ BILLING_RECORD : "one per billed minute"

    USER {
        int id PK
        string username
        string role "USER | PROVIDER"
        decimal per_minute_rate "providers only"
    }
    WALLET {
        int id PK
        int user_id FK "unique"
        decimal balance "CHECK >= 0"
        datetime updated_at
    }
    WALLET_TRANSACTION {
        int id PK
        int wallet_id FK
        string kind "CREDIT | DEBIT"
        decimal amount "CHECK > 0"
        decimal balance_after
        string reason "recharge | session_billing"
        string reference "UNIQUE with kind (if not empty)"
        datetime created_at
    }
    RECHARGE_TRANSACTION {
        int id PK
        int user_id FK
        decimal amount "CHECK > 0"
        string reference "UNIQUE, RCH-uuid"
        string status "pending | success | failed"
        datetime created_at
        datetime completed_at
    }
    CONSULTATION_SESSION {
        int id PK
        int user_id FK
        int provider_id FK "nullable"
        string status "partial UNIQUE(user) where in_progress"
        decimal per_minute_rate "snapshot at start"
        datetime started_at
        datetime ended_at
        int billed_minutes "billing bookmark"
        decimal billed_amount
        int talk_seconds "actual talk time"
        string ended_by "user | provider | system"
        string end_reason
    }
    BILLING_RECORD {
        int id PK
        int session_id FK
        int minute_number "UNIQUE with session"
        decimal amount
        datetime created_at
    }
```

## Billing sequence (one `bill` call)

```mermaid
sequenceDiagram
    participant C as Client / cron
    participant S as bill_session
    participant DB as Database
    C->>S: POST /sessions/{id}/bill/
    S->>DB: BEGIN transaction, lock session row (SELECT FOR UPDATE)
    S->>S: elapsed = floor((now − started_at) / 60s)
    loop each unbilled minute up to elapsed
        S->>DB: lock wallet, debit rate (refused if balance is less than rate)
        S->>DB: insert BillingRecord(session, minute), unique per minute
        S->>S: billed_minutes += 1
    end
    alt a minute could not be paid, or balance is less than rate
        S->>DB: status=completed, ended_by=system, end_reason=insufficient_balance
    end
    S->>DB: COMMIT
    S-->>C: session (billed_minutes, billed_amount, status)
```
