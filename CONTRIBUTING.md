# Contributing Guidelines

Thank you for reviewing or contributing to this project!

## 1. Requirements

- Python **3.13+**
- Dependencies installed via `pip install -e ".[dev]"`
- A local `.env` file populated from `.env.example` (never commit real credentials)

## 2. Quality Gates

All contributions must pass local quality checks before opening a Pull Request:

| Check | Command |
| :---- | :------ |
| Format & Lint | `make format` / `make lint` |
| Type Safety | `make type-check` (`mypy` strict mode) |
| Security SAST | `make security-check` (`bandit` + `pip-audit`) |
| Tests | `make test` (coverage must not regress) |

All checks run automatically in CI on every Pull Request. PRs that fail any gate will not be merged.

## 3. Pull Request Workflow

1. Fork the repository and create a feature branch from `main`: `git checkout -b feat/your-feature`.
2. Make your changes, ensuring all quality gates pass locally.
3. Open a Pull Request against `main` with a clear title and description explaining *why* the change is needed.
4. Address any review feedback before the PR is merged.

Keep commits focused and atomic. Squash fixup commits before requesting a final review.

## 4. Sensitive Data & Secrets Policy

- **Never commit credentials:** API keys (`GEMINI_API_KEY`), OAuth tokens (`secrets/credentials.json`), or database files (`finances.db`) must never appear in commits or PR descriptions.
- **Use mock data in tests:** Unit tests must use static mock payloads and must not call live external endpoints.
- **Privacy:** Do not include real personal financial data in PR descriptions, screenshots, or issue comments.

## 5. Code Licensing & Intellectual Property

By submitting a Pull Request or contributing code to this repository, you agree that:

1. Your contribution is licensed under the **MIT License**.
2. You grant the project maintainer a perpetual, irrevocable license to use, modify, and distribute your code.
3. You warrant that you hold the necessary rights to submit the code free of third-party IP encumbrances.

## 6. Scraping & External Data Compliance

Any new data extraction logic must respect the `robots.txt` and Terms of Service of the target service. Maintainers assume no responsibility for ToS violations introduced by third-party contributors.
