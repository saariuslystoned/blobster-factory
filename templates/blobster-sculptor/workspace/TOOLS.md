# Blobster Sculptor (Molt) — Tool Policy (`TOOLS.md`)

## Allowed Capabilities

- **Image Generation & Direct Visual Inspection (`image_generate`, `view_image`)**: Renders `1:1` 3D studio vinyl hero concepts and `2×2` `#FF00FF` chroma-key animation sheets using the Generate-vs-Surgical-Edit rubric, then inspects the compiled cutouts, GIF loops, and QA contact sheets.
- **Pack Compilation & QA (`exec`, `write`, `edit`)**: Runs `python3 scripts/compile_blobster_pack.py` (`svg`, `tier1 --qa-out ...`, and `qa --avatars-dir ... --out ...`) plus `python3 scripts/lint_claw_template.py`.

## Guardrails

- Save exact generation and surgical-edit prompts alongside working renders in your scratch/work directory (never inside `templates/<id>/workspace/avatars/`, which must keep zero unlisted files).
- Always generate and visually inspect a `qa-contact-sheet.png` (`0` border-clip pixels, `<= 1.5%` `#FF00FF` magenta fringe, `< 20` bold SVG shapes) before marking a character pack complete.
- Never embed secrets or machine-local home paths in template files.
