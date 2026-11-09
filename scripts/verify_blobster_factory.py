#!/usr/bin/env python3
"""Deterministic verifier for saariuslystoned/blobster-factory.

Validates:
1. GitHub front-door assets (.github/assets/banner-{dark,light}.webp, social-preview.png, README.md <picture>).
2. Every OpenClaw Agent Template under templates/*/ via scripts/lint_claw_template.py:
   - package.json (valid name, exact semver, openclaw.template === "CLAW.md", zero scripts).
   - CLAW.md frontmatter (schemaVersion: 1, no SOUL.md + body conflict, confined workspace sources, 5-field cron).
   - profiles/openclaw.yml (schemaVersion: 1, bounded agent.tools.allow, workspaceOnly: true).
   - Zero unlisted/excluded files (excludedPaths == []), secret/token scrub, and the 4 safety & trust habits.
3. Every Tier 1 Avatar Pack under templates/*/workspace/avatars/ via scripts/compile_blobster_pack.py:
   - blobster.svg (256x256, viewBox="-12 -18 144 144", <= 24 custom vector shapes).
   - hero-512.png (512x512, < 2 MiB).
   - cutout-256.png, blobster-idle.gif, blobster-wave.gif (< 2 MiB, >= 2 frames, 0 border-clip px, <= 1.5% #FF00FF spill).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_blobster_pack import analyze_pack_qa  # noqa: E402
from lint_claw_template import lint_template_dir  # noqa: E402


def verify_template_dir(tdir: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []

    lint_res = lint_template_dir(tdir, strict_trust=True)
    for diag in lint_res["diagnostics"]:
        errors.append(f"{tdir.name}: [{diag['code']}] {diag['path']}: {diag['message']}")

    avatars_dir = tdir / "workspace" / "avatars"
    qa_res = analyze_pack_qa(avatars_dir, max_spill_pct=1.5)
    for qerr in qa_res["errors"]:
        errors.append(f"{tdir.name}: [avatar_qa] {qerr}")

    report = {
        "template": tdir.name,
        "ok": len(errors) == 0,
        "selectedFileCount": lint_res.get("selectedFileCount", 0),
        "excludedPaths": lint_res.get("excludedPaths", []),
        "customSvgShapes": qa_res.get("customSvgShapes", 0),
        "maxMagentaSpillPct": qa_res.get("maxMagentaSpillPct", 0.0),
        "maxBorderClipPixels": qa_res.get("maxBorderClipPixels", 0),
    }
    return errors, report


def main() -> int:
    all_errors: list[str] = []

    # 1. Check GitHub assets via smoky-github-design verifier if available
    gh_verifier = Path.home() / ".gemini/config/plugins/saarius-skills/skills/smoky-github-design/scripts/verify_github_assets.py"
    if gh_verifier.is_file():
        cmd = [
            sys.executable,
            str(gh_verifier),
            "--readme", str(REPO_ROOT / "README.md"),
            "--banner", str(REPO_ROOT / ".github/assets/banner-dark.webp"),
            "--banner", str(REPO_ROOT / ".github/assets/banner-light.webp"),
            "--social", str(REPO_ROOT / ".github/assets/social-preview.png"),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            all_errors.append(f"verify_github_assets.py failed:\n{proc.stdout}\n{proc.stderr}")

    # 2. Check templates (OpenClaw schema + 4 trust habits + Tier 1 avatar QA)
    templates_root = REPO_ROOT / "templates"
    template_dirs = sorted(p for p in templates_root.iterdir() if p.is_dir()) if templates_root.is_dir() else []
    if not template_dirs:
        all_errors.append("No templates found under templates/")

    template_reports: list[dict[str, Any]] = []
    for tdir in template_dirs:
        terrs, trep = verify_template_dir(tdir)
        all_errors.extend(terrs)
        template_reports.append(trep)

    summary: dict[str, Any] = {
        "ok": len(all_errors) == 0,
        "templatesVerified": [t.name for t in template_dirs],
        "templateReports": template_reports,
        "errors": all_errors,
    }
    print(json.dumps(summary, indent=2))
    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
