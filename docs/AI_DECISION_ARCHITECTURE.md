# Local AI Decision Architecture

## Objective

The organizer should maximize useful cleanup while making the probability of an
important message being proposed for deletion extremely small. An LLM is one
signal in that decision, not the safety boundary and not a replacement for mail
protocol evidence.

## Decision pipeline

### 1. Deterministic evidence extraction

Extract and normalize information before any model call:

- decoded sender, subject, dates, folder, size, flags, and thread/reply signals;
- List-Unsubscribe and mailing-list headers;
- MIME structure, attachment names, and attachment types;
- authentication results (SPF, DKIM, and DMARC) when available;
- sender/domain frequency, first/last seen dates, and user interaction history;
- transaction, account, security, registration, support, legal, health, travel,
  marketplace-conversation, and payment indicators.

Untrusted mail text is always data. It can never alter the classifier prompt or
request actions.

### 2. Semantic grouping

Exact subjects are insufficient: campaigns frequently vary IDs, dates, names,
and encoded words. Use normalized subjects plus local multilingual embeddings to
cluster semantically equivalent mail. Keep sender/domain boundaries unless the
model supplies strong evidence that two identities belong to one service.

Recommended embedding model: `qwen3-embedding:0.6b`. It is small enough to run
alongside the classifier and is intended for multilingual clustering and text
classification.

### 3. Hard safety policy

Rules have authority over the model when they protect mail. The following never
become deletion candidates solely from an LLM decision:

- registrations, activations, verification, account access/recovery, and
  security changes;
- invoices, receipts, orders, contracts, payments, tax, insurance, and legal or
  medical mail;
- support cases, refunds, cancellations, appointments, bookings, and active
  subscriptions;
- personal replies and marketplace conversations;
- messages with attachments unless a separate attachment-aware review approves
  them;
- recent groups or groups whose newest message is inside the configured age
  threshold.

Phrase matching must be token-aware. For example, `aktion` must not match
`transaktion`, `angebot` must not match `Angebotsende`, and `sale` must not match
`aftersales`.

### 4. Qwen contextual classification

Qwen receives structured evidence for a group and returns schema-constrained
JSON. It must classify the mail's purpose, importance, suggested action,
confidence, and a concise evidence-based reason. The taxonomy is explicit:

- protected: account, finance, health, legal, marketplace, order, personal,
  security, subscription, support, and travel;
- reviewable: notification, promotion, system, spam, and other.

The prompt includes positive and negative examples from regression tests. It
states that no-reply senders are not inherently disposable and that verification
language is normal in legitimate account mail.

### 5. Risk-aware second pass

Metadata-only classification is sufficient for obvious campaigns. Ambiguous or
high-impact decisions receive a second local pass containing a sanitized text
preview and selected headers. The second pass may only make the outcome safer:
it can change Trash to Archive/Keep or Archive to Keep, never promote an
uncertain message to deletion.

### 6. Decision fusion

Combine rules, Qwen, authentication, sender history, age, attachments, and user
feedback. Recommended action gates:

- Keep: any hard protection or unresolved contradiction;
- Archive review: confidence at least 0.90 and no hard protection;
- Trash review: confidence at least 0.95, automated/campaign evidence, newest
  message older than the threshold, no protected content, and explicit approval;
- automatic action: only an account-specific rule previously approved by the
  user. Permanent deletion is never an AI action.

### 7. Explainability and feedback

Every row should show the decisive evidence, which stage made the decision, and
why a safer alternative was rejected. User corrections become account-local
feedback:

- Always keep this sender/pattern;
- Treat as promotion;
- Move to a selected folder;
- Never suggest Trash for this service.

Feedback creates deterministic local policy first. It is also copied into an
anonymous local evaluation set, never committed to Git.

## Model strategy for a 16 GB GPU

Use a two-tier setup:

1. `qwen3.5:9b-q8_0` for primary structured classification. It is approximately
   11 GB and should fit a 16 GB GPU with the deliberately small classification
   batches used by this application.
2. The same model with richer evidence for ambiguous second-pass reviews. This
   avoids keeping two large models resident.

The existing `qwen3.5:9b-q4_K_M` remains the fast mode. A 27B Q4 model is about
17 GB before runtime/KV-cache overhead, so it will not fit completely in 16 GB
VRAM and is not recommended for the always-on service. `qwen3:14b-q4_K_M` is a
viable benchmark candidate at about 9.3 GB, but should replace Qwen 3.5 only if
it wins on the mailbox-specific evaluation set.

## Evaluation and release gate

Maintain a local, account-specific golden set sampled from every category and
action. Measure precision separately for Keep, Archive, Trash, and Phishing.
The release gate is asymmetric:

- zero known protected messages in Trash candidates;
- at least 98% precision for Trash suggestions on the reviewed golden set;
- no decrease in protected-category recall;
- stable structured-output parsing and deterministic results at temperature 0;
- regression tests for every corrected failure pattern.

Deploy a new prompt, rule set, or model only after it passes the same golden set.
Retain the previous decision version so results can be compared and rolled back.
