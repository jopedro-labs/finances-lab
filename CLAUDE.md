# Agent Instructions & Development Guidelines

This document outlines the mandatory operating procedures, coding standards, and quality gates that AI agents and assistants must follow when working in the **Finances** repository.

---

## 1. Working Approach & Interaction Protocol

- **Read Before Editing**: Always read the relevant files and understand surrounding context before editing.
- **Visual Diff & Step-by-Step Approvals**: Before writing or changing any code, use the Edit tool directly so the diff is visible in the file — make one change at a time and wait for approval before proceeding to the next.
- **Small, Safe Steps**: Prefer small, safe, and easy-to-review changes.
- **Preserve Existing Style**: Maintain consistency with the existing code style across the project.
- **No Unannounced API Changes**: Do not change public APIs, schemas, or CLI command signatures without confirmation first.
- **Constructive Critical Thinking**: Do not default to passive agreement. Challenge the user when a decision seems wrong, incomplete, or when a better solution exists — even if the user seems confident. Explain your reasoning and the risks clearly.
- **Explain Before Acting**: Before applying any code change, explain the proposed solution and the reasoning behind it. Wait for explicit user approval before proceeding. Once approved, show the diff first, then apply it.
- **Impact & Realistic Planning**: Prioritize highest-impact tasks and keep implementation plans realistic.
- **No Destructive Operations**: Never overwrite or delete configuration files, SQLite databases (`finances.db`), or credentials (`.env`, `secrets/`) without explicit user instruction.
- **No Direct Commits/PRs to Main**: AI agents are strictly prohibited from performing git commits or opening Pull Requests targeting the `main` branch. All branch merges and commits to `main` must be performed exclusively by the user.
- **Never Open Pull Requests**: AI agents must never create Pull Requests under any circumstances. Repository management — including PR creation, review, and merging — is handled exclusively by the user.
- **Always Edit Code Directly**: Never use worktrees. Always make code changes directly in the working directory. The `.claude/settings.json` must always contain `"worktree": {"bgIsolation": "none"}` to allow direct edits in background sessions.

---

## 2. Quality & Validation

- **Flag Risks & Edge Cases**: Proactively identify and flag risks, boundary conditions, and edge cases.
- **Behavior Preservation**: Validate that changes do not break existing behavior before finalizing them.
- **No Assumptions**: Ask for clarification rather than making assumptions about ambiguous requirements.
- **Makefile Quality Validation**: After any code changes, always run the quality verification targets via the project `Makefile`:
  ```bash
  # Linting & Formatting checks (Black, Ruff, Mypy)
  make lint

  # Security SAST scan & vulnerability audit (Bandit, Pip-Audit)
  make security-check

  # Unit tests and branch coverage verification (Pytest)
  make test

  # Full quality pipeline (combines lint, security, and test)
  make quality
  ```

---

## 3. Code Conventions & Standards

- **Python Version**: `>= 3.13`
- **Docstrings**: When writing or changing code, always validate and update the docstrings (PEP 257 / Google style) of the modified function or class before applying other changes.
- **Explicit Type Annotations**: Every newly created variable, function argument, and return type must include an explicit type annotation (strict Mypy compliance).
- **Readability Over Cleverness**: Prefer explicit and readable code over clever, compact, or obfuscated solutions.
- **Architecture Separation**:
  - `src/cli/` & `main.py`: Presentation layer using Typer & Rich.
  - `src/core/`: Domain models, opportunity evaluation strategies, exposure audit, analytics.
  - `src/infra/`: Database (SQLite), AI client (Gemini), Cloud SSoT (Google Drive), Scrapers (JustETF), Notifications (Discord).
  - `src/utils/`: Chart generators, badge creation, logging.
- **Configuration & Secrets**:
  - Centralized in `src/config.py` using `pydantic-settings`.
  - Always update `.env.example` whenever a new configuration variable is introduced.
  - Keep `data/` and `secrets/` strictly ignored by Git.

---

## 4. Communication Guidelines

- Keep explanations concise, clear, and structured.
- Format all file references and code symbols as clickable Markdown links (e.g. `[main.py](file:///path/to/main.py)` or `[Asset](file:///path/to/src/core/models.py)`).
- Respond in European Portuguese when addressed in Portuguese.

<!-- Guidelines last reviewed: 2026-09-02 -->
