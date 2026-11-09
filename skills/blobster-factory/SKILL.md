---
name: blobster-factory
description: Create, crystallize, style, compile, and lint solo-ready OpenClaw Agent Templates and two-tier Blobster character packs (24px layered OpenClaw SVG + 3D vinyl hero + #FF00FF chroma-key looping GIFs + dark/light QA contact sheets + optional 73-frame sprite_version 2 pet rig).
---

# Blobster Factory (`blobster-factory`)

Open-source workshop for designing, compiling, linting, and verifying **OpenClaw Agent Templates** (`CLAW.md` + `package.json` + `profiles/openclaw.yml` + `workspace/`) and their **Blobster** character packs.

## Core Builder Duo

| Template | ID | Archetype | Responsibility |
| --- | --- | --- | --- |
| **Blobster Smith** | `blobster-smith` | `C1 · Anvil Forgemaster` | Forges complete, solo-install-ready OpenClaw Agent Templates across 3 modes (**Idea**, **Past Session**, **API/CLI** with agent-native CLI design) and enforces `lint_claw_template.py` trust & secret gates. |
| **Blobster Sculptor (Molt)** | `blobster-sculptor` | `C5 · Blueprint Toymaker & Painter` | Crafts the two-tier visual pack using the **Generate-vs-Surgical-Edit** prompt rubric: `24px`-legible layered OpenClaw SVG (`avatars/blobster.svg`), `512×512` 3D vinyl hero (`avatars/hero-512.png`), `#FF00FF` chroma-keyed looping GIFs (`avatars/blobster-idle.gif`, `avatars/blobster-wave.gif`), and dark/light `qa-contact-sheet.png` verification. |

## Commands

### 1. Compile a Tier 1 Blobster Pack (+ Visual QA Contact Sheet)

```bash
python3 scripts/compile_blobster_pack.py tier1 \
  --design templates/<agent-id>/workspace/avatars/blobster-design.json \
  --hero <work-dir>/hero.png \
  --sheet <work-dir>/chromakey-2x2.png \
  --out-dir templates/<agent-id>/workspace/avatars \
  --qa-out <proof-dir>/<agent-id>-qa-contact-sheet.png
```

Audit an existing `avatars/` directory and render its QA sheet without recompiling assets:

```bash
python3 scripts/compile_blobster_pack.py qa \
  --avatars-dir templates/<agent-id>/workspace/avatars \
  --out <proof-dir>/<agent-id>-qa-contact-sheet.png
```

### 2. Lint OpenClaw Template Schema, Zero-Exclusion & Trust Habits

```bash
python3 scripts/lint_claw_template.py --json
```

### 3. Verify All Templates, Avatar QA & GitHub Front-Door Assets

```bash
python3 scripts/verify_blobster_factory.py
```
