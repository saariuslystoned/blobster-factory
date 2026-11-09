# Blobster Sculptor (Molt) — Tool Policy (`TOOLS.md`)

## Allowed Capabilities

- **Image Generation & Direct Visual Inspection (`image_generate`, `view_image`)**: Renders `1:1` 3D studio vinyl hero concepts and `2×2` `#FF00FF` chroma-key animation sheets using the Generate-vs-Surgical-Edit rubric, then inspects the compiled cutouts, GIF loops, and QA contact sheets.
- **Pack Compilation & QA (`exec`, `write`, `edit`)**: Runs the bundled `python3 scripts/compile_blobster_pack.py` (`svg` uses Python 3 stdlib only; `tier1`, `gifs`, and `qa` use `Pillow>=10.0` — verify with `python3 -c "import PIL"` or install via `python3 -m pip install "Pillow>=10.0"`), plus `python3 scripts/lint_claw_template.py` when co-located in a workshop repo with `blobster-smith`.

## Guardrails

- Save exact generation and surgical-edit prompts alongside working renders in your scratch/work directory (never inside `templates/<id>/workspace/avatars/`, which must keep zero unlisted files).
- Always generate and visually inspect a `qa-contact-sheet.png` (`0` border-clip pixels, `<= 1.5%` `#FF00FF` magenta fringe, `< 20` bold SVG shapes) before marking a character pack complete.
- Never embed secrets or machine-local home paths in template files.
