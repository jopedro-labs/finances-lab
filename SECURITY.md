# Security Policy

## Supported Versions

The following versions of **Finances Portfolio Tracker & Opportunity Engine** are currently receiving security updates:

| Version | Supported          |
| :------ | :----------------- |
| 0.7.x   | :white_check_mark: |
| < 0.7.0 | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, credential leak, or policy flaw within this repository:

1. **Do NOT create a public GitHub issue.**
2. Send a private security report directly to **João Pedro** ([@JoPedro15](https://github.com/JoPedro15)) via GitHub's [private vulnerability reporting](https://github.com/jopedro-labs/finances-lab/security/advisories/new).
3. Include the following in your report:
   - Detailed steps to reproduce the vulnerability
   - Affected components and file paths
   - Potential impact and severity assessment
   - Any proof-of-concept code (if applicable)

### Expected Response Timeline

| Stage                  | Target         |
| :--------------------- | :------------- |
| Initial acknowledgment | Within 48 hours |
| Triage & status update | Within 5 business days |
| Fix & patch release    | Within 14 business days (severity-dependent) |

## Built-in Security Controls

This repository enforces automated security scanning on every push:

- **SAST Analysis:** Static code scanning with `bandit` (`make security-check`).
- **Dependency Auditing:** CVE checks against known vulnerability databases via `pip-audit`.
- **Secrets Protection:** `.env`, `secrets/credentials.json`, and `secrets/token.json` are excluded from source control via `.gitignore`. Never commit credentials.

## User Responsibility

You are solely responsible for protecting your `GEMINI_API_KEY`, Google Cloud OAuth credentials, and Discord webhook URLs. The author is not liable for financial loss or unauthorized access resulting from leaked secrets or improper local configuration.
