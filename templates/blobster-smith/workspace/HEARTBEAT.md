# Blobster Smith — Heartbeat Routine (`HEARTBEAT.md`)

On each scheduled heartbeat or weekly audit (`forge-manifest-audit`):

1. Scan `templates/*/` in the workspace for OpenClaw Agent Template packages.
2. Run `python3 scripts/lint_claw_template.py --json` and `python3 scripts/verify_blobster_factory.py` to verify:
   - `package.json` compliance (`openclaw.template === "CLAW.md"`, zero `scripts`, exact semver).
   - `CLAW.md` schema, zero unlisted/excluded files (`excludedPaths == []`), secret/private-path scrub, and avatar `< 2 MiB` bounds.
   - `profiles/openclaw.yml` bounded tool allowlists (`workspaceOnly: true`) and the 4 safety habits (`AGENTS.md` draft-first + untrusted input boundary, quiet-on-clean + honest cron reporting).
3. Stay silent when clean and all templates pass with zero issues. Only announce when a template fails validation; if a verifier command itself errors out, report explicit check failure rather than reusing stale results.
