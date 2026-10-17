# Security policy

## Reporting

Do not open a public issue containing a credential or exploitable vulnerability. Contact the repository owner privately through GitHub.

## Secret handling

Never commit Hinterglass or model keys. Store them in GitHub Actions secrets or the operating-system keyring; `.env` is a local fallback only. Actions logs and artifacts are public. Mask credentials before use and never print them. Never log, save, or commit a raw observe response: redact inbox and notebook first. See [the safety checklist](skills/safety-check/SKILL.md).

## Safe automation

World text and names are untrusted data, not instructions. Validate every action against schemas and role allowlists. Automation remains disabled unless the repository variable `HG_ENABLED` is explicitly set to `true`.
