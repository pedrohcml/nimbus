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



## Stage 3: llm

The loop depends on an LLM protocol and neutral types ('Message', 'ToolCall', 'ToolSpec', 'LLMResponse'). Groq ('openai/gpt-oss-120b') is one adapter. Tests use a 'ScriptedLLM' so the loop is tested without network, cost or randomness.

The agent talks to the MCP server and never to the database, so stage 2 guarantees also apply.

Tool errors go back to the model as messages. Unknown tool names are answered with the list of real tools. A crashing tool returns a generic message. 'max_steps' stops loops with a fallback that offers a human. Provider errors are not caught in the loop.

Every turn produces JSON line events with timings. Reasoning is stored but never shown to the customer. Traces contain customer data, so it's kept out of git.

Manually evaluated the agent using 24 cases with 3 versions of the same prompt, each time fixing small parts of it until all 24 cases passed. v1 got 16 out of 24, v2 got 21 out of 24, and v3 also got 21 out of 24, but that's because in between v2 and v3 I forgot to reset the database, so junk data from v2 testing was left while testing v3. After reseting the database and rerunning the failing cases, all 3 passed.

**Thoughts about the first 3 rounds of manual testing:**
- Ambiguous instructions become errors ("never split a refund" was read as "no partial refunds"). State what is allowed and what is forbidden, and why.
- Tool descriptions are part of the prompt. An outdated 'escalate' description made the model skip escalating suspected fraud.
- Fixing the prompt can break cases that used to pass.
- Results vary between runs of the same prompt.
- A dirty database invalidated two cases. Each case needs a fresh database.
- Rules that matter belong in code: refunds only for 'card_charge' and 'fee', escalation notes so new information such as suspected fraud is never dropped.

Items that are stil open: Invented details in answers. Decide whether refunds are allowed while a dispute is open. Opaque IDs in eval data. Current date in the prompt. 'refunded_minor' in 'TransactionView'. Automatic check that every 'tx_' ID in an answer appeared in a tool result.

Result (uv run poe test): 95 passed in 5.88s



## stage 4: eval harness

Tool calls, tool arguments, final database state, regexes on the answer, plus automatic checks on every turn. The turn finished without hitting max_steps, every tx_ ID in the answer appeared earlier in the conversation (customer messages or tool results, never the model's own arguments), no internal names leak (amount_minor, pending_approval etc.), and the answer is in the expected language.

Each run is isolated and reproducible. Fresh in-memory database, fixed clock and session built from the case. A dirty database invalidated cases in stage 3.

Opaque scenatio IDs: Descriptive IDs ('tx_belongs_to_ricardo') biased the model. Seed IDs are now opaque, tests use named constants and the dataset uses placeholders resolved by the loader.

A misspeled key is an error instead of a disaled check. Unknown placeholders and duplicate case IDs are errors. DB checks must be 'select' queries as they wuote the IDs inline.

Cases that fixed when the agent acts or which words it uses failed for valid behavior (asking for confirmation, "2 of the required 3"). Cases now check effects wherever possible.

Runs end as passed, failed or error. Pass rate = passed / (passed + failed). Provider or harness errors are counted separately so a rate limit never looks like a worse agent. Each report records model, prompt hash and dataset, so results are only compared within the same prompt version.

Several runs per case (3 by default), becuase results may vary between runs.

Couldn't test everything until 100% due to rate limits from Groq. The free tier allows 200k tokens per day for GPT-OSS-120B, about one full suite.

Markdown summaries are commited as the history of results. JSON filed are ignored by git.

Known limits: The language check is a word-list heuristic. An example ID such as tx_123 is flagged as invented. Token usage is not recorded yet, so the cost of the suite is no more than an estimation.

Result (uv run poe test): 127 passed in 2.25s



## stage 5: langgraph agent and human confirmation

**Graph**
The agent loop was rewritten as a LangGraph 'StateGraph' with the nodes 'agent', 'tools', 'confirm', 'finish' and 'give_up', routed by conditional edges.

A checkpointer keeps each conversation's state under a thread_id, which is the conversation ID, so the chat and the eval runner no longer pass the history around. The old loop was deleted after its tests were ported to the graph.
- the stateholds plain dictionaries, not dataclasses, so checkpoints serialize without custom code.
- The system prompt is not stored in the state. It is rebuilt on every model call, so the date and time are always current.
- The trace grows in the state for the whole conversation, and each turn returns only its own events (filtered by turn_id). Fine for short chats but will be revisited in the future with a persistent checkpointer.

**Hard-coded confirmation process instead of relying on LLM**
Before open_dispute or request_refund runs, the 'confirm' node puses the graph with interrupt() and asks the customer.

- The question is built my code from the exact arguments that will run, so a wrong amount is visible before any money moves.
- The next customer message resumes the graph with Command(resume=...).
- Only an explicit yes with no negation counts. When in doubt, nothing runs.
- Before the interrupt the node only reads, because LangGraph runs the node again from the start when it resumes.
- The confirmation question stays out of the message history. Puting it between the model's tool call and the tool result would break the order the APIs require.
- A reply that does not confirm is added as a user message after the declined tool result. Without it, the model only saw "the customer did not confirm" and told customers who had just asked for the action in other words that they had not confirmed, as observed in today's eval run.
- A thread counts as oaused only when an interrupt is pending, not when any node is pending. After a provider error in the middle of a turn, the next message would otherwise be taken as a confirmation reply and lost.

In manual tests, the model asked "should I go ahead?" and then the system asked again. Both the prompt and two tool descriptions told the model to confirm before calling. Prompt version 5.0 and the tool descriptions now say to call the tool directly.

**Rules moved from the prompt to the server**
- "Pending for an unsually long time" was vague and needs time arithmetic, which models often get wrong. get_transaction now returns 'delayed': confirming for more than 2 hours, or pengind for more than 24 hours, since the time registered in created_at.
- get_transaction also returns refund_requested_minor and refundable_minor, computed with the same sum that request_refund enforces.


First eval run (prompt version 5.0): 84 runs, 12 errors (reached daily token limit, so the last 4 cases didnt run), 64 of 72 passed (89%). Lookup, score and security 100%, actions 67%, escalation 83%. the failures led to the reply-as-user-message fix, prompt version 6.0 and the dispute rule. Not comparable with stage 4, because the dataset and the checks changed.

Single failures left:
- One answer in Portuguese to an English message.
- One ID copied wrong in the final answer (‘tx_8c41e2a8’ instead of ‘tx_8c41e2a7’), caught by auto:grounded_ids.

The prompt already forbids both. the real fix for IDs is an output guardrail to be implemented in the future.

Result (uv run poe test): 165 passed in 3.41s