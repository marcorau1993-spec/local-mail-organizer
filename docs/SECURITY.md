# Security model

## Non-negotiable guarantees for version 1

- Mail access is read-only.
- Permanent deletion is unavailable, even if `DRY_RUN=false` is supplied.
- The API binds to loopback by default.
- Secrets are never accepted through source-controlled configuration.
- Logs must not contain message bodies, subjects, addresses, tokens, or attachment names.

## Future action lifecycle

Actions progress through `proposed`, `approved`, `executed`, and `verified` states. Only explicitly selected messages can be moved to the provider Trash folder, and the app exposes no permanent expunge operation. Sensitive mail, replies, starred mail, messages with protected attachments, and low-confidence classifications are excluded from automatic deletion.

## Archive safety

Local and NAS paths must resolve beneath an explicitly configured archive root. Exports use temporary files, atomic rename where supported, SHA-256 verification, collision-safe names, and a manifest containing opaque identifiers rather than mail metadata. Cloud adapters are optional and isolated behind the same transaction contract.

## Local inventory database

The resumable inventory database is stored only under the ignored `data/` directory. It contains message headers and therefore must be treated as private even though it never enters Git. SQLite uses WAL mode, foreign keys, unique `(job, folder, UID)` keys, prepared parameters, and indexes derived from actual grouping and progress queries. Public builds contain only the schema in source form.

## Threats considered

- Prompt injection inside mail content
- Malicious unsubscribe links and tracking URLs
- Credential leakage through logs or Git
- Archive path traversal and unsafe network shares
- Partial exports followed by premature deletion
- Model hallucination or malformed structured output
- IMAP race conditions and provider-specific folder semantics

## Model isolation and prompt injection

Mail fields are serialized as JSON between explicit untrusted-data delimiters. The system prompt forbids following instructions from those fields, Ollama structured output is constrained with a generated JSON schema, and Pydantic rejects malformed or additional fields. Model failure produces a protected manual-review result. Deterministic policy then overrides the model for protected categories and low confidence. The model has no mail, filesystem, network, archive, unsubscribe, or deletion tools.
