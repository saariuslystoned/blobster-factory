<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/banner-dark.webp">
    <source media="(prefers-color-scheme: light)" srcset=".github/assets/banner-light.webp">
    <img alt="Blobster Factory — Forge the brain. Sculpt the shell. Open-source workshop, CLI pack compiler, and starter templates for OpenClaw agents." src=".github/assets/banner-dark.webp" width="100%">
  </picture>

  <p>
    <img alt="OpenClaw Template Schema: v1" src="https://img.shields.io/badge/OpenClaw%20Template%20Schema-v1-4CC38A?style=flat-square&labelColor=171F1B">
    <img alt="Core Builder Duo: Smith + Molt" src="https://img.shields.io/badge/builder%20duo-Smith%20%2B%20Molt-E6A23C?style=flat-square&labelColor=171F1B">
    <img alt="Avatar Pack: Tier 1 SVG + 3D GIF & Tier 2 Pet Rig" src="https://img.shields.io/badge/avatar%20pack-24px%20SVG%20%2B%203D%20GIF-38BDF8?style=flat-square&labelColor=171F1B">
    <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-24583C?style=flat-square&labelColor=171F1B">
  </p>

  <p>
    <a href="#the-builder-duo">The Builder Duo</a> ·
    <a href="#two-tier-blobster-pack-architecture">2-Tier Avatar Pack</a> ·
    <a href="#quick-start">Quick Start</a> ·
    <a href="#repository-layout">Repository Layout</a> ·
    <a href="#verification">Verification</a>
  </p>
</div>

---

# Blobster Factory (`blobster-factory`)

An open-source workshop, deterministic asset compiler, template linter, and starter template collection for **[OpenClaw](https://github.com/openclaw) Agent Templates** (`CLAW.md`, `package.json`, `profiles/openclaw.yml`, and `workspace/`).

Every OpenClaw agent needs two halves that fit together cleanly:
1. **The Brain (`Blobster Smith`)** — A solo-install-ready, schema-validated `CLAW.md` manifest, bounded `profiles/openclaw.yml` tool allowlists, `AGENTS.md` / `SOUL.md` / `TOOLS.md` / `HEARTBEAT.md` bootstrap files, skills, quiet-on-clean 5-field cron routines, draft-first human gates, and zero-secret linting.
2. **The Shell (`Blobster Sculptor / Molt`)** — A character identity that reads unmistakably at `24×24` pixels in any OpenClaw sidebar (`avatars/blobster.svg`) **and** comes alive as a 3D soft-touch vinyl collectible (`avatars/hero-512.png`, single-frame `avatars/sprite-2x2.png`, and `#FF00FF` chroma-keyed transparent looping `blobster-idle.gif` & `blobster-wave.gif`), verified by an automated dark/light QA contact sheet.

---

## The Builder Duo

`blobster-factory` ships with its two founding craftsman templates under [`templates/`](templates/), ready to load on any local OpenClaw install (`Settings -> Labs -> Templates` or `Pages -> Templates`):

<table>
  <thead>
    <tr>
      <th width="140">Animated GIF</th>
      <th width="110">24px SVG</th>
      <th width="140">3D Vinyl Hero</th>
      <th>Template &amp; Role</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="center">
        <img src="https://github.com/saariuslystoned/blobster-factory/releases/download/v0.1.0-assets/blobster-smith-idle.gif" width="112" alt="Blobster Smith Animated Idle GIF">
      </td>
      <td align="center">
        <img src="templates/blobster-smith/workspace/avatars/blobster.svg" width="72" alt="Blobster Smith 24px Layered OpenClaw SVG">
      </td>
      <td align="center">
        <img src="templates/blobster-smith/workspace/avatars/hero-512.png" width="112" alt="Blobster Smith 3D Vinyl Render">
      </td>
      <td>
        <strong><a href="templates/blobster-smith/CLAW.md">Blobster Smith</a> (<code>blobster-smith</code>)</strong><br>
        <em>Archetype: <code>C1 · Anvil Forgemaster</code></em><br><br>
        Forges complete, solo-first OpenClaw Agent Templates across three starting modes: <strong>(1) Idea</strong> (one clear job per bot, with optional 2–3 bot splits), <strong>(2) Past Session</strong> (turns a messy working transcript/folder into a sanitized 6-part <code>SKILL.md</code> + template), and <strong>(3) API/CLI</strong> (agent-native CLI &amp; <code>mcpServers</code> wrapper with <code>"${ENV_VAR}"</code> placeholders and live read preflights). Runs <code>lint_claw_template.py</code> before handoff.
      </td>
    </tr>
    <tr>
      <td align="center">
        <img src="https://github.com/saariuslystoned/blobster-factory/releases/download/v0.1.0-assets/blobster-sculptor-idle.gif" width="112" alt="Blobster Sculptor (Molt) Animated Idle GIF">
      </td>
      <td align="center">
        <img src="templates/blobster-sculptor/workspace/avatars/blobster.svg" width="72" alt="Blobster Sculptor 24px Layered OpenClaw SVG">
      </td>
      <td align="center">
        <img src="templates/blobster-sculptor/workspace/avatars/hero-512.png" width="112" alt="Blobster Sculptor 3D Vinyl Render">
      </td>
      <td>
        <strong><a href="templates/blobster-sculptor/CLAW.md">Blobster Sculptor · Molt</a> (<code>blobster-sculptor</code>)</strong><br>
        <em>Archetype: <code>C5 · Blueprint Toymaker &amp; Painter</code></em><br><br>
        Designs, surgically refines, and compiles the agent's visual identity across both formats: OpenClaw's native 5-layer <code>256×256</code> (<code>viewBox="-12 -18 144 144"</code>) vector avatar (<code>avatars/blobster.svg</code>) and the 3D soft-touch vinyl hero + <code>#FF00FF</code> chroma-keyed transparent looping GIF pack, verified on dark and light surfaces via an automated <code>qa-contact-sheet.png</code>.
      </td>
    </tr>
  </tbody>
</table>

---

## Two-Tier Blobster Pack Architecture

Every character built in the workshop follows a structured two-tier visual pipeline (`scripts/compile_blobster_pack.py`):

| Tier | Target Use Case | Generated Artifacts | Budget & QA Gates |
| --- | --- | --- | --- |
| **Tier 1 · Fast Pack** *(Default)* | Every OpenClaw Agent Template & ClawHub listing | 1. `avatars/blobster-design.json` + `avatars/blobster.svg` (`256×256`, `viewBox="-12 -18 144 144"`)<br>2. `avatars/hero-512.png` (`512×512` 3D studio vinyl render)<br>3. `avatars/sprite-2x2.png` (`512×512` single-frame despilled `2×2` sheet) + `avatars/cutout-256.png`<br>4. Hydrated `blobster-idle.gif` & `blobster-wave.gif` (`compile_blobster_pack.py gifs`) + external `qa-contact-sheet.png` | Fixed OpenClaw lobster silhouette (`BODY`, `LEFT`, `RIGHT`, eyes at `(45,32)` & `(75,32)`), empty `back` layer, `<= 24` custom vector shapes, `0` border-clip px, `<= 1.5%` `#FF00FF` spill, `< 2 MiB` per file |
| **Tier 2 · Full Pet Rig** *(Optional `--tier2`)* | Desktop / Sidebar interactive pet hosts | 3-sheet `4×4` `#FF00FF` animation pack (`16` states, `73` frames) compiled into a `1536×2288` RGBA `sprite.png` + `manifest.json` (`sprite_version: 2`) | `256×286` per cell (`6×8` grid) + turnaround & expression sheets |

---

## Quick Start

### 1. Load a Template in OpenClaw

1. In OpenClaw, enable **Settings -> Labs -> Templates** (or open **Pages -> Templates** at `/templates`).
2. Point OpenClaw at either template package directory:
   - [`templates/blobster-smith`](templates/blobster-smith)
   - [`templates/blobster-sculptor`](templates/blobster-sculptor)
3. Or export any configured agent from your OpenClaw agent list via **`⋯` -> `Create Template`** and let **Blobster Smith** + **Molt** sanitize, lint, and package it under `templates/<agent-id>/`.

### 2. Compile a Tier 1 Visual Pack + QA Contact Sheet

```bash
python3 scripts/compile_blobster_pack.py tier1 \
  --design templates/<agent-id>/workspace/avatars/blobster-design.json \
  --hero <work-dir>/hero.png \
  --sheet <work-dir>/chromakey-2x2.png \
  --out-dir templates/<agent-id>/workspace/avatars \
  --omit-gifs \
  --qa-out <proof-dir>/<agent-id>-qa-contact-sheet.png

# Materialize blobster-idle.gif & blobster-wave.gif into dist/avatars/<agent-id>/:
python3 scripts/compile_blobster_pack.py gifs --all-templates
```

---

## Repository Layout

```text
blobster-factory/
├── .github/assets/
│   ├── banner-dark.webp              # 1600x900 (16:9) Obsidian Telemetry Bench hero banner
│   ├── banner-light.webp             # 1600x900 (16:9) Specimen Drawer Workbench hero banner
│   └── social-preview.png            # 1280x640 (2:1) GitHub Social Preview (< 1 MiB)
├── scripts/
│   ├── compile_blobster_pack.py      # OpenClaw SVG + #FF00FF 2x2 GIF compiler + dark/light QA contact sheet
│   ├── lint_claw_template.py         # Zero-exclusion OpenClaw schema, secret scrub & trust-habit linter
│   └── verify_blobster_factory.py    # End-to-end template linter, avatar QA, and GitHub asset verifier
├── skills/
│   └── blobster-factory/SKILL.md     # Portable skill for agent harnesses
└── templates/
    ├── blobster-smith/               # C1 · Anvil Forgemaster (OpenClaw Agent Template)
    │   ├── package.json              # { name, version, license, openclaw: { template: "CLAW.md" } }
    │   ├── CLAW.md                   # schemaVersion: 1 manifest
    │   ├── profiles/openclaw.yml     # Bounded coding tool allowlist + sandbox + heartbeat
    │   └── workspace/                # AGENTS.md, SOUL.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md, avatars/, skills/
    └── blobster-sculptor/            # C5 · Blueprint Toymaker & Painter / Molt (OpenClaw Agent Template)
        ├── package.json
        ├── CLAW.md
        ├── profiles/openclaw.yml
        └── workspace/
```

---

## Verification

Run the zero-dependency linter, visual QA audit, and repository verifier:

```bash
python3 scripts/lint_claw_template.py --json
python3 scripts/compile_blobster_pack.py qa --avatars-dir templates/blobster-smith/workspace/avatars
python3 scripts/verify_blobster_factory.py
```

## License

MIT. OpenClaw base Blobster vector silhouette (`BODY`, `LEFT`, `RIGHT`) in [`scripts/compile_blobster_pack.py`](scripts/compile_blobster_pack.py) retains its upstream `MIT © 2026 OpenClaw Foundation` notice.
