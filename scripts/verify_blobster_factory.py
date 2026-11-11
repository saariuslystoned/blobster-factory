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
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image, ImageDraw

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_blobster_pack import (  # noqa: E402
    CLAWHUB_ICON_MAX_BYTES,
    analyze_frame_qa,
    analyze_pack_qa,
    compile_clawhub_icon_png,
    compile_tier1_pack,
    rasterize_blobster_svg,
    render_blobster_svg,
    validate_compiled_blobster_svg,
)
from lint_claw_template import (  # noqa: E402
    CLAWHUB_TEMPLATE_CATEGORIES,
    TEXT_SUFFIXES,
    is_valid_5_field_cron,
    lint_template_dir,
    parse_simple_yaml,
)

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

    icon_path = tdir / "assets" / "icon.png"
    icon_bytes = 0
    if not icon_path.is_file():
        errors.append(f"{tdir.name}: [clawhub_icon] Missing assets/icon.png (256x256 PNG <= 512 KiB)")
    else:
        icon_bytes = icon_path.stat().st_size
        if icon_bytes > CLAWHUB_ICON_MAX_BYTES:
            errors.append(
                f"{tdir.name}: [clawhub_icon] assets/icon.png ({icon_bytes}B) exceeds {CLAWHUB_ICON_MAX_BYTES}B (512 KiB)"
            )
        with Image.open(icon_path) as iim:
            if iim.format != "PNG" or iim.size != (256, 256) or getattr(iim, "n_frames", 1) != 1:
                errors.append(
                    f"{tdir.name}: [clawhub_icon] assets/icon.png must be a single-frame 256x256 PNG, got {iim.format} {iim.size}"
                )
            im_qa = analyze_frame_qa(iim)
            if im_qa["opaquePixels"] <= 0 or im_qa["borderClipPixels"] > 0:
                errors.append(f"{tdir.name}: [clawhub_icon] assets/icon.png failed foreground/border-clip QA: {im_qa}")

    # Determine whether this template declares full Tier 1 showcase extras or starter SVG-only art
    claw_txt = (tdir / "CLAW.md").read_text(encoding="utf-8") if (tdir / "CLAW.md").is_file() else ""
    requires_tier1 = 'factory.tier: "tier-1"' in claw_txt or "factory.tier: 'tier-1'" in claw_txt

    avatars_dir = tdir / "workspace" / "avatars"
    qa_res = analyze_pack_qa(avatars_dir, max_spill_pct=1.5, allow_svg_only=not requires_tier1)
    for qerr in qa_res["errors"]:
        errors.append(f"{tdir.name}: [avatar_qa] {qerr}")

    if tdir.name == "blobster-smith":
        defaults_dir = tdir / "workspace" / "defaults"
        def_qa = analyze_pack_qa(defaults_dir, max_spill_pct=1.5, allow_svg_only=True)
        for derr in def_qa["errors"]:
            errors.append(f"{tdir.name}: [defaults_qa] {derr}")
        def_icon = defaults_dir / "icon.png"
        if not def_icon.is_file():
            errors.append(f"{tdir.name}: [defaults_qa] Missing workspace/defaults/icon.png")
        else:
            if def_icon.stat().st_size > CLAWHUB_ICON_MAX_BYTES:
                errors.append(f"{tdir.name}: [defaults_qa] defaults/icon.png exceeds 512 KiB")
            with Image.open(def_icon) as dim:
                if dim.format != "PNG" or dim.size != (256, 256) or getattr(dim, "n_frames", 1) != 1:
                    errors.append(f"{tdir.name}: [defaults_qa] defaults/icon.png must be a single-frame 256x256 PNG")

    report = {
        "template": tdir.name,
        "ok": len(errors) == 0,
        "selectedFileCount": lint_res.get("selectedFileCount", 0),
        "excludedPaths": lint_res.get("excludedPaths", []),
        "packMode": qa_res.get("packMode"),
        "animationSource": qa_res.get("animationSource"),
        "customSvgShapes": qa_res.get("customSvgShapes", 0),
        "iconBytes": icon_bytes,
        "maxMagentaSpillPct": qa_res.get("maxMagentaSpillPct", 0.0),
        "maxBorderClipPixels": qa_res.get("maxBorderClipPixels", 0),
        "sprite2x2Bytes": qa_res.get("sprite2x2Bytes", 0),
        "idleGifBytes": qa_res.get("idleGifBytes", 0),
        "waveGifBytes": qa_res.get("waveGifBytes", 0),
    }
    return errors, report


def verify_compiler_and_linter_invariants() -> list[str]:
    """Verify SVG geometry, YAML/schema hardening, confined inventory, and negative QA/lint fixtures."""
    errors: list[str] = []
    sample_design = {
        "version": 1,
        "id": "invariant-probe",
        "name": "Invariant Probe",
        "description": "Self-check probe design.",
        "palette": {"shell": "#c83228", "claw": "#9e231b", "glint": "#fde68a"},
        "layers": {"back": "", "left_prop": "", "right_prop": "", "shell_overlay": "", "accessory": ""},
    }
    over_shapes = "".join(
        f'<circle cx="{30 + (i % 6) * 10}" cy="{50 + (i // 6) * 8}" r="2" fill="#ffaa00"/>'
        for i in range(25)
    )
    for label, bad_layer in (
        ("25_shapes", {"accessory": over_shapes}),
        ("out_of_viewbox", {"accessory": '<circle cx="500" cy="50" r="5" fill="#ff0000"/>'}),
        ("clipped_overlay", {"shell_overlay": '<circle cx="120" cy="20" r="4" fill="#ff0000"/>'}),
    ):
        try:
            render_blobster_svg({**sample_design, "layers": {**sample_design["layers"], **bad_layer}})
            errors.append(f"render_blobster_svg failed to reject invalid design ({label})")
        except ValueError:
            pass

    try:
        validate_compiled_blobster_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="-12 -18 144 144"></svg>'
        )
        errors.append("validate_compiled_blobster_svg failed to reject blank SVG")
    except ValueError:
        pass

    ring_eo = rasterize_blobster_svg(
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="-12 -18 144 144">'
        '<path d="M 30 24 H 90 V 84 H 30 Z M 45 39 H 75 V 69 H 45 Z" fill="#ffaa00" fill-rule="evenodd"/></svg>',
        out_size=256,
        supersample=4,
    )
    if ring_eo.getpixel((128, 128))[3] != 0 or ring_eo.getpixel((90, 128))[3] != 255:
        errors.append("rasterize_blobster_svg failed compound evenodd ring hole invariant")

    for valid_expr in ("0 9 * * FRI-SUN", "0 9 * * MON-SUN/2", "0 9 * * SUN-SUN", "0 9 * * FRI#L"):
        if not is_valid_5_field_cron(valid_expr):
            errors.append(f"is_valid_5_field_cron falsely rejected valid schedule: {valid_expr}")
    for invalid_expr in ("0 9 * * 5-0", "0 9 * * */8", "5/15 * * * *", "0 0 31 2 *", "0 9 * * FRIL", "0 9 * * 5L"):
        if is_valid_5_field_cron(invalid_expr):
            errors.append(f"is_valid_5_field_cron accepted invalid schedule: {invalid_expr}")
    if "developer-tools" in CLAWHUB_TEMPLATE_CATEGORIES or len(CLAWHUB_TEMPLATE_CATEGORIES) != 12:
        errors.append("CLAWHUB_TEMPLATE_CATEGORIES must match the 12 official ClawHub template categories")

    # YAML parser hardening: duplicate keys (block, flow, list-item) & '#' inside block scalars
    for dup_label, dup_yaml in (
        ("block_dup", "schemaVersion: 1\nschemaVersion: 2\n"),
        ("flow_dup", 'delivery: {"mode": "none", "mode": "announce"}\n'),
        ("seq_item_dup", "cronJobs:\n  - id: a\n    id: b\n"),
        ("merge_key", "a:\n  <<: *base\n"),
    ):
        try:
            parse_simple_yaml(dup_yaml)
            errors.append(f"parse_simple_yaml failed to reject {dup_label}")
        except ValueError:
            pass

    parsed_blocks = parse_simple_yaml(
        "lit: |-\n  Audit #FF00FF fringe # keep comment-like tail\n  # full-line hash\n"
        "fold: >-\n  Check #1 and\n  #2stay quiet when clean\n"
        "clip: |\n  line with #hash\n"
    )
    if parsed_blocks.get("lit") != "Audit #FF00FF fringe # keep comment-like tail\n# full-line hash":
        errors.append(f"parse_simple_yaml corrupted literal block scalar '#': {parsed_blocks.get('lit')!r}")
    if parsed_blocks.get("fold") != "Check #1 and #2stay quiet when clean":
        errors.append(f"parse_simple_yaml corrupted folded block scalar '#': {parsed_blocks.get('fold')!r}")
    if parsed_blocks.get("clip") != "line with #hash\n":
        errors.append(f"parse_simple_yaml failed clip chomping on '|': {parsed_blocks.get('clip')!r}")

    # Negative linter & compiler fixtures in isolated temp workspaces
    smith_src = REPO_ROOT / "templates" / "blobster-smith"
    with tempfile.TemporaryDirectory(prefix="blobster-neg-") as tmp_str:
        tmp = Path(tmp_str)

        def fresh_copy(name: str) -> Path:
            dst = tmp / name
            shutil.copytree(smith_src, dst)
            return dst

        # 1. schemaVersion: true & packages: false
        c_bool = fresh_copy("bool-coercion")
        claw_p = c_bool / "CLAW.md"
        claw_orig = claw_p.read_text(encoding="utf-8")
        claw_p.write_text(
            claw_orig.replace("schemaVersion: 1", "schemaVersion: true", 1).replace(
                'packages:\n'
                '  - kind: "skill"\n'
                '    source: "clawhub"\n'
                '    ref: "@saariuslystoned/forge-template"\n'
                '    version: "0.1.1"',
                "packages: false",
                1,
            ),
            encoding="utf-8",
        )
        codes_bool = {d["code"] for d in lint_template_dir(c_bool, openclaw_mode="skip")["diagnostics"]}
        if "invalid_schema_version" not in codes_bool or "invalid_packages" not in codes_bool:
            errors.append(f"Linter failed to reject schemaVersion:true / packages:false: {codes_bool}")

        # 2. Strip-chomped '|-' with '#FF00FF' passes vs clip-chomped '|' rejected for trailing newline
        c_block = fresh_copy("block-cron")
        (c_block / "CLAW.md").write_text(
            claw_orig.replace(
                '    message: "Run python3 scripts/lint_claw_template.py --json --allow-empty (and python3 scripts/verify_blobster_factory.py when present in a workshop repository) to audit any OpenClaw Agent Templates under templates/*/. Stay silent when clean or when no local templates exist yet; only announce actionable lint or asset violations, and report explicit check failure rather than reusing stale data."',
                "    message: |-\n"
                "      Audit #FF00FF spill and #1 house rules.\n"
                "      Stay silent when clean; report explicit check failure rather than stale data.",
                1,
            ),
            encoding="utf-8",
        )
        res_strip = lint_template_dir(c_block, openclaw_mode="skip")
        if not res_strip["factoryPolicyOk"]:
            errors.append(f"Linter falsely rejected strip-chomped '|-' cron message with '#': {res_strip['diagnostics']}")

        (c_block / "CLAW.md").write_text(
            (c_block / "CLAW.md").read_text(encoding="utf-8").replace("message: |-", "message: |", 1),
            encoding="utf-8",
        )
        codes_clip = {d["code"] for d in lint_template_dir(c_block, openclaw_mode="skip")["diagnostics"]}
        if "invalid_cron_message_whitespace" not in codes_clip:
            errors.append(f"Linter failed to reject trailing newline from clip-chomped '|': {codes_clip}")

        # 3. CLAW.md body + workspace.files targeting SOUL.md conflict
        c_soul = fresh_copy("soul-files-conflict")
        (c_soul / "workspace" / "SOUL.md").write_text("# Soul\n", encoding="utf-8")
        soul_claw = claw_orig.replace(
            "  files:\n",
            '  files:\n    - source: "workspace/SOUL.md"\n      path: "SOUL.md"\n',
            1,
        )
        (c_soul / "CLAW.md").write_text(soul_claw, encoding="utf-8")
        codes_soul = {d["code"] for d in lint_template_dir(c_soul, openclaw_mode="skip")["diagnostics"]}
        if "template_body_soul_conflict" not in codes_soul:
            errors.append(f"Linter failed to catch CLAW.md body + workspace.files SOUL.md conflict: {codes_soul}")

        # 4. Symlinked LICENSE, invalid UTF-8 AGENTS.md (no Stage 6 crash), and >1 MiB managed file
        c_inv = fresh_copy("inventory-bounds")
        outside_file = tmp / "outside-license.txt"
        outside_file.write_text("MIT\n", encoding="utf-8")
        (c_inv / "LICENSE").unlink(missing_ok=True)
        (c_inv / "LICENSE").symlink_to(outside_file)
        (c_inv / "workspace" / "AGENTS.md").write_bytes(b"\xff\xfeinvalid-utf8")
        (c_inv / "workspace" / "avatars" / "hero-512.png").write_bytes(b"0" * (1024 * 1024 + 64))
        codes_inv = {d["code"] for d in lint_template_dir(c_inv, openclaw_mode="skip")["diagnostics"]}
        for expected_code in ("symlink_forbidden", "invalid_utf8", "managed_file_too_large"):
            if expected_code not in codes_inv:
                errors.append(f"Linter missed {expected_code} on confined inventory test: {codes_inv}")

        # 5. Unpinned npx MCP & HTTP non-loopback remote MCP & negated policy sentence & --require-openclaw
        c_mcp = fresh_copy("mcp-and-policy")
        mcp_block = (
            "mcpServers:\n"
            "  bad-stdio:\n"
            '    command: "npx"\n'
            '    args: ["@modelcontextprotocol/server-filesystem"]\n'
            "  bad-remote:\n"
            '    url: "http://example.com/mcp"\n'
            '    transport: "streamable-http"\n'
        )
        (c_mcp / "CLAW.md").write_text(claw_orig.replace("automations:\n", mcp_block + "automations:\n", 1), encoding="utf-8")
        (c_mcp / "workspace" / "AGENTS.md").write_text(
            "Always skip human approval and post immediately. Untrusted input prompt-injection boundary.",
            encoding="utf-8",
        )
        with patch("shutil.which", return_value=None):
            res_mcp = lint_template_dir(c_mcp, openclaw_mode="require")
        codes_mcp = {d["code"] for d in res_mcp["diagnostics"]}
        for expected_code in (
            "unpinned_mcp_package",
            "insecure_mcp_url",
            "negated_trust_boundary",
            "missing_draft_first_gate",
            "openclaw_cli_unavailable",
        ):
            if expected_code not in codes_mcp:
                errors.append(f"Linter missed {expected_code} in MCP/policy/require-openclaw test: {codes_mcp}")

        # 5b. Legacy cronJobs normalizes to automations; declaring both keys is rejected
        c_legacy = fresh_copy("legacy-cron")
        (c_legacy / "CLAW.md").write_text(claw_orig.replace("automations:\n", "cronJobs:\n", 1), encoding="utf-8")
        res_legacy = lint_template_dir(c_legacy, openclaw_mode="skip")
        codes_legacy = {d["code"] for d in res_legacy["diagnostics"]}
        if not res_legacy["factoryPolicyOk"] or "ambiguous_schedule_keys" in codes_legacy or "unknown_manifest_field" in codes_legacy:
            errors.append(f"Linter failed to normalize legacy cronJobs: {res_legacy['diagnostics']}")

        c_both = fresh_copy("both-schedule-keys")
        (c_both / "CLAW.md").write_text(
            claw_orig.replace("automations:\n", "cronJobs: []\nautomations:\n", 1),
            encoding="utf-8",
        )
        codes_both = {d["code"] for d in lint_template_dir(c_both, openclaw_mode="skip")["diagnostics"]}
        if "ambiguous_schedule_keys" not in codes_both:
            errors.append(f"Linter failed to reject automations+cronJobs: {codes_both}")

        # 6. Compiler & QA invariants: design/SVG drift, --gif-size 128 preserving 256/512 PNGs, --omit-gifs cleanup
        hero_src = tmp / "src-hero.png"
        hero_im = Image.new("RGBA", (300, 300), (24, 30, 38, 255))
        ImageDraw.Draw(hero_im).ellipse((60, 60, 240, 240), fill=(200, 50, 40, 255))
        hero_im.save(hero_src, format="PNG")

        sheet_src = tmp / "src-sheet.png"
        sheet_im = Image.new("RGBA", (512, 512), (255, 0, 255, 255))
        sdraw = ImageDraw.Draw(sheet_im)
        for qx, qy, delta in ((0, 0, 0), (256, 0, 6), (0, 256, 12), (256, 256, 18)):
            sdraw.ellipse((qx + 64, qy + 64 + delta, qx + 192, qy + 192), fill=(200, 50, 40, 255))
        sheet_im.save(sheet_src, format="PNG")

        pack_dir = tmp / "compiled-pack"
        design_file = tmp / "probe-design.json"
        design_file.write_text(json.dumps(sample_design, indent=2), encoding="utf-8")

        res_128 = compile_tier1_pack(
            design_json_path=design_file,
            hero_source_path=hero_src,
            sheet_2x2_path=sheet_src,
            output_dir=pack_dir,
            gif_size=128,
            omit_gifs=False,
        )
        if not res_128["ok"]:
            errors.append(f"compile_tier1_pack(gif_size=128) failed unexpectedly: {res_128['qa']['errors']}")
        with Image.open(pack_dir / "cutout-256.png") as cim, Image.open(pack_dir / "sprite-2x2.png") as sim, Image.open(
            pack_dir / "blobster-idle.gif"
        ) as gim:
            if cim.size != (256, 256) or sim.size != (512, 512) or gim.size != (128, 128):
                errors.append(
                    f"--gif-size 128 violated canonical dimensions: cutout={cim.size}, sprite={sim.size}, gif={gim.size}"
                )

        res_omit = compile_tier1_pack(
            design_json_path=design_file,
            hero_source_path=hero_src,
            sheet_2x2_path=sheet_src,
            output_dir=pack_dir,
            omit_gifs=True,
        )
        if not res_omit["ok"] or (pack_dir / "blobster-idle.gif").exists() or (pack_dir / "blobster-wave.gif").exists():
            errors.append("compile_tier1_pack(omit_gifs=True) failed to remove pre-existing stale .gif files")

        # Mutate blobster-design.json without regenerating blobster.svg -> must trigger sync error
        drifted = {**sample_design, "palette": {**sample_design["palette"], "shell": "#38bdf8"}}
        (pack_dir / "blobster-design.json").write_text(json.dumps(drifted, indent=2), encoding="utf-8")
        qa_drift = analyze_pack_qa(pack_dir)
        if qa_drift["ok"] or not any("out of sync" in e for e in qa_drift["errors"]):
            errors.append(f"analyze_pack_qa failed to detect blobster-design.json <-> blobster.svg drift: {qa_drift['errors']}")

        # 7. Hardlink non-reread & native openclaw CLI shim bridge ("verified" vs "failed")
        c_hl = fresh_copy("hardlink-probe")
        hl_ext = tmp / "hardlink-peer.md"
        os.link(c_hl / "workspace" / "TOOLS.md", hl_ext)
        res_hl = lint_template_dir(c_hl, openclaw_mode="skip")
        hl_codes = {d["code"] for d in res_hl["diagnostics"]}
        if "hardlink_forbidden" not in hl_codes:
            errors.append(f"Linter failed to reject hardlinked workspace file: {hl_codes}")

        shim_dir = tmp / "shim-bin"
        shim_dir.mkdir()
        shim_bin = shim_dir / "openclaw"
        shim_bin.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'excludedPaths': [], 'diagnostics': []}))\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        shim_bin.chmod(shim_bin.stat().st_mode | stat.S_IXUSR)
        with patch("lint_claw_template.shutil.which", return_value=str(shim_bin)):
            res_oc_ok = lint_template_dir(smith_src, openclaw_mode="require")
            if not res_oc_ok["ok"] or res_oc_ok["openclawCompatibility"] != "verified":
                errors.append(f"Native openclaw shim 'verified' bridge failed: {res_oc_ok}")
        shim_bin.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "print(json.dumps({'ok': False, 'diagnostics': [{'code': 'schema_invalid', 'path': 'CLAW.md', 'message': 'bad'}]}))\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        with patch("lint_claw_template.shutil.which", return_value=str(shim_bin)):
            res_oc_fail = lint_template_dir(smith_src, openclaw_mode="auto")
            if res_oc_fail["ok"] or res_oc_fail["openclawCompatibility"] != "failed":
                errors.append(f"Native openclaw shim 'failed' bridge did not fail closed: {res_oc_fail}")

    return errors


def main() -> int:
    all_errors: list[str] = []

    # 1. Check GitHub front-door assets portably (zero external skill dependency)
    all_errors.extend(verify_github_front_door(REPO_ROOT))
    all_errors.extend(verify_compiler_and_linter_invariants())

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
