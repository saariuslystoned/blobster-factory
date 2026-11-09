# Blobster Factory v1 — Verification Proof (`PROOF.md`)

## Scope

Initial v1 release of `blobster-factory`:

1. **Dual-Theme GitHub Front Door (`.github/assets/`, `README.md`)**:
   - `1600x900` dark (`banner-dark.webp`) and light (`banner-light.webp`) hero banners wired via `<picture>` in `README.md` + `1280x640` `social-preview.png` (`< 1 MiB`).
2. **OpenClaw Blobster Pack Compiler & Visual QA (`scripts/compile_blobster_pack.py`)**:
   - Compiles OpenClaw-compliant `256x256` (`viewBox="-12 -18 144 144"`) 5-layer vector avatars (`avatars/blobster.svg`), `512x512` 3D vinyl renders (`avatars/hero-512.png`), and `#FF00FF` chroma-keyed looping GIF89a packs (`avatars/blobster-idle.gif`, `avatars/blobster-wave.gif`, `avatars/cutout-256.png`).
   - Renders `1280x760` dark/light QA contact sheets (`tier1 --qa-out` and `qa --avatars-dir --out`) checking `24px` chat pills + `4x` pixel loupe, `64px` sidebar cards, `256px` safe-frame border clipping (`0 px` required), `#FF00FF` residual fringe spill (`<= 1.50%`), custom SVG shape count (`<= 24`), and `< 2 MiB` file budgets.
3. **Zero-Exclusion OpenClaw Template & Safety Linter (`scripts/lint_claw_template.py`)**:
   - Validates `package.json` (`openclaw.template === "CLAW.md"`, exact semver, zero lifecycle `scripts`), `CLAW.md` (`schemaVersion: 1`, no body + `SOUL.md` collision, confined workspace sources, `"${ENV_VAR}"` MCP placeholders, 5-field cron schedules), `profiles/openclaw.yml` (`workspaceOnly: true`, bounded non-wildcard tool allowlists), zero unlisted files (`excludedPaths == []`), secret/private-path scrubbing, draft-first approval gates, untrusted input boundaries, and quiet-on-clean / honest-failure scheduled jobs.
4. **Core Builder Duo (`templates/blobster-smith/`, `templates/blobster-sculptor/`)**:
   - **Blobster Smith (`blobster-smith`)**: Solo/local-first OpenClaw template architect supporting 3 modes (**Idea**, **Past Session**, and **API/CLI** with agent-native CLI ergonomics).
   - **Blobster Sculptor / Molt (`blobster-sculptor`)**: OpenClaw character designer and animator with the **Fresh-Generate vs. Surgical-Edit** prompt rubric and automated QA contact-sheet workflow.

## Reproducible Verification

```bash
python3 scripts/lint_claw_template.py --json
python3 scripts/compile_blobster_pack.py qa --avatars-dir templates/blobster-smith/workspace/avatars
python3 scripts/compile_blobster_pack.py qa --avatars-dir templates/blobster-sculptor/workspace/avatars
python3 scripts/verify_blobster_factory.py
```

### Measured Telemetry

| Template | Selected Files | Excluded Paths | Custom SVG Shapes | Max `#FF00FF` Spill | Border-Clip Pixels | `idle.gif` / `wave.gif` / `hero-512.png` | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `blobster-smith` | `16` | `[]` | `12` (`<= 24`) | `0.70%` (`<= 1.50%`) | `0 px` | `78.9 KB` / `81.4 KB` / `392.1 KB` | `PASS` |
| `blobster-sculptor` | `16` | `[]` | `14` (`<= 24`) | `0.17%` (`<= 1.50%`) | `0 px` | `74.3 KB` / `72.8 KB` / `356.8 KB` | `PASS` |

- Negative lint & QA suite verified deterministic `exit 1` rejection across all 11 lint error codes (`project_scripts_forbidden`, `mcp_env_must_be_placeholder`, `unlisted_excluded_files`, `secret_detected`, `private_path_detected`, `missing_draft_first_gate`, `missing_untrusted_input_boundary`, `cron_missing_quiet_on_clean`, `cron_missing_stale_refusal`, `heartbeat_missing_quiet_on_clean`, `heartbeat_missing_stale_refusal`) plus outer-border clipping and `> 1.50%` `#FF00FF` fringe spill.
