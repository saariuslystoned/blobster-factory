# Blobster Factory v1 — Verification Proof (`PROOF.md`)

## Scope

Initial v1 release of `blobster-factory`:

1. **Dual-Theme GitHub Front Door (`.github/assets/`, `README.md`)**:
   - `1600x900` dark (`banner-dark.webp`) and light (`banner-light.webp`) hero banners wired via `<picture>` in `README.md` + `1280x640` `social-preview.png` (`< 1 MiB`).
   - Showcase animated GIFs hosted on immutable release tag `v0.1.0-assets` (`81ae11af8bd6f48e809e53c530aeaf9fd64056f4`):
     - `blobster-smith-idle.gif` (`80,829 B`, `sha256:673713da933d7dd71ec8c728eec0078e2ef9f4683dbb11ac2e7f9c3e45bf8c80`)
     - `blobster-smith-wave.gif` (`83,349 B`, `sha256:8ce631b17d65e9b423276b1d4d2aa4338ee43b92f35bcd4bc19dc38ae2ef1549`)
     - `blobster-sculptor-idle.gif` (`76,062 B`, `sha256:4a5cfa04934f2f519577c6de0ed3b0cdf4e8db9134bccc79e8bf7ccf558d7cb1`)
     - `blobster-sculptor-wave.gif` (`74,507 B`, `sha256:2884033c1c38760d34bcb58927ef61cfec16b0547386e624f6620c72be9aa263`)
2. **OpenClaw Blobster Pack Compiler & Visual QA (`scripts/compile_blobster_pack.py`)**:
   - Compiles OpenClaw-compliant `256x256` (`viewBox="-12 -18 144 144"`) 5-layer vector avatars (`avatars/blobster.svg` — the single live avatar rendered inside OpenClaw chat today, enforcing `blobster-design.json` <-> `blobster.svg` sync, non-empty foregrounds, `<= 24` custom vector shapes, strict `viewBox` & `BODY_PATH` bounds, `0 px` outer-border clipping, and `< 1 MiB` OpenClaw template managed-file budget), alongside `512x512` 3D vinyl renders (`avatars/hero-512.png`, `< 1 MiB`), single-frame `512x512` `2x2` RGBA animation sheets (`avatars/sprite-2x2.png`, `< 1 MiB`), `avatars/cutout-256.png` (`256x256`, `< 1 MiB`), and deterministic `#FF00FF` chroma-keyed looping GIF89a hydration (`compile_blobster_pack.py gifs` -> `blobster-idle.gif`, `blobster-wave.gif`, `< 2 MiB`) for GitHub/ClawHub READMEs, showcase cards, and external desktop-pet apps such as **Codex Pets**.
   - Renders `1280x760` dark/light QA contact sheets (`tier1 --qa-out` and `qa --avatars-dir --out`) with full compound `fill-rule` / `clip-rule` (`evenodd` & `nonzero`), `stroke-dasharray`, and `stroke-linecap` parity across `24px` chat pills + `4x` pixel loupe, `64px` sidebar cards, `256px` SVG & raster safe-frame border clipping (`0 px` required + `0` out-of-`viewBox` SVG shapes), `#FF00FF` residual fringe spill (`<= 1.50%`), custom SVG shape count (`<= 24`), and `< 1 MiB` template managed-file / `< 2 MiB` GIF budgets.
3. **Two-Layer OpenClaw CLI Bridge & Factory House-Rule Linter (`scripts/lint_claw_template.py`)**:
   - **Authoritative OpenClaw compatibility (`openclawCompatibility`)**: Automatically invokes native `openclaw templates validate <dir> --json` when `openclaw` is installed on `PATH` (`"verified"` / `"failed"`), or reports `"unverified"` honestly when `openclaw` is absent (`--require-openclaw` fails closed).
   - **Factory house rules (`factoryPolicyOk`)**: Establishes one confined, symlink-free regular-file inventory (`<= 1 MiB` per managed file, `<= 4 MiB` aggregate workspace sources, zero second disk rereads), strict block/flow YAML parsing (duplicate-key rejection across block/flow/list mappings, `#` preservation inside `|`/`>` block scalars, exact `type(schemaVersion) is int`), official 12-slug ClawHub `categories`, `SOUL.md` body/workspace collision detection (`bootstrapFiles` & `workspace.files`), pinned stdio/HTTPS remote `mcpServers` with `"${ENV_VAR}"` placeholders, Croner-compatible 5-field cron schedules, zero unlisted files (`excludedPaths == []`), and honest secret-pattern / policy-phrase heuristics.
4. **Core Builder Duo (`templates/blobster-smith/`, `templates/blobster-sculptor/`) & CI (`.github/workflows/ci.yml`)**:
   - **Blobster Smith (`blobster-smith`)**: Solo/local-first OpenClaw template architect supporting 3 modes (**Idea**, **Past Session**, and **API/CLI** with agent-native CLI ergonomics) with a single intentional Monday 09:00 `cronJobs` schedule (redundant 30-minute `HEARTBEAT.md` removed).
   - **Blobster Sculptor / Molt (`blobster-sculptor`)**: OpenClaw character designer and animator with the **Fresh-Generate vs. Surgical-Edit** prompt rubric, **Codex Pets** / showcase asset role documentation, and a single intentional Weekday 09:30 `cronJobs` QA audit.
   - **GitHub Actions CI (`.github/workflows/ci.yml`)**: Runs `lint_claw_template.py --json` and `verify_blobster_factory.py` (including negative schema/YAML/symlink/budget/drift fixtures) on every push and pull request.

## Reproducible Verification

```bash
python3 scripts/lint_claw_template.py --json
python3 scripts/compile_blobster_pack.py gifs --all-templates
python3 scripts/compile_blobster_pack.py qa --avatars-dir templates/blobster-smith/workspace/avatars
python3 scripts/compile_blobster_pack.py qa --avatars-dir templates/blobster-sculptor/workspace/avatars
python3 scripts/verify_blobster_factory.py
```

### Measured Telemetry

| Template | Selected Files | Excluded Paths | Custom SVG Shapes | Max `#FF00FF` Spill | Border-Clip Pixels | `sprite-2x2.png` / `idle.gif` / `wave.gif` / `hero-512.png` | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `blobster-smith` | `15` | `[]` | `12` (`<= 24`) | `0.81%` (`<= 1.50%`) | `0 px` | `278.9 KB` / `78.9 KB` / `81.4 KB` / `392.1 KB` | `PASS` |
| `blobster-sculptor` | `15` | `[]` | `14` (`<= 24`) | `0.17%` (`<= 1.50%`) | `0 px` | `252.6 KB` / `74.3 KB` / `72.8 KB` / `356.8 KB` | `PASS` |

- Standalone packaging verified: `blobster-smith` bundles canonical `scripts/lint_claw_template.py` (stdlib-only) and `blobster-sculptor` bundles canonical `scripts/compile_blobster_pack.py`, while `skills/blobster-factory` is explicitly documented as a repository-local workshop skill.
- Negative lint & QA suite (`scripts/verify_blobster_factory.py`) deterministically verifies rejection across duplicate YAML keys (block, flow, list-item), literal `#` preservation inside `|-` / `>-` block scalars vs trailing-newline rejection on `|`, `schemaVersion: true`, `packages: false`, `CLAW.md` body + `workspace.files` `SOUL.md` collision, symlinked `LICENSE`, invalid UTF-8 `AGENTS.md` without reread crashes, `> 1 MiB` managed files, unpinned/HTTP `mcpServers`, blank/drifted `blobster.svg`, `--gif-size 128` preserving `256x256` cutout + `512x512` sprite, and `--omit-gifs` removing stale `.gif` files.
