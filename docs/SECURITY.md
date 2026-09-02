# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security-advisory reporting flow when it is enabled for this repository. Include the
affected version, impact, and anonymized reproduction steps. Never attach a real
mailbox database, exported message, credential, token, address, or message content.

Maintainers should acknowledge a complete report within seven days and coordinate a
fix and disclosure timeline according to severity. This is a volunteer project and
does not currently offer a bug bounty.

## Supported versions

Security fixes are applied to the latest `main` branch and the latest published
release. Older snapshots are not supported.

## Security guarantees

- The API binds to loopback by default.
- Credentials and OAuth token caches use the operating-system credential manager.
- Repository configuration never accepts or contains real mailbox secrets.
- Scans are read-only and use IMAP peek operations.
- Qwen cannot directly call mailbox, filesystem, archive, unsubscribe, or network
  mutation tools.
- Normal deletion moves explicitly selected messages to the provider Trash folder.
- Permanent removal is isolated to **Empty Trash**, shows the affected count, and
  requires typed confirmation.
- Logs must not contain message bodies, subjects, addresses, tokens, or attachment
  names.

## Future action lifecycle

Actions progress through `proposed`, `approved`, `executed`, and `verified` states.
Only explicitly selected messages can be moved to the provider Trash folder.
Sensitive mail, replies, starred mail, messages with protected attachments, and
low-confidence classifications are excluded from automatic deletion. Empty Trash is
a separate, deliberate operation and is never initiated by the model or background
filing agent.

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
