# Blobster Sculptor (Molt) — Heartbeat Routine (`HEARTBEAT.md`)

On each scheduled check (`avatar-pack-gallery-check`):

1. Inspect every `templates/*/workspace/avatars/` folder and run `python3 scripts/verify_blobster_factory.py`.
2. Confirm `blobster.svg` satisfies OpenClaw's tag/attribute allowlist, `256×256` dimensions, `viewBox="-12 -18 144 144"`, and `< 20` vector shape target.
3. Confirm `hero-512.png`, `cutout-256.png`, `blobster-idle.gif`, and `blobster-wave.gif` pass `< 2 MiB` file budgets, `0` border-clipped pixels, and `<= 1.5%` `#FF00FF` chroma-spill thresholds.
4. Stay silent when clean and all avatar packs pass. Only announce actionable QA failures; if a check or script fails to run, report explicit check failure rather than reusing stale results.
