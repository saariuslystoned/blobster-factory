#!/usr/bin/env python3
"""Deterministic OpenClaw Agent Template linter & trust-habit verifier.

Enforces four invariants on every OpenClaw Agent Template directory:
1. Zero-exclusion OpenClaw schema & package compliance:
   - package.json (canonical name, exact semver, openclaw.template == "CLAW.md", zero scripts)
   - CLAW.md (schemaVersion: 1, no body + workspace SOUL.md collision, no deprecated
     metadata.openclaw.config pointer, confined existing workspace sources, valid 5-field cronJobs)
   - profiles/openclaw.yml (schemaVersion: 1, bounded agent.tools.allow without wildcards,
     workspaceOnly: true, no forbidden model/provider/credential keys)
   - Zero unlisted/excluded files inside the template root (matches OpenClaw validateTemplateProject
     excludedPaths == [])
2. Secret, token & private-path scrub:
   - Rejects raw API keys/tokens, private keys, literal mcpServers env secrets (must use "${ENV_VAR}"),
     and machine-local home paths (/Users/<name>/, /home/<name>/, C:\\Users\\)
3. Draft-first outbound approval gate & untrusted outside/group-chat input boundary in AGENTS.md / CLAW.md
4. Quiet-on-clean (dead-day silence) & stale/fabricated-data refusal on scheduled cronJobs / HEARTBEAT.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

MAX_PACKAGE_JSON_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PROFILE_BYTES = 256 * 1024
MAX_PROJECT_ENTRIES = 4096

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PACKAGE_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]{0,62}/)?[a-z][a-z0-9._-]{0,63}$")
ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")
CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")

TEXT_SUFFIXES = {
    ".md", ".json", ".yml", ".yaml", ".txt", ".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".toml", ".svg"
}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_or_stripe_key", re.compile(r"\bsk-(?:live-|test-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b")),
    ("xai_key", re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{24,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
]

PRIVATE_PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("macos_home_path", re.compile(r"/Users/[A-Za-z0-9_][A-Za-z0-9._-]*/")),
    ("linux_home_path", re.compile(r"/home/[A-Za-z0-9_][A-Za-z0-9._-]*/")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_][A-Za-z0-9._-]*\\")),
]

DRAFT_GATE_RE = re.compile(
    r"\b(?:draft(?:-first|-only|s)?|human(?:-|\s+)(?:gate\w*|approv\w*|confirm\w*)|"
    r"explicit(?:\s+human)?\s+(?:approv\w*|confirm\w*)|never\s+(?:auto-send|send|post|publish|push)\b)",
    re.IGNORECASE,
)
UNTRUSTED_BOUNDARY_RE = re.compile(
    r"\b(?:untrusted(?:\s+(?:input|data|message|content|memory|room|team))?|prompt[- ]injection|"
    r"cannot\s+(?:override|rewrite|modify|mutate)\s+(?:AGENTS|SOUL|operating))",
    re.IGNORECASE,
)
QUIET_ON_CLEAN_RE = re.compile(
    r"\b(?:stay(?:s)?\s+(?:quiet|silent)|quiet(?:-on-(?:clean|dead-days)|\s+when\s+(?:clean|nothing|zero|no\s+issues))|"
    r"silent\s+when\s+(?:clean|nothing|all\s+pass|zero)|do\s+not\s+(?:spam|announce|post)\s+when|"
    r"only\s+(?:announce|notify|alert|post)\s+when)\b",
    re.IGNORECASE,
)
STALE_REFUSAL_RE = re.compile(
    r"\b(?:stale(?:\s+data|\s+result|\s+report)?|never\s+(?:invent|fabricate|fake|recycle)|"
    r"report\s+(?:explicit\s+)?(?:source\s+|tool\s+|check\s+)?failure)\b",
    re.IGNORECASE,
)


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def _split_flow_items(inner: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    for ch in inner:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_double:
            buf.append(ch)
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_single
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == "," and depth == 0:
                part = "".join(buf).strip()
                if part:
                    items.append(part)
                buf = []
                continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def _parse_scalar(token: str) -> Any:
    t = token.strip()
    if t == "":
        return ""
    if t in ("null", "~"):
        return None
    if t == "true":
        return True
    if t == "false":
        return False
    if t.startswith('"') and t.endswith('"') and len(t) >= 2:
        return json.loads(t)
    if t.startswith("'") and t.endswith("'") and len(t) >= 2:
        return t[1:-1].replace("''", "'")
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in _split_flow_items(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for entry in _split_flow_items(inner):
            k, sep, v = _split_key_val(entry)
            if not sep:
                raise ValueError(f"Invalid inline YAML mapping entry: {entry!r}")
            out[k] = _parse_scalar(v)
        return out
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return t


def _split_key_val(text: str) -> tuple[str, bool, str]:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if idx + 1 == len(text) or text[idx + 1].isspace():
                raw_k = text[:idx].strip()
                k = str(_parse_scalar(raw_k)) if (raw_k[:1] in ('"', "'")) else raw_k
                return k, True, text[idx + 1 :].strip()
    return text.strip(), False, ""


def parse_simple_yaml(text: str) -> Any:
    """Parse the clean block/flow YAML subset used in CLAW.md and profiles/openclaw.yml."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        cleaned = _strip_yaml_comment(raw)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        if "\t" in cleaned[:indent]:
            raise ValueError("YAML indentation must use spaces, not tabs")
        lines.append((indent, cleaned.strip()))

    if not lines:
        return {}

    def parse_block(idx: int, base_indent: int) -> tuple[Any, int]:
        if idx >= len(lines):
            return {}, idx
        cur_indent, cur_text = lines[idx]
        if cur_indent < base_indent:
            return {}, idx

        if cur_text == "-" or cur_text.startswith("- "):
            arr: list[Any] = []
            while idx < len(lines):
                ind, txt = lines[idx]
                if ind < cur_indent:
                    break
                if ind > cur_indent or not (txt == "-" or txt.startswith("- ")):
                    break
                rest = txt[1:].strip()
                idx += 1
                if not rest:
                    val, idx = parse_block(idx, cur_indent + 1)
                    arr.append(val)
                else:
                    k, has_colon, v = _split_key_val(rest)
                    if has_colon:
                        item_map: dict[str, Any] = {}
                        if v in ("|", ">", "|-", ">-"):
                            block_lines_item: list[str] = []
                            block_ind_item: int | None = None
                            while idx < len(lines) and lines[idx][0] > cur_indent + 2:
                                b_ind, b_txt = lines[idx]
                                if block_ind_item is None:
                                    block_ind_item = b_ind
                                pad = " " * max(0, b_ind - block_ind_item)
                                block_lines_item.append(pad + b_txt)
                                idx += 1
                            joiner_item = "\n" if v.startswith("|") else " "
                            item_map[k] = joiner_item.join(block_lines_item)
                        elif v == "":
                            sub_val, idx = parse_block(idx, cur_indent + 1)
                            item_map[k] = sub_val
                        else:
                            item_map[k] = _parse_scalar(v)
                        while idx < len(lines) and lines[idx][0] > cur_indent:
                            sub_ind = lines[idx][0]
                            extra, idx = parse_block(idx, sub_ind)
                            if isinstance(extra, dict):
                                item_map.update(extra)
                            else:
                                raise ValueError(f"Unexpected nested list item structure near {lines[idx - 1][1]!r}")
                        arr.append(item_map)
                    else:
                        arr.append(_parse_scalar(rest))
            return arr, idx

        mapping: dict[str, Any] = {}
        while idx < len(lines):
            ind, txt = lines[idx]
            if ind < cur_indent:
                break
            if ind > cur_indent:
                raise ValueError(f"Unexpected indentation at {txt!r}")
            if txt == "-" or txt.startswith("- "):
                break
            k, has_colon, v = _split_key_val(txt)
            if not has_colon:
                raise ValueError(f"Expected key: value in YAML at {txt!r}")
            idx += 1
            if v in ("|", ">", "|-", ">-"):
                block_lines: list[str] = []
                block_indent: int | None = None
                while idx < len(lines) and lines[idx][0] > cur_indent:
                    b_ind, b_txt = lines[idx]
                    if block_indent is None:
                        block_indent = b_ind
                    pad = " " * max(0, b_ind - block_indent)
                    block_lines.append(pad + b_txt)
                    idx += 1
                joiner = "\n" if v.startswith("|") else " "
                mapping[k] = joiner.join(block_lines)
            elif v == "":
                if idx < len(lines) and lines[idx][0] > cur_indent:
                    sub_val, idx = parse_block(idx, lines[idx][0])
                    mapping[k] = sub_val
                else:
                    mapping[k] = {}
            else:
                mapping[k] = _parse_scalar(v)
        return mapping, idx

    result, next_idx = parse_block(0, lines[0][0])
    if next_idx < len(lines):
        raise ValueError(f"Trailing unparsed YAML at {lines[next_idx][1]!r}")
    return result


def is_valid_5_field_cron(expr: str) -> bool:
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    return all(bool(CRON_FIELD_RE.match(p)) for p in parts)


def _portable_path_key(rel_path: str) -> str:
    return unicodedata.normalize("NFC", rel_path.replace("\\", "/")).lower()


def _is_safe_rel_path(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
        return False
    parts = rel_path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _diag(code: str, path: str, message: str) -> dict[str, str]:
    return {"level": "error", "code": code, "path": path, "message": message}


def _scan_text_for_secrets_and_paths(rel_path: str, content: str) -> list[dict[str, str]]:
    diags: list[dict[str, str]] = []
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(content):
            diags.append(
                _diag(
                    "secret_detected",
                    rel_path,
                    f"{rel_path} contains credential-like text matching {label}; use unresolved ${{ENV_VAR}} references.",
                )
            )
    for label, pattern in PRIVATE_PATH_PATTERNS:
        if pattern.search(content):
            diags.append(
                _diag(
                    "private_path_detected",
                    rel_path,
                    f"{rel_path} contains machine-local path ({label}); keep template instructions portable.",
                )
            )
    return diags


def lint_template_dir(tdir: Path, *, strict_trust: bool = True) -> dict[str, Any]:
    """Lint a single OpenClaw Agent Template directory and return structured diagnostics."""
    diagnostics: list[dict[str, str]] = []
    root = tdir.resolve()
    pkg_path = root / "package.json"
    claw_path = root / "CLAW.md"
    profile_path = root / "profiles" / "openclaw.yml"

    if not pkg_path.is_file():
        diagnostics.append(_diag("missing_package_json", "package.json", "Missing package.json"))
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}
    if not claw_path.is_file():
        diagnostics.append(_diag("missing_claw_md", "CLAW.md", "Missing CLAW.md"))
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}

    # 1. package.json checks
    try:
        pkg_bytes = pkg_path.read_bytes()
        if len(pkg_bytes) > MAX_PACKAGE_JSON_BYTES:
            diagnostics.append(_diag("package_too_large", "package.json", "package.json exceeds 256 KiB"))
        pkg = json.loads(pkg_bytes.decode("utf-8"))
    except Exception as exc:
        diagnostics.append(_diag("invalid_package_json", "package.json", f"Invalid UTF-8 JSON: {exc}"))
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}

    if not isinstance(pkg, dict):
        diagnostics.append(_diag("invalid_package_json", "package.json", "package.json must be a JSON object"))
        pkg = {}

    pkg_name = pkg.get("name")
    if not isinstance(pkg_name, str) or not PACKAGE_NAME_RE.match(pkg_name):
        diagnostics.append(
            _diag("invalid_package_name", "package.json.name", f"Invalid ClawHub package name: {pkg_name!r}")
        )
    pkg_ver = pkg.get("version")
    if not isinstance(pkg_ver, str) or not SEMVER_RE.match(pkg_ver):
        diagnostics.append(
            _diag("invalid_package_version", "package.json.version", f"Version must be exact semver: {pkg_ver!r}")
        )
    openclaw_meta = pkg.get("openclaw")
    if not isinstance(openclaw_meta, dict) or openclaw_meta.get("template") != "CLAW.md" or "claw" in openclaw_meta:
        diagnostics.append(
            _diag(
                "project_manifest_must_be_template_markdown",
                "package.json.openclaw.template",
                'package.json must set openclaw.template to "CLAW.md" (without legacy openclaw.claw).',
            )
        )
    if "scripts" in pkg and (not isinstance(pkg["scripts"], dict) or len(pkg["scripts"]) > 0):
        diagnostics.append(
            _diag(
                "project_scripts_forbidden",
                "package.json.scripts",
                "OpenClaw Template projects cannot declare npm scripts or lifecycle hooks.",
            )
        )
    if "license" in pkg and (not isinstance(pkg["license"], str) or not pkg["license"].strip()):
        diagnostics.append(
            _diag("project_license_invalid", "package.json.license", "package.json license must be a non-empty string.")
        )

    # 2. CLAW.md frontmatter & manifest checks
    try:
        claw_bytes = claw_path.read_bytes()
        if len(claw_bytes) > MAX_MANIFEST_BYTES:
            diagnostics.append(_diag("manifest_too_large", "CLAW.md", "CLAW.md exceeds 1 MiB"))
        claw_text = claw_bytes.decode("utf-8")
    except Exception as exc:
        diagnostics.append(_diag("invalid_claw_utf8", "CLAW.md", f"CLAW.md must be valid UTF-8: {exc}"))
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}

    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n([\s\S]*))?$", claw_text)
    if not m:
        diagnostics.append(
            _diag("missing_template_frontmatter", "CLAW.md", "CLAW.md must start with --- YAML frontmatter ---")
        )
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}

    fm_str, body_str = m.group(1), (m.group(2) or "").strip()
    try:
        manifest = parse_simple_yaml(fm_str)
    except Exception as exc:
        diagnostics.append(_diag("invalid_manifest_yaml", "CLAW.md", f"YAML parse failure: {exc}"))
        return {"template": tdir.name, "root": str(root), "ok": False, "excludedPaths": [], "diagnostics": diagnostics}

    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        diagnostics.append(_diag("invalid_schema_version", "CLAW.md.schemaVersion", "CLAW.md schemaVersion must be 1"))
        manifest = manifest if isinstance(manifest, dict) else {}

    agent_cfg = manifest.get("agent")
    if not isinstance(agent_cfg, dict):
        diagnostics.append(_diag("missing_agent_block", "CLAW.md.agent", "CLAW.md must declare an agent mapping"))
        agent_cfg = {}
    else:
        aid = agent_cfg.get("id")
        aname = agent_cfg.get("name")
        if not isinstance(aid, str) or not AGENT_ID_RE.match(aid):
            diagnostics.append(_diag("invalid_agent_id", "CLAW.md.agent.id", f"Invalid agent.id: {aid!r}"))
        if not isinstance(aname, str) or not aname.strip():
            diagnostics.append(_diag("invalid_agent_name", "CLAW.md.agent.name", "agent.name must be non-empty"))

    metadata_cfg = manifest.get("metadata")
    if isinstance(metadata_cfg, dict) and "openclaw.config" in metadata_cfg:
        diagnostics.append(
            _diag(
                "deprecated_openclaw_profile_pointer",
                "CLAW.md.metadata.openclaw.config",
                "Remove deprecated metadata.openclaw.config pointer; OpenClaw discovers profiles/openclaw.yml automatically.",
            )
        )

    workspace_cfg = manifest.get("workspace") or {}
    if not isinstance(workspace_cfg, dict):
        diagnostics.append(_diag("invalid_workspace", "CLAW.md.workspace", "workspace must be a mapping"))
        workspace_cfg = {}

    bootstrap_files = workspace_cfg.get("bootstrapFiles") or {}
    if not isinstance(bootstrap_files, dict):
        diagnostics.append(_diag("invalid_bootstrap_files", "CLAW.md.workspace.bootstrapFiles", "Must be a mapping"))
        bootstrap_files = {}

    if "SOUL.md" in bootstrap_files and body_str:
        diagnostics.append(
            _diag(
                "template_body_soul_conflict",
                "CLAW.md",
                "CLAW.md cannot contain both markdown body text and workspace.bootstrapFiles['SOUL.md'].",
            )
        )

    workspace_sources: list[str] = []
    for bname, bentry in bootstrap_files.items():
        src = bentry.get("source") if isinstance(bentry, dict) else None
        if not isinstance(src, str) or not _is_safe_rel_path(src):
            diagnostics.append(
                _diag("invalid_bootstrap_source", f"CLAW.md.workspace.bootstrapFiles.{bname}", f"Unsafe source {src!r}")
            )
            continue
        workspace_sources.append(src)

    ws_files = workspace_cfg.get("files") or []
    if not isinstance(ws_files, list):
        diagnostics.append(_diag("invalid_workspace_files", "CLAW.md.workspace.files", "workspace.files must be a list"))
        ws_files = []
    for idx, fentry in enumerate(ws_files):
        if not isinstance(fentry, dict):
            diagnostics.append(_diag("invalid_workspace_file_entry", f"CLAW.md.workspace.files[{idx}]", "Must be a map"))
            continue
        src = fentry.get("source")
        dst = fentry.get("path")
        if not isinstance(src, str) or not _is_safe_rel_path(src):
            diagnostics.append(
                _diag("invalid_workspace_source", f"CLAW.md.workspace.files[{idx}].source", f"Unsafe source {src!r}")
            )
            continue
        if not isinstance(dst, str) or not _is_safe_rel_path(dst):
            diagnostics.append(
                _diag("invalid_workspace_dest", f"CLAW.md.workspace.files[{idx}].path", f"Unsafe path {dst!r}")
            )
        if src.lower() == "package.json":
            diagnostics.append(
                _diag("project_invalid", f"CLAW.md.workspace.files[{idx}].source", "Cannot map package.json")
            )
        workspace_sources.append(src)

    for src in workspace_sources:
        target = root / src
        if target.is_symlink():
            diagnostics.append(_diag("symlink_forbidden", src, f"Workspace source {src} must not be a symlink"))
        elif not target.is_file():
            diagnostics.append(_diag("missing_workspace_source", src, f"Missing declared workspace source {src}"))
        else:
            try:
                target.resolve().relative_to(root)
            except ValueError:
                diagnostics.append(_diag("source_escapes_package", src, f"Source {src} escapes package root"))

    # mcpServers env & auth header placeholder check
    mcp_servers = manifest.get("mcpServers") or {}
    if isinstance(mcp_servers, dict):
        for srv_name, srv_cfg in mcp_servers.items():
            if not isinstance(srv_cfg, dict):
                continue
            if isinstance(srv_cfg.get("env"), dict):
                for env_k, env_v in srv_cfg["env"].items():
                    if not isinstance(env_v, str) or not ENV_PLACEHOLDER_RE.match(env_v):
                        diagnostics.append(
                            _diag(
                                "mcp_env_must_be_placeholder",
                                f"CLAW.md.mcpServers.{srv_name}.env.{env_k}",
                                f"MCP env value for {env_k} must be an unresolved '${{ENV_VAR}}' reference, never a literal value.",
                            )
                        )
            if isinstance(srv_cfg.get("headers"), dict):
                for hdr_k, hdr_v in srv_cfg["headers"].items():
                    if hdr_k.lower() in ("authorization", "x-api-key", "api-key") and (
                        not isinstance(hdr_v, str) or "${" not in hdr_v
                    ):
                        diagnostics.append(
                            _diag(
                                "mcp_header_must_use_placeholder",
                                f"CLAW.md.mcpServers.{srv_name}.headers.{hdr_k}",
                                f"MCP auth header {hdr_k} must reference an unresolved '${{ENV_VAR}}' placeholder.",
                            )
                        )

    # cronJobs schema & quiet/honesty check
    cron_jobs = manifest.get("cronJobs") or []
    if not isinstance(cron_jobs, list):
        diagnostics.append(_diag("invalid_cron_jobs", "CLAW.md.cronJobs", "cronJobs must be a list"))
        cron_jobs = []
    for idx, job in enumerate(cron_jobs):
        jpath = f"CLAW.md.cronJobs[{idx}]"
        if not isinstance(job, dict):
            diagnostics.append(_diag("invalid_cron_job", jpath, "Each cronJob must be a mapping"))
            continue
        sched = job.get("schedule")
        if not isinstance(sched, dict):
            diagnostics.append(_diag("invalid_cron_schedule", f"{jpath}.schedule", "schedule must be a mapping"))
        else:
            cron_expr = sched.get("cron")
            tz = sched.get("timezone")
            if not isinstance(cron_expr, str) or not is_valid_5_field_cron(cron_expr):
                diagnostics.append(
                    _diag("invalid_cron_expression", f"{jpath}.schedule.cron", f"Invalid 5-field cron: {cron_expr!r}")
                )
            if not isinstance(tz, str) or not tz.strip():
                diagnostics.append(
                    _diag("missing_cron_timezone", f"{jpath}.schedule.timezone", "Explicit IANA timezone required")
                )
        msg = job.get("message")
        if not isinstance(msg, str) or not msg.strip():
            diagnostics.append(_diag("missing_cron_message", f"{jpath}.message", "cronJob message must be non-empty"))
        elif strict_trust:
            if not QUIET_ON_CLEAN_RE.search(msg):
                diagnostics.append(
                    _diag(
                        "cron_missing_quiet_on_clean",
                        f"{jpath}.message",
                        "Scheduled cronJob message must instruct the agent to stay quiet/silent when nothing actionable changed.",
                    )
                )
            if not STALE_REFUSAL_RE.search(msg):
                diagnostics.append(
                    _diag(
                        "cron_missing_stale_refusal",
                        f"{jpath}.message",
                        "Scheduled cronJob message must instruct the agent to report failure explicitly instead of inventing or reusing stale data.",
                    )
                )
        delivery = job.get("delivery")
        if delivery is not None:
            if not isinstance(delivery, dict) or delivery.get("mode") not in (
                "none", "announce", "last-channel", "owner"
            ):
                diagnostics.append(
                    _diag("invalid_cron_delivery", f"{jpath}.delivery", f"Invalid delivery block: {delivery!r}")
                )

    # 3. profiles/openclaw.yml checks
    has_profile = profile_path.is_file()
    if has_profile:
        try:
            prof_bytes = profile_path.read_bytes()
            if len(prof_bytes) > MAX_PROFILE_BYTES:
                diagnostics.append(_diag("profile_too_large", "profiles/openclaw.yml", "Exceeds 256 KiB"))
            prof = parse_simple_yaml(prof_bytes.decode("utf-8"))
        except Exception as exc:
            diagnostics.append(_diag("invalid_profile_yaml", "profiles/openclaw.yml", f"YAML parse error: {exc}"))
            prof = {}
        if not isinstance(prof, dict) or prof.get("schemaVersion") != 1:
            diagnostics.append(
                _diag("invalid_profile_schema", "profiles/openclaw.yml", "profiles/openclaw.yml schemaVersion must be 1")
            )
            prof = prof if isinstance(prof, dict) else {}
        p_agent = prof.get("agent")
        if not isinstance(p_agent, dict):
            diagnostics.append(_diag("missing_profile_agent", "profiles/openclaw.yml.agent", "Missing agent block"))
        else:
            for forbidden_key in ("model", "provider", "credentials", "delegates"):
                if forbidden_key in p_agent:
                    diagnostics.append(
                        _diag(
                            "profile_forbidden_field",
                            f"profiles/openclaw.yml.agent.{forbidden_key}",
                            f"profiles/openclaw.yml cannot set {forbidden_key} (controlled by host OpenClaw policy).",
                        )
                    )
            tools_cfg = p_agent.get("tools")
            if not isinstance(tools_cfg, dict):
                diagnostics.append(
                    _diag("missing_tools_policy", "profiles/openclaw.yml.agent.tools", "Explicit tools block required")
                )
            else:
                allow_list = tools_cfg.get("allow")
                if not isinstance(allow_list, list) or len(allow_list) == 0:
                    diagnostics.append(
                        _diag(
                            "unbounded_tool_allowlist",
                            "profiles/openclaw.yml.agent.tools.allow",
                            "profiles/openclaw.yml must declare a bounded, non-empty agent.tools.allow list.",
                        )
                    )
                elif any(not isinstance(t, str) or "*" in t for t in allow_list):
                    diagnostics.append(
                        _diag(
                            "wildcard_tool_forbidden",
                            "profiles/openclaw.yml.agent.tools.allow",
                            "Wildcard ('*') tool grants are forbidden in agent.tools.allow.",
                        )
                    )
                fs_cfg = tools_cfg.get("fs")
                if not isinstance(fs_cfg, dict) or fs_cfg.get("workspaceOnly") is not True:
                    diagnostics.append(
                        _diag(
                            "workspace_only_required",
                            "profiles/openclaw.yml.agent.tools.fs.workspaceOnly",
                            "agent.tools.fs.workspaceOnly must be true.",
                        )
                    )

    # 4. OpenClaw validateTemplateProject zero-exclusion check (project.ts L378-439)
    selected_paths: list[str] = ["package.json", "CLAW.md"]
    if (root / "LICENSE").is_file():
        selected_paths.append("LICENSE")
    if (root / "BOOTSTRAP.md").is_file():
        selected_paths.append("BOOTSTRAP.md")
    if has_profile:
        selected_paths.append("profiles/openclaw.yml")
    selected_paths.extend(workspace_sources)

    portable_map: dict[str, str] = {}
    for sp in selected_paths:
        key = _portable_path_key(sp)
        prev = portable_map.get(key)
        if prev and prev != sp:
            diagnostics.append(
                _diag("project_path_collision", sp, f"Selected paths {prev!r} and {sp!r} collide on case-insensitive FS")
            )
        portable_map[key] = sp

    excluded_paths: list[str] = []
    entry_count = 0

    def walk_dir(rel_dir: str) -> None:
        nonlocal entry_count
        abs_dir = root / rel_dir if rel_dir else root
        for entry in sorted(abs_dir.iterdir(), key=lambda p: p.name):
            entry_count += 1
            if entry_count > MAX_PROJECT_ENTRIES:
                diagnostics.append(
                    _diag("project_too_many_entries", "$", f"Template exceeds {MAX_PROJECT_ENTRIES} entries")
                )
                return
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if entry.is_dir():
                if entry.name in (".git", "node_modules"):
                    excluded_paths.append(f"{rel}/")
                else:
                    walk_dir(rel)
            else:
                if _portable_path_key(rel) not in portable_map:
                    excluded_paths.append(rel)

    walk_dir("")
    if excluded_paths:
        diagnostics.append(
            _diag(
                "unlisted_excluded_files",
                "$.workspace.files",
                "Unlisted files inside template root would be silently excluded by `openclaw templates build`: "
                + ", ".join(excluded_paths),
            )
        )

    # 5. Scan all selected text files for leaked secrets & private paths
    for sp in dict.fromkeys(selected_paths):
        fpath = root / sp
        if fpath.is_file() and fpath.suffix.lower() in TEXT_SUFFIXES:
            try:
                txt = fpath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                diagnostics.append(_diag("invalid_utf8", sp, f"{sp} is not valid UTF-8"))
                continue
            diagnostics.extend(_scan_text_for_secrets_and_paths(sp, txt))

    # 6. Trust habit checks on AGENTS.md / CLAW.md body & HEARTBEAT.md
    if strict_trust:
        agents_src = (
            bootstrap_files.get("AGENTS.md", {}).get("source")
            if isinstance(bootstrap_files.get("AGENTS.md"), dict)
            else None
        )
        policy_text = body_str
        policy_label = "CLAW.md"
        if isinstance(agents_src, str) and (root / agents_src).is_file():
            policy_text = (root / agents_src).read_text(encoding="utf-8") + "\n" + body_str
            policy_label = agents_src

        if not DRAFT_GATE_RE.search(policy_text):
            diagnostics.append(
                _diag(
                    "missing_draft_first_gate",
                    policy_label,
                    f"{policy_label} must declare a draft-first / human-approval gate before external sends, posts, pushes, or publishes.",
                )
            )
        if not UNTRUSTED_BOUNDARY_RE.search(policy_text):
            diagnostics.append(
                _diag(
                    "missing_untrusted_input_boundary",
                    policy_label,
                    f"{policy_label} must declare an untrusted outside/group-chat input boundary protecting AGENTS.md/SOUL.md and gated actions.",
                )
            )

        hb_src = (
            bootstrap_files.get("HEARTBEAT.md", {}).get("source")
            if isinstance(bootstrap_files.get("HEARTBEAT.md"), dict)
            else None
        )
        if isinstance(hb_src, str) and (root / hb_src).is_file():
            hb_text = (root / hb_src).read_text(encoding="utf-8")
            if not QUIET_ON_CLEAN_RE.search(hb_text):
                diagnostics.append(
                    _diag(
                        "heartbeat_missing_quiet_on_clean",
                        hb_src,
                        f"{hb_src} must instruct scheduled checks to stay quiet/silent when nothing actionable failed.",
                    )
                )
            if not STALE_REFUSAL_RE.search(hb_text):
                diagnostics.append(
                    _diag(
                        "heartbeat_missing_stale_refusal",
                        hb_src,
                        f"{hb_src} must instruct scheduled checks to report check failures explicitly instead of reusing stale results.",
                    )
                )

    return {
        "template": tdir.name,
        "root": str(root),
        "ok": len(diagnostics) == 0,
        "selectedFileCount": len(set(selected_paths)),
        "excludedPaths": excluded_paths,
        "diagnostics": diagnostics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint OpenClaw Agent Template packages for schema compliance, zero excluded files, secret scrubs, and trust gates."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Template project directories to lint (default: all templates/*/ in repo).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report to stdout.")
    parser.add_argument(
        "--no-strict-trust",
        action="store_true",
        help="Check OpenClaw schema, zero-exclusion, and secret scrub only (skip AGENTS.md/cron trust-phrase checks).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    if args.paths:
        targets = args.paths
    else:
        templates_root = repo_root / "templates"
        if not templates_root.is_dir():
            print(f"error: default templates directory not found: {templates_root}", file=sys.stderr)
            return 2
        targets = sorted(p for p in templates_root.iterdir() if p.is_dir())

    if not targets:
        print("error: no template directories found to lint", file=sys.stderr)
        return 2

    for t in targets:
        if not t.is_dir():
            print(f"error: template directory does not exist: {t}", file=sys.stderr)
            return 2

    results = [lint_template_dir(t, strict_trust=not args.no_strict_trust) for t in targets]
    overall_ok = all(r["ok"] for r in results)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": overall_ok,
                    "templatesChecked": [r["template"] for r in results],
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        for r in results:
            status = "PASS" if r["ok"] else "FAIL"
            print(f"[{status}] {r['template']} ({r['selectedFileCount']} selected files)")
            for d in r["diagnostics"]:
                print(f"  - [{d['code']}] {d['path']}: {d['message']}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
