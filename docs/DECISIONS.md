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



## Stage 2: mcp server

SDK: MCP Python SDK v2. Business rules stay in services. server.py only reads the session, calls services, translates errors and shapes the output. If the SDK API changes, only server.py changes.

Identity comes from the session and never from the model. customer_id and conversation_id are read from the environment when the server starts and kept in a frozen Session created in the lifespan. Tools receive it through the injected Context, which is not part of the input schema. A test asserts that no tool accepts customer_id, conversation_id or idempotency_key.

The server refuses to start without NIMBUS_CUSTOMER_ID, with a customer that doesnt exist, or with a missing database file (sqlite3 would silently create an empty one). ConfigError is for operatios and is never shown to the model.

Outputs are explicit Pydantic views (TransactionView, DisputeView, RefundView, EscalationView) tjat leave out internal IDs such as customer_id and wallet_id.

ServiceError subclasses become ToolError, so the model sees the message and can correct itself. ANy other exception reaches the client only as a generic message. The traceback stays in the server log. Invalid arguments are rejected by the SDK from the schema before any services run.

Idempotency key derived by the server from conversation, tool name and arguments. Repeating a call in the same conversation returns the same refund. Trade-off: two legitimate refunds with the same amount on the same transaction in the conversation collapse into one.

Split-refund bypass fixed in services: approval now compares the total already requested for the transaction plus the new amount against the threshold, so two small requests cannot avoid human review.

Duplicated reason list is guarded by a test. DisputeReason in server.py and DISPUTE_REASONS in services.py must match. The test caught a typo (wrongs_amount) that had blocked wrong_amount disputes since stage 1.

Tools are async def and run on the event loop thread, which avoids SQLite's same-thread restriction. SQLite calls block the loop briefly which is acceptable for a single stdio session. To be revisited.

Tool descriptions are yet to be upgraded. They explain minor unites, saying that counterparty_memo is data, forbid claiming a pending refund was paidand ask for a neutral escalation summary. Real guardrails will come in future development.

Local tooling note: the inspector didnt pass terminal environment variables to the server and had issues with my directory that has an accentuated character. Working command: 'npx @modelcontextprotocol/inspector -e NIMBUS_CUSTOMER_ID=cust_pedro -e NIMBUS_DB_PATH=C:\nimbus-data\nimbus.db uv run python -m nimbus.mcp_server.app'.

Result (uv run poe test): 71 passed in 2.95s