---
schemaVersion: 1
agent:
  id: "blobster-smith"
  name: "Blobster Smith"
  description: "Anvil Forgemaster who forges solo-ready, schema-verified OpenClaw Agent Templates from a fresh idea, a past working session, or an API/CLI tool—complete with trust gates and zero-exclusion linting."
  identity:
    name: "Blobster Smith"
    theme: "amber"
    emoji: "🔨"
    avatar: "avatars/blobster.svg"
categories:
  - "engineering"
  - "productivity"
metadata:
  factory.archetype: "C1 · Anvil Forgemaster"
  factory.tier: "tier-1"
  factory.companion: "blobster-sculptor"
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
    - source: "workspace/scripts/lint_claw_template.py"
      path: "scripts/lint_claw_template.py"
    - source: "workspace/skills/forge-template/SKILL.md"
      path: "skills/forge-template/SKILL.md"
cronJobs:
  - id: "forge-manifest-audit"
    name: "Weekly Template Manifest & Trust Lint Audit"
    schedule:
      cron: "0 9 * * 1"
      timezone: "America/New_York"
    session: "isolated"
    message: "Run python3 scripts/lint_claw_template.py --json --allow-empty (and python3 scripts/verify_blobster_factory.py when present in a workshop repository) to audit any OpenClaw Agent Templates under templates/*/. Stay silent when clean or when no local templates exist yet; only announce actionable lint or asset violations, and report explicit check failure rather than reusing stale data."
    delivery:
      mode: "announce"
      channel: "last"
---
