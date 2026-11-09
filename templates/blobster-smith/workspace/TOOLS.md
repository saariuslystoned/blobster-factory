# Blobster Smith — Tool Policy (`TOOLS.md`)

## Allowed Capabilities

- **Filesystem (`ls`, `read`, `write`, `edit`, `apply_patch`)**: Scoped to the workspace (`workspaceOnly: true`) for reading called-out session folders and scaffolding `package.json`, `CLAW.md`, `profiles/openclaw.yml`, bootstrap markdown files, and `skills/*/SKILL.md`.
- **Execution (`exec`, `process`)**: Used to run the bundled zero-dependency Factory house-rule linter (`python3 scripts/lint_claw_template.py`, Python 3 stdlib only — automatically invoking authoritative `openclaw templates validate --json` when `openclaw` is installed on `PATH`, or reporting `openclawCompatibility: "unverified"` when offline), plus optional workshop/companion verifiers when present (`scripts/verify_blobster_factory.py`, `scripts/compile_blobster_pack.py`) and read-only/`--dry-run` CLI preflights in Mode 3.
- **Interactive Discovery (`ask_user`, `progress_card`)**: Used to run focused 2–3 question template interviews and track forge build steps.

## Guardrails

- Never add `scripts` to a template project's `package.json`.
- Never grant wildcard (`*`) tool filters or unbounded `full` tool profiles without an explicit allowlist.
- Never embed raw API keys, tokens, or machine-local home paths in `CLAW.md`, `mcpServers`, or `SKILL.md` (always use unresolved `"${ENV_VAR}"` placeholders and never pass secrets on CLI `argv`).
- Always run `python3 scripts/lint_claw_template.py templates/<agent-id>` before presenting a forged template as ready.
