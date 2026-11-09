---
name: sculpt-blobster
description: Design, surgically refine, compile, and QA-verify an OpenClaw Blobster visual pack — Tier 1 Fast Pack (24px layered SVG + 512x512 3D vinyl hero PNG + 2x2 #FF00FF chroma-key looping GIFs + automated dark/light QA contact sheet) and optional Tier 2 73-frame sprite_version 2 pet rig.
---

# Sculpt Blobster (`sculpt-blobster`)

Use this skill to craft, refine, compile, and visually verify the character pack for any **OpenClaw Agent Template**.

## Prompt Rubric: Fresh Generate vs. Surgical Edit

Never mix initial generation prompts with refinement prompts—save each prompt alongside its working image in your scratch/work folder and follow this split:

### 1. Fresh Generate (`1:1` 3D Hero or `2×2` `#FF00FF` Chroma Sheet)

Write **4–6 crisp sentences** covering:
1. **Character & Silhouette**: Lobster vinyl toy (`BODY` + claws + 1 bold hat/headpiece + 1–2 readable claw props), naming each material texture **once** (matte soft-touch vinyl, brushed brass, stitched leather, woven denim).
2. **Background Contract**:
   - **Hero (`1:1`)**: Clean neutral studio plinth with subtle contact shadow.
   - **Animation Sheet (`1:1`, `2×2` grid)**: `Idle A` (top-left), `Idle B` (top-right), `Wave/Action A` (bottom-left), `Wave/Action B` (bottom-right) on a **100% flat, unlit `#FF00FF` (`RGB 255, 0, 255`) background** with zero floor shadows, zero text labels, and zero divider lines.
3. **Clean Lighting**: Bright, even three-point studio key + rim light—explicitly avoid floating dust motes, chromatic aberration, color fringing, lens bloom, or crushed black shadows.
4. **Full-Body Margin**: Centered full-body framing with at least `8–10%` breathing room around tall hats, antennae, hammers, and brushes so nothing touches cell borders.

### 2. Surgical Edit (Fixing Prop Grips, Apron Text, Paint Split, or Fringe)

When an existing hero or `2×2` sheet is 90% right and needs a targeted fix:
1. **Lead with 1–3 concrete part-level replacements**: State the exact delta first (e.g., `"Replace the unlabeled resin blank in the left claw with a miniature lobster figurine painted glossy cyan (#38BDF8) on the upper half over white primer on the lower half"` or `"Reposition the left claw so its pincer wraps cleanly around the iron tong handles"`).
2. **Add 1 short anchor sentence**: Explicitly name the preserved camera angle, full-body crop, lighting, and untouched props (`"Preserve the three-quarter front camera angle, full-body centering, charred leather apron, and glowing amber hammer in the right claw."`).
3. **Hard Bans**:
   - **Never** write vague `"keep everything else the same"` instructions without naming the anchored pose/crop.
   - **Never** repaste the full 5-sentence generation prompt into an edit call (causes duplicate props, shifted scale, and muddied textures).

### 3. Pre-Render 5-Point Prompt Checklist

- [ ] Zero conflicting pose or lighting instructions.
- [ ] Every material/texture named once (no adjective stacking).
- [ ] Surgical edits contain `<= 3` concrete part deltas + `1` explicit anchor sentence.
- [ ] `2×2` sprite prompts forbid floor shadows, gradients, grid lines, and text on `#FF00FF`.
- [ ] `blobster-design.json` keeps `back: ""`, `< 20` bold vector shapes, and leaves eyes at `(45,32)` & `(75,32)` unobstructed.

## Tier 1: Compile & Run Deterministic Visual QA

1. **Author `templates/<id>/workspace/avatars/blobster-design.json`** (`version: 1`, `palette` 6-digit hex colors, 5 allowed SVG fragment layers).
2. **Compile the Pack + Emit QA Contact Sheet** (use `--omit-gifs` for Git-tracked `templates/<id>/workspace/avatars/` so Git tracks single-frame `sprite-2x2.png` + `cutout-256.png`, and keep `--qa-out` outside `templates/<id>/workspace/avatars/` so `CLAW.md` maintains zero unlisted files):
   ```bash
   python3 scripts/compile_blobster_pack.py tier1 \
     --design templates/<id>/workspace/avatars/blobster-design.json \
     --hero <work-dir>/hero.png \
     --sheet <work-dir>/chromakey-2x2.png \
     --out-dir templates/<id>/workspace/avatars \
     --omit-gifs \
     --qa-out <proof-dir>/<id>-qa-contact-sheet.png

   # Hydrate blobster-idle.gif & blobster-wave.gif from sprite-2x2.png into dist/avatars/<id>/:
   python3 scripts/compile_blobster_pack.py gifs --avatars-dir templates/<id>/workspace/avatars
   ```
   Or audit an existing avatar directory without recompiling assets:
   ```bash
   python3 scripts/compile_blobster_pack.py qa \
     --avatars-dir templates/<id>/workspace/avatars \
     --out <proof-dir>/<id>-qa-contact-sheet.png
   ```
3. **Inspect `<id>-qa-contact-sheet.png` Directly (`view_image`)**:
   - Confirm **`24px` chat pill** + `4×` pixel loupe silhouette legibility on both Dark (`#0D1117`) and Light (`#F8FAFC`) panels.
   - Confirm **`0` border-clipped pixels** across `cutout-256.png` and all GIF frames.
   - Confirm **`<= 1.5%` `#FF00FF` residual fringe spill** and `< 2 MiB` per shipped file.

## Tier 2: Optional Extended Pet Rig (`sprite_version: 2`)

When an agent is promoted to a desktop/sidebar interactive pet, generate the 3-sheet `4×4` `#FF00FF` animation pack (`16` states, `73` frames) and compile the `1536×2288` RGBA `sprite.png` + `manifest.json` (`sprite_version: 2`).
