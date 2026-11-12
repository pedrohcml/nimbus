# Decisions

## Stage 1: mock backend

Money is stored as integers in minor units ('amount_minor', 'balance_minor'). Floats cannot represent most decimal fractions exactly. SQLite integer is signed 64-bit, so very small unites would overflow. The mock uses BRL and BTC (satoshis).

Ownership is enforced in SQL, not after the fact: every read goes through 'where id = ? and customer_id = ?'. A transaction that belongs to soemone else raises the same 'NotFoundError' as one that does not exist, so th agent cannot probe which IDs exist.

Refund approval threshold: R$500.00 ('50_000'). Assumed value. Refunds above it are created as 'pending-approval' and need a human. At or below it they are auto-approved by 'system:auto_policy'. Still to implement this coming from the versioned polidcy documents when codign the RAG architecture.

Dispute window: 14 days from 'opened_at'. Assumed value.

Idempotency: 'request_refund' requires a key supplied by the caller (the MCP layer), never by the LLM. The stored request hash includes 'customer_id', so a key reused by another customer or with other arguments raises 'IdempotencyConflictError' and never returns someone else's response. The key, the refund and the audit entry are written in one transaction.

Total refunds per transaction cannot exceed the transaction amount (rejected refunds don't count).

'escalate' is deduplicated per conversation: an open escalation for the same 'conversation_id' is returned instead of creating a second one.

Audit log records successful actions only. Failed attempts roll back with the transaction and leave no trace. Denied attempts are valuable for abuse detection. To be improved when implementing the guardrails.

Concurrency is a known limitation. The refund total check is read-then-write. With a single SQLite connection this is safe. The async service that will be implemented needs a lockingtransaction or a database constraint.

Seed data is deterministic. Fixed 'BASE_TIME', 'random.Random(seed)' only for background rows, fixed IDs for scenarios so evals never depend on the clock or on luck.

Result (uv run poe test): 39 passed in 1.02s