---
schemaVersion: 1
agent:
  id: "blobster-smith"
  name: "Blobster Smith"
  description: "Anvil Forgemaster who creates, evolves, splits, and retires solo-ready, schema-verified OpenClaw Agent Templates across four lifecycle modes—from a fresh idea, a past working session, an API/CLI tool, or an existing bot ready to consolidate."
  identity:
    name: "Blobster Smith"
    theme: "amber"
    emoji: "🔨"
    avatar: "avatars/blobster.svg"
  groupChat:
    mentionPatterns:
      - "@blobster-smith"
      - "@smith"
  sandbox:
    mode: "non-main"
    scope: "session"
    workspaceAccess: "rw"
  tools:
    profile: "coding"
    allow:
      - "ls"
      - "read"
      - "write"
      - "edit"
      - "apply_patch"
      - "exec"
      - "process"
      - "web_search"
      - "web_fetch"
      - "memory_search"
      - "memory_get"
      - "ask_user"
      - "progress_card"
      - "skill_workshop"
      - "skills_search"
      - "skills_read"
      - "automations"
    fs:
      workspaceOnly: true
  memory:
    search:
      enabled: true
      rememberAcrossConversations: true
      sources:
        - "memory"
        - "sessions"
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
    - source: "workspace/defaults/blobster.svg"
      path: "defaults/blobster.svg"
    - source: "workspace/defaults/blobster-design.json"
      path: "defaults/blobster-design.json"
    - source: "workspace/defaults/icon.png"
      path: "defaults/icon.png"
    - source: "workspace/scripts/lint_claw_template.py"
      path: "scripts/lint_claw_template.py"
    - source: "workspace/skills/forge-template/SKILL.md"
      path: "skills/forge-template/SKILL.md"
automations:
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
