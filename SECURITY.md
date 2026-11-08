# Security

Brighty runs locally with the current user's permissions. It uses private macOS interfaces and sends DDC commands to a display. It does not need sudo, collect telemetry, or use the network during normal operation.

Do not commit or attach display state, real UUIDs/serial numbers, credentials, or complete system-setting exports to public issues. Use synthetic IDs and redact local paths in diagnostics.

For sensitive reports, use the repository's **Security → Advisories → Report a vulnerability** feature if private reporting is enabled. If unavailable, open a minimal issue requesting a private reporting channel without disclosing exploit details or private information. No response-time guarantee or formally supported release branch is currently defined.
