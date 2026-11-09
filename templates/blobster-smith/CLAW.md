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
    avatar: "avatars/blobster-idle.gif"
categories:
  - "developer-tools"
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
    HEARTBEAT.md:
      source: "workspace/HEARTBEAT.md"
  files:
    - source: "workspace/avatars/blobster.svg"
      path: "avatars/blobster.svg"
    - source: "workspace/avatars/blobster-design.json"
      path: "avatars/blobster-design.json"
    - source: "workspace/avatars/hero-512.png"
      path: "avatars/hero-512.png"
    - source: "workspace/avatars/blobster-idle.gif"
      path: "avatars/blobster-idle.gif"
    - source: "workspace/avatars/blobster-wave.gif"
      path: "avatars/blobster-wave.gif"
    - source: "workspace/avatars/cutout-256.png"
      path: "avatars/cutout-256.png"
    - source: "workspace/skills/forge-template/SKILL.md"
      path: "skills/forge-template/SKILL.md"
cronJobs:
  - id: "forge-manifest-audit"
    name: "Weekly Template Manifest & Trust Lint Audit"
    schedule:
      cron: "0 9 * * 1"
      timezone: "America/New_York"
    session: "isolated"
    message: "Run python3 scripts/lint_claw_template.py --json and python3 scripts/verify_blobster_factory.py across templates/*/. Stay silent when clean and all templates pass; only announce actionable lint or asset violations, and report explicit check failure rather than reusing stale data."
    delivery:
      mode: "announce"
      channel: "last"
---
