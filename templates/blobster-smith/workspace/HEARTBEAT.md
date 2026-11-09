# Blobster Smith — Heartbeat Routine (`HEARTBEAT.md`)

On each scheduled heartbeat or weekly audit (`forge-manifest-audit`):

1. Run the bundled template linter `python3 scripts/lint_claw_template.py --json --allow-empty` against `templates/*/` (and run `python3 scripts/verify_blobster_factory.py` when present in a workshop repository):
   - `package.json` compliance (`openclaw.template === "CLAW.md"`, zero `scripts`, exact semver).
   - `CLAW.md` schema, 5-field cron ranges/steps/IANA timezones, zero unlisted/excluded files (`excludedPaths == []`), credential-file/secret/private-path scrub, and avatar `< 2 MiB` bounds.
   - `profiles/openclaw.yml` bounded tool allowlists (`workspaceOnly: true`) and the 4 safety habits (`AGENTS.md` draft-first + untrusted input boundary, quiet-on-clean + honest cron reporting).
2. Stay silent when clean (or when no local `templates/*/` exist yet) and all templates pass with zero issues. Only announce when a template fails validation; if a verifier command itself errors out, report explicit check failure rather than reusing stale results.
