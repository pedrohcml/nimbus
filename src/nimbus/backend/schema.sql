create table customers (
    id text primary key,
    full_name text not null,
    email text not null,
    country text not null,
    kyc_status text not null check (kyc_status in ('pending', 'verified', 'rejected')),
    created_at text not null
);

create table wallets (
    id text primary key,
    customer_id text not null references customers(id),
    asset text not null,
    balance_minor integer not null check (balance_minor >= 0),
    unique (customer_id, asset)
);

create table transactions (
    id text primary key,
    customer_id text not null references customers(id),
    wallet_id text not null references wallets(id),
    type text not null check (type in ('deposit', 'withdrawal', 'trade', 'fee', 'card_charge')),
    asset text not null,
    amount_minor integer not null,
    fee_minor integer not null default 0,
    status text not null check (status in ('pending', 'confirming', 'completed', 'failed', 'reversed')),
    network text,
    tx_hash text,
    confirmations integer,
    required_confirmations integer,
    counterparty_memo text,
    created_at text not null,
    updated_at text not null
);

create index idx_transactions_customer on transactions(customer_id, created_at);

create table disputes (
    id text primary key,
    customer_id text not null references customers(id),
    transaction_id text not null references transactions(id),
    reason_code text not null check (reason_code in ('unauthorized', 'duplicate', 'not_received', 'wrong_amount', 'other')),
    status text not null check (status in ('open', 'under_review', 'resolved_customer', 'resolved_exchange', 'rejected')),
    opened_at text not null,
    due_at text not null,
    unique (transaction_id)
);

create table refund_requests (
    id text primary key,
    customer_id text not null references customers(id),
    transaction_id text not null references transactions(id),
    dispute_id text references disputes(id),
    amount_minor integer not null check (amount_minor > 0),
    asset text not null,
    status text not null check (status in ('pending_approval', 'approved', 'rejected', 'executed')),
    requires_approval integer not null check (requires_approval in (0, 1)),
    approved_by text,
    decided_at text,
    created_at text not null
);

create table idempotency_keys (
    key text primary key,
    tool_name text not null,
    request_hash text not null,
    response_json text not null,
    created_at text not null
);

create table escalations (
    id text primary key,
    conversation_id text not null,
    customer_id text not null references customers(id),
    reason text not null,
    status text not null check (status in ('open', 'assigned', 'closed')),
    created_at text not null
);

create table audit_log (
    id integer primary key autoincrement,
    ts text not null,
    actor text not null check (actor in ('agent', 'human', 'system')),
    conversation_id text,
    customer_id text,
    tool_name text not null,
    args_json text not null,
    result_status text not null
);

create table policy_documents (
    id text primary key,
    title text not null,
    version integer not null,
    effective_from text not null,
    effective_to text,
    content_hash text not null
);

create table escalation_notes (
    id integer primary key autoincrement,
    escalation_id text not null references escalations(id),
    note text not null,
    created_at text not null
);