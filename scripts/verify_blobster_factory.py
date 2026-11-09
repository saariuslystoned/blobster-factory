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
   - hero-512.png (512x512, single-frame PNG, < 2 MiB).
   - cutout-256.png + sprite-2x2.png -> verified GIF89a idle/wave streams (< 2 MiB, >= 2 frames, 0 border-clip px, <= 1.5% #FF00FF spill).
   - Single-frame binary cleanliness across tracked template assets (no multi-frame binaries in Git tree).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_blobster_pack import analyze_pack_qa  # noqa: E402
from lint_claw_template import TEXT_SUFFIXES, lint_template_dir  # noqa: E402

ALLOWED_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def verify_github_front_door(repo_root: Path) -> list[str]:
    errors: list[str] = []
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        errors.append("Missing README.md")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        for token in (
            "<picture>",
            "prefers-color-scheme: dark",
            "prefers-color-scheme: light",
            ".github/assets/banner-dark.webp",
            ".github/assets/banner-light.webp",
        ):
            if token not in readme_text:
                errors.append(f"README.md missing expected front-door markup token: {token}")

    asset_specs = [
        (".github/assets/banner-dark.webp", "WEBP", (1600, 900), 500 * 1024),
        (".github/assets/banner-light.webp", "WEBP", (1600, 900), 500 * 1024),
        (".github/assets/social-preview.png", "PNG", (1280, 640), 1024 * 1024),
    ]
    for rel, exp_fmt, exp_size, max_bytes in asset_specs:
        apath = repo_root / rel
        if not apath.is_file():
            errors.append(f"Missing GitHub asset: {rel}")
            continue
        sz = apath.stat().st_size
        if sz > max_bytes:
            errors.append(f"{rel} ({sz} bytes) exceeds {max_bytes} byte budget")
        with Image.open(apath) as im:
            if im.format != exp_fmt:
                errors.append(f"{rel} format {im.format!r} != {exp_fmt!r}")
            if im.size != exp_size:
                errors.append(f"{rel} dimensions {im.size} != {exp_size}")
            if getattr(im, "n_frames", 1) != 1:
                errors.append(f"{rel} must be single-frame")
    return errors


def verify_template_dir(tdir: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []

    lint_res = lint_template_dir(tdir, strict_trust=True)
    for diag in lint_res["diagnostics"]:
        errors.append(f"{tdir.name}: [{diag['code']}] {diag['path']}: {diag['message']}")

    for fpath in sorted(tdir.rglob("*")):
        if not fpath.is_file():
            continue
        suf = fpath.suffix.lower()
        if suf in TEXT_SUFFIXES:
            continue
        raw = fpath.read_bytes()
        try:
            raw.decode("utf-8")
            if b"\0" not in raw:
                continue
        except UnicodeDecodeError:
            pass
        rel = fpath.relative_to(tdir).as_posix()
        if suf not in ALLOWED_BINARY_SUFFIXES:
            errors.append(
                f"{tdir.name}: [binary_policy] {rel}: unsupported binary extension {suf!r} in Git template tree (use single-frame PNG/JPEG/WebP)"
            )
            continue
        with Image.open(fpath) as bim:
            if getattr(bim, "n_frames", 1) != 1:
                errors.append(f"{tdir.name}: [binary_policy] {rel}: multi-frame binary images are not permitted in Git template tree")

    avatars_dir = tdir / "workspace" / "avatars"
    qa_res = analyze_pack_qa(avatars_dir, max_spill_pct=1.5)
    for qerr in qa_res["errors"]:
        errors.append(f"{tdir.name}: [avatar_qa] {qerr}")

    report = {
        "template": tdir.name,
        "ok": len(errors) == 0,
        "selectedFileCount": lint_res.get("selectedFileCount", 0),
        "excludedPaths": lint_res.get("excludedPaths", []),
        "animationSource": qa_res.get("animationSource"),
        "customSvgShapes": qa_res.get("customSvgShapes", 0),
        "maxMagentaSpillPct": qa_res.get("maxMagentaSpillPct", 0.0),
        "maxBorderClipPixels": qa_res.get("maxBorderClipPixels", 0),
        "sprite2x2Bytes": qa_res.get("sprite2x2Bytes", 0),
        "idleGifBytes": qa_res.get("idleGifBytes", 0),
        "waveGifBytes": qa_res.get("waveGifBytes", 0),
    }
    return errors, report


def main() -> int:
    all_errors: list[str] = []

    # 1. Check GitHub front-door assets portably (zero external skill dependency)
    all_errors.extend(verify_github_front_door(REPO_ROOT))

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
