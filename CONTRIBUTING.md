# Contributing

Thank you for improving Local Mail Organizer. Contributions should preserve its core
principles: local processing, explicit approval for mailbox mutations, strict account
isolation, and safe failure behavior.

## Before opening an issue

- Search existing issues first.
- Reproduce the problem with a non-critical mailbox or synthetic fixtures.
- Remove real addresses, names, subjects, message bodies, attachment names, paths,
  credentials, tokens, identifiers, and screenshots containing private data.
- Report security vulnerabilities using the process in `docs/SECURITY.md`, not a
  public issue.

## Development setup

Follow the installation steps in `README.md`, then run the quality suite:

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\pytest.exe -q
npm run lint
npm run build
```

## Pull requests

1. Keep changes focused and explain the user-visible outcome.
2. Add or update tests for behavioral changes.
3. Use reserved domains such as `example.com`, `example.invalid`, or `.example` in
   fixtures. Never copy a real mailbox example into the repository.
4. Keep AI output advisory. Authentication signals and deterministic protection
   rules must remain authoritative.
5. Do not add automatic permanent deletion or bypass explicit approval flows.
6. Update documentation when configuration or provider behavior changes.

By contributing, you agree that your contribution may be distributed under the
PolyForm Noncommercial License 1.0.0. A contribution does not grant users a
commercial license.
