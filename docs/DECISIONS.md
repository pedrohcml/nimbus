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



## Stage 6: RAG

**Corpus**
- Policies are markdown files with a YAML header containing id, title, version and effective_from. Markdown gives the headings that section chunking uses. The header gives versions.
- Versions matter because the right answer depends on the date. The refund policy has v1 (auto-approval up to R$ 300.00) and v2 (R$ 500.00, plus dispute block). in_effect picks, for each policy, the version with the latest effective_from that already started.
- Tests keep the documents in sync with the backend. The refund threshold, the dispute window and the delay limits are written in both places, and test fails if they differ.
- The FAQ was written from the backend rules with every answer traceable to a constant or check.
- Six distractor policies (identity verification, limits, card, trading, deposits and account closure) were added to give retrieval near misses, such as the withdrawal limit next to the refund approval limit.
- Markdown instead of PDF for now as PDF extraction loses structure and adds noise, and measuring retrieval and extraction at the same time would mix two causes.

**Chunking**
- Two strategies were developed and tested: chunking per section (by heading), and fixed windows of 60 words with 15 of overlap.
- Every chunk records the sections it covers, so both strategies are scored with the same labels (policy and section) and not chunk IDs.
- The document title is prepended to every chunk, so a chunk like "up to R$ 500.00 is approved automatically" still says it is about refunds.
- All versions are chunked. the date filter happens at search time.

**Measuring retrieval**
- Metrics like recall@k (if the correct chunk is amongst the first k results) and MRR (1 divided by the position of the 1st correct result). Retrieval is measured without any LLM, so it costs no token usage quota.
- The first eval set (25 questions) became too easy once dense retrieval was added. recall@3 was 1.00 for both chunkings methods, so it could not compare variants anymore.
- The second set (61 questions, being 46 in english and 15 in portuguese) adds exact terms, short queries, confusing neighbors, realistic messages and dates. Each question qccepts any of several answers due to the FAQ repeating policy rules.
- rag-eval --misses lists what came first when rank 1 was wrong. Most decisions below came from that list and not from the averages.
- With 61 questions, a difference of 1 or 2 questions can be considered noise. No weight or threshold was tuned on this set to avoid fitting the ruler.

**Results (61 questions)**
**Variant                   | recall@1 | recall@3 | recall@5 | MRR**
BM25, section               | 0.36     | 0.54     | 0.59     | 0.45
BM25, window                | 0.49     | 0.61     | 0.64     | 0.55
Pinecone, section           | 0.85     | 0.93     | 0.98     | 0.90
Pinecone, window            | 0.82     | 0.95     | 0.98     | 0.89
RRF, section                | 0.70     | 0.87     | 0.90     | 0.78
RRF, window                 | 0.75     | 0.89     | 0.92     | 0.83
Pinecone + rerank, section  | 0.87     | 0.97     | 0.97     | 0.91

- BM25 compares words, so Portuguese questions against an English corpus failed almost completely. Without stopword removal, question-shaped FAQ chunks matched unrelated questions through words like "can", "I" and "my", and queries with no shared word returned the same arbitrary chunks in corpus order. spaCy stopwords (keeping negations) and dropping zero-score results made BM25 more of an honest method, as it cannot return anything it cannot match.
- Pinecone (multilingual-e5-large, embedded by Pinecone) solved Portuguese. From 0.07 to 1.00 recall@5.
- Hybrid search with reciprocal rank fusion was worse than POinecone alone. With equal weights, any wrong BM25 result that also appears anywhere in Pinecone's top 20 outranks Pinecone's first result. It fixed 1 question and broke 10. Did not use weighted fusion, because weighting each of the 61 questions individually with fit the ruler. Kept in the code but not used by the agent.
- Reranking with bge-reranker-v2-m3 fixed 3 near-miss questions, broke 2 and could be considered a tie with Pinecone alone. It costs one more call per search on a quota of 500 rerank requests a month. Kept in the code but not used by the agent.
- Section and window chunking tie with Pinecone, but section was kept. Better recall@1 in Portuguese and chunks with a complete meaning are better to cite. Window chunks that mix sections usually became generic results for unrelated questions.

**Pinecone**
- In this project, a managed vector database is more than enough for a corpus of only 12 documents, but it was chosen to show the integration with a production tool.
- Pinecone embeds the text itself, so no local model or PyTorch had to be installed on th work computer.
- One namespace poer chunking. The versionfilter is a metadata filter on policy_version, computed from the versions in effect.
- Ingestion is a separate command. Documents become searchable a few seconds after upsert and the DOcuments API has no count to wait on, so ingestion waits a fixed 10 seconds.

**search_policies tool**
- The tool lives in the MCP server next to the others and takes a Retriever, so the server does not know it is Pinecone.
- The search date comes from the session clock, not from the model.
- The model always gets 5 passages. It started at 3, but a manual test missed the spread rule at 3, and recall@5 is 0.98 against 0.93 at 3.
- Pinecone's SDK is synchronous and calls the network, so the search runs in a worker thread to keep the server responsive. Failures reach the model as a clean error that suggests escalating.
- The tool is always registered, so the tools the model sees always match the prompt.

**Agent eval with prompt 9.0**
- Language: 5 of 5, including a conversation that switches from Portuguese to English.
- Policy, prompt 9.0: 3 of 6. One real failure: Asked for a balance, the agent declined but did not say where to find it. Two failures were the ruler: The model wrote "30 minutes" with a narrow no-break space which the regex did not match, and a correct Portuguese answer quoted English policy text, which tipped the language detector. Answers are now normalized with NFKC before pattern checks, and the new prompt 10.0 tells the model not to quote policies in another language.
- Policy, prompt 10.0: 6 of 6. One run of 6 cases shows the fixes work, not that the rate is 100%.
- A Portuguese answer wrote the field name "delayed". No automatic check can catch it without false positives in English answers. It will be assessed later.


Result (uv run poe test): 223 passed in 4.04s