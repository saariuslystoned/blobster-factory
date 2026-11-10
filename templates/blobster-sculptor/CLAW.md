---
schemaVersion: 1
agent:
  id: "blobster-sculptor"
  name: "Blobster Sculptor"
  description: "Master Toymaker & Painter (Molt) who crafts 24px-legible OpenClaw layered SVGs, surgical 3D vinyl toy renders, #FF00FF chroma-keyed sprites & Codex Pets GIF packs, and automated QA contact sheets."
  identity:
    name: "Blobster Sculptor (Molt)"
    theme: "cyan"
    emoji: "🎨"
    avatar: "avatars/blobster.svg"
categories:
  - "product"
  - "engineering"
  - "productivity"
metadata:
  factory.archetype: "C5 · Blueprint Toymaker & Painter"
  factory.nickname: "Molt"
  factory.tier: "tier-1"
  factory.companion: "blobster-smith"
workspace:
  bootstrapFiles:
    AGENTS.md:
      source: "workspace/AGENTS.md"
    SOUL.md:
      source: "workspace/SOUL.md"
    IDENTITY.md:
      source: "workspace/IDENTITY.md"
    TOOLS.md:
      source: "workspace/TOOLS.md"
  files:
    - source: "assets/icon.png"
      path: "assets/icon.png"
    - source: "workspace/avatars/blobster.svg"
      path: "avatars/blobster.svg"
    - source: "workspace/avatars/blobster-design.json"
      path: "avatars/blobster-design.json"
    - source: "workspace/avatars/hero-512.png"
      path: "avatars/hero-512.png"
    - source: "workspace/avatars/sprite-2x2.png"
      path: "avatars/sprite-2x2.png"
    - source: "workspace/avatars/cutout-256.png"
      path: "avatars/cutout-256.png"
    - source: "workspace/scripts/compile_blobster_pack.py"
      path: "scripts/compile_blobster_pack.py"
    - source: "workspace/skills/sculpt-blobster/SKILL.md"
      path: "skills/sculpt-blobster/SKILL.md"
cronJobs:
  - id: "avatar-pack-gallery-check"
    name: "Daily Avatar Pack Budget, Spill & Clipping QA Audit"
    schedule:
      cron: "30 9 * * 1-5"
      timezone: "America/New_York"
    session: "isolated"
    message: "Run python3 scripts/compile_blobster_pack.py qa --avatars-dir avatars (plus any templates/*/workspace/avatars/ folders or scripts/verify_blobster_factory.py when present in a workshop repository) to verify 256x256 viewBox='-12 -18 144 144' SVG compliance, non-empty synchronized foregrounds, zero border-clipped frames, <=1.5% #FF00FF fringe spill, and <1 MiB template / <2 MiB GIF budgets. Stay silent when clean and all packs pass; report explicit check or dependency failure rather than reusing stale data."
    delivery:
      mode: "announce"
      channel: "last"
---
