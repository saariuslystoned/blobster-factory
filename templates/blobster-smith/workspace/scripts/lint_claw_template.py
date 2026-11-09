#!/usr/bin/env python3
"""OpenClaw Agent Template house-rule linter & native CLI bridge.

Separates validation into two explicit layers:
1. Authoritative OpenClaw compatibility (`openclawCompatibility`):
   - Runs native `openclaw templates validate <dir> --json` automatically when `openclaw` is on `PATH`.
   - Reports `"unverified"` (never equivalent native validation) when `openclaw` is unavailable locally,
     or fails closed when `--require-openclaw` is passed.
2. Factory house rules (`factoryPolicyOk`):
   - Confined, symlink-free single regular-file inventory enforcing OpenClaw byte budgets
     (`1 MiB` per managed file, `4 MiB` aggregate workspace sources, `256 KiB` package/profile caps)
     and zero unlisted/excluded files (`excludedPaths == []`).
   - Strict block/flow YAML & manifest/profile subset checks (duplicate key rejection, literal `#`
     preservation inside block scalars, SemVer, 5-field Croner schedules, bounded tool allowlists).
   - Secret-pattern & machine-local private-path heuristics across all confined files.
   - Policy-phrase heuristics (`AGENTS.md` / `CLAW.md` draft-first outbound gate & untrusted input
     boundary; quiet-on-clean & stale-data refusal on scheduled `cronJobs` and optional `HEARTBEAT.md`).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_PACKAGE_JSON_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PROFILE_BYTES = 256 * 1024
MAX_MANAGED_FILE_BYTES = 1024 * 1024
MAX_MANAGED_WORKSPACE_BYTES = 4 * MAX_MANAGED_FILE_BYTES
MAX_BOOTSTRAP_SEED_BYTES = 2 * 1024 * 1024
MAX_TOTAL_INVENTORY_BYTES = 8 * 1024 * 1024
MAX_PROJECT_ENTRIES = 4096

ALLOWED_MANIFEST_KEYS = {
    "schemaVersion",
    "agent",
    "categories",
    "metadata",
    "workspace",
    "packages",
    "mcpServers",
    "cronJobs",
}
ALLOWED_WORKSPACE_KEYS = {"bootstrapFiles", "files"}
ALLOWED_PACKAGE_ENTRY_KEYS = {"kind", "source", "ref", "version"}
ALLOWED_CRON_JOB_KEYS = {"id", "name", "schedule", "session", "message", "delivery"}
ALLOWED_STDIO_MCP_KEYS = {"command", "transport", "args", "env", "toolFilter", "timeout", "connectTimeout"}
ALLOWED_REMOTE_MCP_KEYS = {"url", "transport", "auth", "toolFilter", "timeout", "connectTimeout"}
PORTABLE_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DANGEROUS_HOST_ENV_KEYS = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "NODE_OPTIONS",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "BASH_ENV",
    "ENV",
    "PATH",
}
PACKAGE_RUNNER_COMMANDS = {"npx", "pnpm", "yarn", "bunx", "uvx", "pipx"}
PINNED_PKG_SPEC_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(?:@|==)"
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$"
)

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PACKAGE_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")
WINDOWS_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"|?*]')
WINDOWS_RESERVED_SEGMENT_RE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE)
ALLOWED_BOOTSTRAP_FILE_NAMES = {"AGENTS.md", "SOUL.md", "IDENTITY.md", "TOOLS.md", "HEARTBEAT.md"}
CLAWHUB_TEMPLATE_CATEGORIES = {
    "personal",
    "health",
    "travel",
    "productivity",
    "research",
    "engineering",
    "governance",
    "operations",
    "finance",
    "sales",
    "product",
    "people",
}

TEXT_SUFFIXES = {
    ".md", ".json", ".yml", ".yaml", ".txt", ".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".toml", ".svg"
}

SAFE_ENV_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
FORBIDDEN_CREDENTIAL_FILENAMES = {
    ".env",
    ".netrc",
    ".git-credentials",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
FORBIDDEN_CREDENTIAL_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".p8", ".jks", ".keystore", ".kdbx"}

CRON_MONTH_ALIASES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
CRON_DOW_ALIASES = {
    "SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6,
}
CRON_MAX_DAYS_IN_MONTH = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_or_stripe_key", re.compile(r"\bsk-(?:live-|test-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b")),
    ("xai_key", re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{24,}\b")),
    ("private_key_block", re.compile(r"-{5}BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY(?: BLOCK)?-{5}")),
]

PRIVATE_PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("macos_home_path", re.compile(r"/Users/[A-Za-z0-9_][A-Za-z0-9._-]*/")),
    ("linux_home_path", re.compile(r"/home/[A-Za-z0-9_][A-Za-z0-9._-]*/")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_][A-Za-z0-9._-]*\\")),
]

DRAFT_GATE_RE = re.compile(
    r"\b(?:draft(?:-first|-only|s)?|human-gated|"
    r"(?:require\w*|await\w*|with|until|after|before)\s+(?:explicit\s+)?human(?:-|\s+)(?:gate\w*|approv\w*|confirm\w*)|"
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
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth < 0:
                    raise ValueError(f"Unbalanced closing bracket in flow YAML: {inner!r}")
            elif ch == "," and depth == 0:
                part = "".join(buf).strip()
                if not part:
                    raise ValueError(f"Empty item before comma in flow YAML: {inner!r}")
                items.append(part)
                buf = []
                continue
        buf.append(ch)
    if escaped or in_single or in_double or depth != 0:
        raise ValueError(f"Unterminated quote or bracket in flow YAML: {inner!r}")
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


_YAML_DOUBLE_ESCAPES: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "'": "'",
    "0": "\0",
    "a": "\x07",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    "_": "\xa0",
    "N": "\x85",
    "L": "\u2028",
    "P": "\u2029",
}


def _decode_double_quoted_yaml(token: str) -> str:
    if len(token) < 2 or not token.startswith('"'):
        raise ValueError(f"Invalid double-quoted YAML scalar: {token!r}")
    out: list[str] = []
    idx = 1
    while idx < len(token):
        ch = token[idx]
        if ch == '"':
            if idx != len(token) - 1:
                raise ValueError(f"Trailing characters after double-quoted YAML scalar: {token!r}")
            return "".join(out)
        if ch == "\\":
            idx += 1
            if idx >= len(token):
                raise ValueError(f"Unterminated escape in double-quoted YAML scalar: {token!r}")
            esc = token[idx]
            if esc in _YAML_DOUBLE_ESCAPES:
                out.append(_YAML_DOUBLE_ESCAPES[esc])
                idx += 1
            elif esc == "x" and idx + 2 < len(token):
                out.append(chr(int(token[idx + 1 : idx + 3], 16)))
                idx += 3
            elif esc == "u" and idx + 4 < len(token):
                cp = int(token[idx + 1 : idx + 5], 16)
                out.append(chr(cp))
                idx += 5
            elif esc == "U" and idx + 8 < len(token):
                cp = int(token[idx + 1 : idx + 9], 16)
                out.append(chr(cp))
                idx += 9
            else:
                raise ValueError(f"Unsupported escape \\{esc} in YAML scalar: {token!r}")
        else:
            out.append(ch)
            idx += 1
    raise ValueError(f"Unterminated double-quoted YAML scalar: {token!r}")


def _decode_single_quoted_yaml(token: str) -> str:
    if len(token) < 2 or not token.startswith("'"):
        raise ValueError(f"Invalid single-quoted YAML scalar: {token!r}")
    out: list[str] = []
    idx = 1
    while idx < len(token):
        ch = token[idx]
        if ch == "'":
            if idx + 1 < len(token) and token[idx + 1] == "'":
                out.append("'")
                idx += 2
                continue
            if idx != len(token) - 1:
                raise ValueError(f"Trailing characters after single-quoted YAML scalar: {token!r}")
            return "".join(out)
        out.append(ch)
        idx += 1
    raise ValueError(f"Unterminated single-quoted YAML scalar: {token!r}")


def _matching_flow_end(token: str, open_ch: str, close_ch: str) -> int:
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(token):
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
        elif not in_single and not in_double:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return idx
    return -1


def _parse_scalar(token: str) -> Any:
    t = token.strip()
    if t == "" or t in ("null", "Null", "NULL", "~"):
        return None
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if t.startswith('"'):
        return _decode_double_quoted_yaml(t)
    if t.startswith("'"):
        return _decode_single_quoted_yaml(t)
    if t.startswith("["):
        if _matching_flow_end(t, "[", "]") != len(t) - 1:
            raise ValueError(f"Invalid flow sequence in YAML: {t!r}")
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in _split_flow_items(inner)]
    if t.startswith("{"):
        if _matching_flow_end(t, "{", "}") != len(t) - 1:
            raise ValueError(f"Invalid flow mapping in YAML: {t!r}")
        inner = t[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for entry in _split_flow_items(inner):
            k, sep, v = _split_key_val(entry, in_flow=True)
            if not sep:
                raise ValueError(f"Invalid inline YAML mapping entry: {entry!r}")
            if k in out:
                raise ValueError(f"Duplicate YAML key {k!r} in inline mapping")
            out[k] = _parse_scalar(v)
        return out
    if t[0] in ("&", "*", "!", "]", "}", ",", "|", ">", "%", "@", "`"):
        raise ValueError(f"Unsupported or invalid YAML token: {t!r}")
    for idx, ch in enumerate(t):
        if ch == ":" and (idx + 1 == len(t) or t[idx + 1].isspace()):
            raise ValueError(f"Unquoted colon in plain YAML scalar must be quoted: {t!r}")
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return t


def _split_key_val(text: str, *, in_flow: bool = False) -> tuple[str, bool, str]:
    in_single = False
    in_double = False
    escaped = False
    depth = 0
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
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth = max(0, depth - 1)
            elif ch == ":" and depth == 0:
                raw_prefix = text[:idx].strip()
                quoted_key_adjacent = (
                    in_flow
                    and len(raw_prefix) >= 2
                    and raw_prefix[0] in ('"', "'")
                    and raw_prefix[-1] == raw_prefix[0]
                )
                if idx + 1 == len(text) or text[idx + 1].isspace() or quoted_key_adjacent:
                    if not raw_prefix:
                        raise ValueError(f"Empty YAML mapping key in {text!r}")
                    if raw_prefix[0] in ('"', "'"):
                        parsed_k = _parse_scalar(raw_prefix)
                        if not isinstance(parsed_k, str):
                            raise ValueError(f"Invalid quoted YAML key: {raw_prefix!r}")
                        k = parsed_k
                    else:
                        if raw_prefix[0] in ("&", "*", "!", "[", "]", "{", "}", ",", "|", ">", "%", "@", "`"):
                            raise ValueError(f"Unsupported or invalid YAML key: {raw_prefix!r}")
                        k = raw_prefix
                    if k == "<<":
                        raise ValueError("YAML merge keys ('<<') are unsupported; must map directly to JSON data")
                    return k, True, text[idx + 1 :].strip()
    return text.strip(), False, ""


_BLOCK_SCALAR_HEADER_RE = re.compile(r"^([|>])(?:([+-])([1-9])?|([1-9])([+-])?)?$")


def _fold_yaml_block_lines(lines: list[str]) -> str:
    """Fold non-empty YAML '>' scalar lines while preserving blank lines and more-indented lines."""
    leading_empty = 0
    while leading_empty < len(lines) and lines[leading_empty] == "":
        leading_empty += 1
    parts: list[str] = ["\n" * leading_empty] if leading_empty else []
    prev_more_indented: bool | None = None
    empty_run = 0
    for line in lines[leading_empty:]:
        if line == "":
            empty_run += 1
            continue
        cur_more_indented = line[0] in (" ", "\t")
        if prev_more_indented is not None:
            if not prev_more_indented and not cur_more_indented:
                parts.append(" " if empty_run == 0 else ("\n" * empty_run))
            else:
                parts.append("\n" * (empty_run + 1))
        parts.append(line)
        prev_more_indented = cur_more_indented
        empty_run = 0
    return "".join(parts)


def _parse_block_scalar(
    raw_lines: list[str],
    start_idx: int,
    parent_indent: int,
    header: str,
) -> tuple[str, int]:
    """Parse a YAML '|' or '>' block scalar without stripping '#' comments inside the scalar body."""
    m = _BLOCK_SCALAR_HEADER_RE.match(header)
    if not m:
        raise ValueError(f"Invalid YAML block scalar header: {header!r}")
    style = m.group(1)
    chomp = m.group(2) or m.group(5) or ""
    indent_tok = m.group(3) or m.group(4)
    min_indent = max(0, parent_indent + 1)
    block_indent: int | None = (max(0, parent_indent) + int(indent_tok)) if indent_tok else None

    collected: list[tuple[int, str]] = []
    idx = start_idx
    while idx < len(raw_lines):
        raw = raw_lines[idx]
        sp = len(raw) - len(raw.lstrip(" "))
        rest = raw[sp:]
        if rest == "":
            collected.append((sp, raw))
            idx += 1
            continue
        if sp < min_indent:
            if rest.startswith("\t"):
                raise ValueError("YAML indentation must use spaces, not tabs")
            break
        if block_indent is None:
            if any(prev_sp > sp for prev_sp, _ in collected):
                raise ValueError("Leading spaces-only line in YAML block scalar exceeds block indentation")
            block_indent = sp
        elif sp < block_indent:
            if rest.startswith("\t"):
                raise ValueError("YAML indentation must use spaces, not tabs")
            raise ValueError("Inconsistent indentation inside YAML block scalar")
        collected.append((sp, raw))
        idx += 1

    if block_indent is None:
        return ("\n" * len(collected) if chomp == "+" else ""), idx

    lines_with_blank_flag: list[tuple[bool, str]] = []
    for sp, raw in collected:
        if sp >= block_indent:
            body_line = raw[block_indent:]
            lines_with_blank_flag.append((body_line == "", body_line))
        else:
            lines_with_blank_flag.append((True, ""))

    last_non_blank = -1
    for pos in range(len(lines_with_blank_flag) - 1, -1, -1):
        if not lines_with_blank_flag[pos][0]:
            last_non_blank = pos
            break

    if last_non_blank == -1:
        return ("\n" * len(lines_with_blank_flag) if chomp == "+" else ""), idx

    active_lines = [s for _, s in lines_with_blank_flag[: last_non_blank + 1]]
    trailing_blanks = len(lines_with_blank_flag) - (last_non_blank + 1)
    core = "\n".join(active_lines) if style == "|" else _fold_yaml_block_lines(active_lines)
    if chomp == "-":
        suffix = ""
    elif chomp == "+":
        suffix = "\n" * (1 + trailing_blanks)
    else:
        suffix = "\n"
    return core + suffix, idx


def _flow_bracket_balance(text: str) -> int:
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    for ch in text:
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
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
    return depth


def parse_simple_yaml(text: str) -> Any:
    """Parse the clean block/flow YAML subset used in CLAW.md and profiles/openclaw.yml."""
    raw_lines = text.removeprefix("\ufeff").splitlines()

    def inspect_code_line(raw: str) -> tuple[int, str, str] | None:
        cleaned = _strip_yaml_comment(raw)
        if not cleaned.strip():
            return None
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        if cleaned[indent : indent + 1] == "\t":
            raise ValueError("YAML indentation must use spaces, not tabs")
        return indent, cleaned.strip(), cleaned

    def next_code_line(idx: int) -> int:
        while idx < len(raw_lines):
            if inspect_code_line(raw_lines[idx]) is not None:
                return idx
            idx += 1
        return idx

    start = next_code_line(0)
    if start < len(raw_lines):
        first_ind, first_txt, _ = inspect_code_line(raw_lines[start]) or (0, "", "")
        if first_ind == 0 and first_txt == "---":
            start = next_code_line(start + 1)

    end_limit = len(raw_lines)
    probe = start
    while probe < len(raw_lines):
        info = inspect_code_line(raw_lines[probe])
        if info is not None:
            p_ind, p_txt, _ = info
            if p_ind == 0 and p_txt == "---":
                raise ValueError("Multiple YAML documents are unsupported")
            if p_ind == 0 and p_txt == "...":
                after_end = next_code_line(probe + 1)
                if after_end < len(raw_lines):
                    raise ValueError("Trailing content after YAML '...' document end marker")
                end_limit = probe
                break
        probe += 1

    raw_lines = raw_lines[:end_limit]
    if start >= len(raw_lines):
        return {}

    def collect_flow_scalar(line_idx: int, min_cont_indent: int, initial: str) -> tuple[Any, int]:
        parts = [initial]
        balance = _flow_bracket_balance(initial)
        cur = line_idx + 1
        while balance > 0:
            cur = next_code_line(cur)
            if cur >= len(raw_lines):
                raise ValueError(f"Unterminated multiline flow YAML starting with {initial!r}")
            c_info = inspect_code_line(raw_lines[cur])
            assert c_info is not None
            c_ind, c_txt, _ = c_info
            if c_ind < min_cont_indent:
                raise ValueError(f"Under-indented multiline flow YAML continuation at {c_txt!r}")
            parts.append(c_txt)
            balance += _flow_bracket_balance(c_txt)
            cur += 1
        return _parse_scalar(" ".join(parts)), cur

    def parse_mapping_value(line_idx: int, key_indent: int, v: str) -> tuple[Any, int]:
        if _BLOCK_SCALAR_HEADER_RE.match(v):
            return _parse_block_scalar(raw_lines, line_idx + 1, key_indent, v)
        if v.startswith(("|", ">")):
            raise ValueError(f"Invalid YAML block scalar header: {v!r}")
        if v == "":
            nxt = next_code_line(line_idx + 1)
            if nxt < len(raw_lines):
                n_info = inspect_code_line(raw_lines[nxt])
                assert n_info is not None
                n_ind, n_txt, _ = n_info
                if n_ind > key_indent:
                    return parse_block(nxt, n_ind)
                if n_ind == key_indent and (n_txt == "-" or n_txt.startswith("- ")):
                    return parse_sequence(nxt, key_indent)
            return None, nxt
        if v.startswith(("[", "{")) and _flow_bracket_balance(v) > 0:
            return collect_flow_scalar(line_idx, key_indent + 1, v)
        return _parse_scalar(v), line_idx + 1

    def parse_mapping_entries(idx: int, exact_indent: int, mapping: dict[str, Any]) -> int:
        while True:
            idx = next_code_line(idx)
            if idx >= len(raw_lines):
                break
            info = inspect_code_line(raw_lines[idx])
            assert info is not None
            ind, txt, _ = info
            if ind < exact_indent:
                break
            if ind > exact_indent:
                raise ValueError(f"Unexpected indentation at {txt!r}")
            if txt == "-" or txt.startswith("- "):
                break
            k, has_colon, v = _split_key_val(txt)
            if not has_colon:
                raise ValueError(f"Expected key: value in YAML at {txt!r}")
            if k in mapping:
                raise ValueError(f"Duplicate YAML key: {k!r}")
            val, idx = parse_mapping_value(idx, exact_indent, v)
            mapping[k] = val
        return idx

    def parse_sequence(idx: int, seq_indent: int) -> tuple[list[Any], int]:
        arr: list[Any] = []
        while True:
            idx = next_code_line(idx)
            if idx >= len(raw_lines):
                break
            info = inspect_code_line(raw_lines[idx])
            assert info is not None
            ind, txt, cleaned = info
            if ind < seq_indent:
                break
            if ind > seq_indent:
                raise ValueError(f"Unexpected indentation in YAML sequence at {txt!r}")
            if not (txt == "-" or txt.startswith("- ")):
                break
            if txt == "-":
                nxt = next_code_line(idx + 1)
                if nxt >= len(raw_lines):
                    arr.append(None)
                    idx = nxt
                else:
                    n_info = inspect_code_line(raw_lines[nxt])
                    assert n_info is not None
                    n_ind, _, _ = n_info
                    if n_ind > seq_indent:
                        val, idx = parse_block(nxt, n_ind)
                        arr.append(val)
                    else:
                        arr.append(None)
                        idx = nxt
                continue

            after_dash = cleaned[seq_indent + 1 :]
            spaces_after_dash = len(after_dash) - len(after_dash.lstrip(" "))
            if after_dash[spaces_after_dash : spaces_after_dash + 1] == "\t":
                raise ValueError("YAML indentation must use spaces, not tabs")
            item_indent = seq_indent + 1 + spaces_after_dash
            rest = after_dash[spaces_after_dash:].strip()

            if _BLOCK_SCALAR_HEADER_RE.match(rest):
                val, idx = _parse_block_scalar(raw_lines, idx + 1, seq_indent, rest)
                arr.append(val)
            elif rest.startswith(("|", ">")):
                raise ValueError(f"Invalid YAML block scalar header: {rest!r}")
            else:
                k, has_colon, v = _split_key_val(rest)
                if has_colon:
                    item_map: dict[str, Any] = {}
                    first_val, idx = parse_mapping_value(idx, item_indent, v)
                    item_map[k] = first_val
                    nxt = next_code_line(idx)
                    if nxt < len(raw_lines):
                        n_info = inspect_code_line(raw_lines[nxt])
                        assert n_info is not None
                        n_ind, _, _ = n_info
                        if n_ind > seq_indent and n_ind != item_indent:
                            raise ValueError(f"Misaligned YAML mapping key inside sequence item at {n_info[1]!r}")
                        if n_ind == item_indent:
                            idx = parse_mapping_entries(nxt, item_indent, item_map)
                    arr.append(item_map)
                elif rest.startswith(("[", "{")) and _flow_bracket_balance(rest) > 0:
                    val, idx = collect_flow_scalar(idx, seq_indent + 1, rest)
                    arr.append(val)
                else:
                    arr.append(_parse_scalar(rest))
                    idx += 1
        return arr, idx

    def parse_block(idx: int, min_indent: int) -> tuple[Any, int]:
        idx = next_code_line(idx)
        if idx >= len(raw_lines):
            return {}, idx
        info = inspect_code_line(raw_lines[idx])
        assert info is not None
        cur_indent, cur_text, _ = info
        if cur_indent < min_indent:
            return {}, idx
        if _BLOCK_SCALAR_HEADER_RE.match(cur_text):
            return _parse_block_scalar(raw_lines, idx + 1, cur_indent - 1, cur_text)
        if cur_text == "-" or cur_text.startswith("- "):
            return parse_sequence(idx, cur_indent)
        k, has_colon, _ = _split_key_val(cur_text)
        if has_colon:
            mapping: dict[str, Any] = {}
            idx = parse_mapping_entries(idx, cur_indent, mapping)
            return mapping, idx
        if cur_text.startswith(("[", "{")) and _flow_bracket_balance(cur_text) > 0:
            return collect_flow_scalar(idx, cur_indent, cur_text)
        return _parse_scalar(cur_text), idx + 1

    first_info = inspect_code_line(raw_lines[start])
    assert first_info is not None
    result, next_idx = parse_block(start, first_info[0])
    trailing = next_code_line(next_idx)
    if trailing < len(raw_lines):
        t_info = inspect_code_line(raw_lines[trailing])
        assert t_info is not None
        raise ValueError(f"Trailing unparsed YAML at {t_info[1]!r}")
    return result


def _parse_cron_field(
    field: str,
    min_val: int,
    max_val: int,
    aliases: dict[str, int] | None = None,
    *,
    sunday_upper_seven: bool = False,
    max_step: int | None = None,
    dom_modifiers: bool = False,
    dow_modifiers: bool = False,
) -> set[int] | None:
    """Validate and expand a single cron field matching OpenClaw's Croner 5-field grammar."""
    if not field:
        return None
    normalized = field.replace("?", "*")
    if dow_modifiers and normalized.startswith("+"):
        normalized = normalized[1:]
        if not normalized:
            return None
    segments = normalized.split(",")
    if any(not seg for seg in segments):
        return None

    def parse_atom(token: str, *, is_range_upper: bool = False) -> int | None:
        if is_range_upper and sunday_upper_seven and token.upper() == "SUN":
            return 7
        if aliases and token.upper() in aliases:
            return aliases[token.upper()]
        if re.fullmatch(r"\d+", token):
            val = int(token)
            if min_val <= val <= max_val:
                return val
        return None

    step_limit = max_step if max_step is not None else (max_val - min_val + 1)
    out: set[int] = set()
    for raw_seg in segments:
        seg = raw_seg
        if dom_modifiers:
            up = seg.upper()
            if up in ("L", "LW"):
                out.add(28)
                continue
            if up.endswith("W"):
                if "/" in seg or "-" in seg or not re.fullmatch(r"\d+", seg[:-1]):
                    return None
                w_day = int(seg[:-1])
                if not (min_val <= w_day <= max_val):
                    return None
                out.add(w_day)
                continue
        if dow_modifiers:
            if "#" in seg:
                nth_parts = seg.split("#")
                if len(nth_parts) != 2 or not re.fullmatch(r"[1-5Ll]", nth_parts[1]):
                    return None
                seg = nth_parts[0]
            if not seg:
                return None

        if "/" in seg:
            slash_parts = seg.split("/")
            if len(slash_parts) != 2:
                return None
            base, step_str = slash_parts
            if not re.fullmatch(r"\d+", step_str):
                return None
            step = int(step_str)
            if step < 1 or step > step_limit:
                return None
            if base == "*":
                lo, hi = min_val, max_val
            elif "-" in base:
                range_parts = base.split("-")
                if len(range_parts) != 2:
                    return None
                lo_v = parse_atom(range_parts[0])
                hi_v = parse_atom(range_parts[1], is_range_upper=True)
                if lo_v is None or hi_v is None or lo_v > hi_v:
                    return None
                lo, hi = lo_v, hi_v
            else:
                # Croner forbids numeric-prefix stepping ('5/15'); require '*/step' or 'min-max/step'.
                return None
            out.update(range(lo, hi + 1, step))
        else:
            if seg == "*":
                out.update(range(min_val, max_val + 1))
            elif "-" in seg:
                range_parts = seg.split("-")
                if len(range_parts) != 2:
                    return None
                lo_v = parse_atom(range_parts[0])
                hi_v = parse_atom(range_parts[1], is_range_upper=True)
                if lo_v is None or hi_v is None or lo_v > hi_v:
                    return None
                out.update(range(lo_v, hi_v + 1))
            else:
                v = parse_atom(seg)
                if v is None:
                    return None
                out.add(v)
    return out if out else None


def is_valid_5_field_cron(expr: str) -> bool:
    """Validate a 5-field cron schedule (minute hour day-of-month month day-of-week)."""
    if not expr or expr != expr.strip():
        return False
    parts = expr.split()
    if len(parts) != 5:
        return False
    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    doms = _parse_cron_field(parts[2], 1, 31, dom_modifiers=True)
    months = _parse_cron_field(parts[3], 1, 12, aliases=CRON_MONTH_ALIASES)
    dows = _parse_cron_field(
        parts[4],
        0,
        7,
        aliases=CRON_DOW_ALIASES,
        sunday_upper_seven=True,
        max_step=7,
        dow_modifiers=True,
    )
    if any(f is None for f in (minutes, hours, doms, months, dows)):
        return False
    assert doms is not None and months is not None
    # Reject impossible calendar schedules such as Feb 31 ('0 0 31 2 *') or Apr 31 ('0 0 31 4 *').
    if not any(day <= CRON_MAX_DAYS_IN_MONTH[month] for month in months for day in doms):
        return False
    return True


def is_valid_iana_timezone(tz: str) -> bool:
    cleaned = tz.strip()
    if not cleaned or cleaned != tz:
        return False
    try:
        ZoneInfo(cleaned)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


def _is_forbidden_credential_file(rel_path: str) -> bool:
    p = Path(rel_path)
    name = p.name.lower()
    suffix = p.suffix.lower()
    if name in SAFE_ENV_TEMPLATE_NAMES:
        return False
    if name in FORBIDDEN_CREDENTIAL_FILENAMES:
        return True
    if name.startswith(".env."):
        return True
    if suffix in FORBIDDEN_CREDENTIAL_SUFFIXES:
        return True
    return False


_NEGATION_GUARD_RE = re.compile(
    r"\b(?:never|not|cannot|can't|must\s+not|do\s+not|don't|refuse\w*|forbid\w*|prohibit\w*)\b",
    re.IGNORECASE,
)
_UNSAFE_TRUST_SENTENCE_RE = re.compile(
    r"\b(?:skip|bypass|ignore|no\s+need\s+for)\s+(?:explicit\s+)?human(?:-|\s+)(?:gate\w*|approv\w*|confirm\w*)\b"
    r"|\b(?:always\s+)?(?:obey|trust|execute)\s+untrusted(?:\s+(?:input|data|message|content))?\b",
    re.IGNORECASE,
)


def _has_negated_trust_sentence(text: str) -> bool:
    for sentence in re.split(r"\r?\n|[.!?]+(?=\s|$)", text):
        if _UNSAFE_TRUST_SENTENCE_RE.search(sentence) and not _NEGATION_GUARD_RE.search(sentence):
            return True
    return False


def _portable_path_key(rel_path: str) -> str:
    return unicodedata.normalize("NFC", rel_path.replace("\\", "/")).lower()


def _project_path_key(rel_path: str, case_insensitive: bool) -> str:
    norm = unicodedata.normalize("NFC", rel_path.replace("\\", "/"))
    return norm.lower() if case_insensitive else norm


def _is_case_insensitive_fs(root: Path) -> bool:
    try:
        s1 = (root / "CLAW.md").lstat()
        s2 = (root / "claw.md").lstat()
        return s1.st_dev == s2.st_dev and s1.st_ino == s2.st_ino
    except OSError:
        return False


def _is_safe_rel_path(rel_path: str) -> bool:
    if not rel_path or "\\" in rel_path:
        return False
    if rel_path.startswith("/") or re.match(r"^[A-Za-z]:/", rel_path):
        return False
    for part in rel_path.split("/"):
        if part in ("", ".", ".."):
            return False
        if WINDOWS_INVALID_PATH_CHARS_RE.search(part):
            return False
        if any(ord(ch) <= 0x1F for ch in part):
            return False
        if part.endswith(".") or part.endswith(" "):
            return False
        if WINDOWS_RESERVED_SEGMENT_RE.match(part):
            return False
    return True


def _has_symlink_component(root: Path, rel_path: str) -> bool:
    cur = root
    for part in [p for p in rel_path.split("/") if p]:
        cur = cur / part
        if cur.is_symlink():
            return True
    return False


def _read_bounded_regular_file(
    root: Path,
    rel_path: str,
    max_bytes: int,
    *,
    reject_hardlinks: bool = True,
) -> tuple[bytes | None, str | None, str | None]:
    """Read a confined, non-symlink regular file up to max_bytes without unbounded memory reads."""
    if _has_symlink_component(root, rel_path):
        return None, "symlink_forbidden", f"{rel_path} must not be or traverse a symlink"
    target = root / rel_path
    try:
        st = target.lstat()
    except FileNotFoundError:
        return None, "missing", f"Missing file {rel_path}"
    except OSError as exc:
        return None, "read_failed", f"Could not stat {rel_path}: {exc}"
    if not stat.S_ISREG(st.st_mode):
        return None, "not_regular_file", f"{rel_path} must be a regular file"
    if reject_hardlinks and st.st_nlink > 1:
        return None, "hardlink_forbidden", f"{rel_path} must not have multiple hardlinks"
    try:
        target.resolve().relative_to(root)
    except ValueError:
        return None, "source_escapes_package", f"{rel_path} escapes package root"
    if st.st_size > max_bytes:
        return None, "file_too_large", f"{rel_path} ({st.st_size} bytes) exceeds {max_bytes} byte limit"
    try:
        with target.open("rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        return None, "read_failed", f"Could not read {rel_path}: {exc}"
    if len(data) > max_bytes:
        return None, "file_too_large", f"{rel_path} exceeds {max_bytes} byte limit"
    return data, None, None


def _conflicts_with_template_path(targets: set[str], candidate: str) -> bool:
    for target in targets:
        if target == candidate or target.startswith(f"{candidate}/") or candidate.startswith(f"{target}/"):
            return True
    return False


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


def _is_pinned_package_manager_mcp(command: str, args: list[Any]) -> bool:
    cmd_base = Path(command.strip()).name.lower()
    if cmd_base not in PACKAGE_RUNNER_COMMANDS:
        return True
    str_args = [a.strip() for a in args if isinstance(a, str) and a.strip()]
    non_flag = [a for a in str_args if not a.startswith("-")]
    if cmd_base in ("pnpm", "yarn") and non_flag and non_flag[0] == "dlx":
        non_flag = non_flag[1:]
    if cmd_base == "pipx" and non_flag and non_flag[0] == "run":
        non_flag = non_flag[1:]
    if not non_flag:
        return False
    return bool(PINNED_PKG_SPEC_RE.match(non_flag[0]))


def _run_native_openclaw_validate(root: Path) -> tuple[str, list[dict[str, str]]]:
    """Run authoritative `openclaw templates validate <dir> --json` when `openclaw` is installed."""
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        return "unverified", []
    try:
        proc = subprocess.run(
            [openclaw_bin, "templates", "validate", str(root), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        return "failed", [
            _diag("openclaw_native_validation_failed", "$", f"Failed executing openclaw CLI: {exc}")
        ]

    raw_out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    payload: Any = None
    if raw_out:
        try:
            payload = json.loads(raw_out)
        except json.JSONDecodeError:
            payload = None

    if (
        proc.returncode == 0
        and isinstance(payload, dict)
        and payload.get("ok") is True
        and not payload.get("excludedPaths")
        and not payload.get("diagnostics")
    ):
        return "verified", []

    diags: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for item in payload.get("diagnostics") or []:
            if isinstance(item, dict):
                diags.append(
                    _diag(
                        f"openclaw_native_{item.get('code', 'diagnostic')}",
                        str(item.get("path", "$")),
                        str(item.get("message", "OpenClaw native template validation failed.")),
                    )
                )
        err_obj = payload.get("error")
        if isinstance(err_obj, dict) and not diags:
            diags.append(
                _diag(
                    f"openclaw_native_{err_obj.get('code', 'error')}",
                    "$",
                    str(err_obj.get("message", "OpenClaw native template validation failed.")),
                )
            )
        if payload.get("excludedPaths"):
            diags.append(
                _diag(
                    "openclaw_native_excluded_paths",
                    "$.workspace.files",
                    "Native OpenClaw reported excludedPaths: " + ", ".join(map(str, payload["excludedPaths"])),
                )
            )
    if not diags:
        snippet = raw_out.splitlines()[0] if raw_out else f"exit code {proc.returncode}"
        diags.append(
            _diag("openclaw_native_validation_failed", "$", f"openclaw templates validate failed: {snippet}")
        )
    return "failed", diags


def lint_template_dir(
    tdir: Path,
    *,
    strict_trust: bool = True,
    openclaw_mode: str = "auto",
) -> dict[str, Any]:
    """Lint a single OpenClaw Agent Template directory and return structured diagnostics."""
    diagnostics: list[dict[str, str]] = []
    if tdir.is_symlink():
        diagnostics.append(_diag("symlink_forbidden", "$", "Template root directory must not be a symlink"))
        return {
            "template": tdir.name,
            "root": str(tdir),
            "ok": False,
            "factoryPolicyOk": False,
            "openclawCompatibility": "unverified",
            "selectedFileCount": 0,
            "excludedPaths": [],
            "diagnostics": diagnostics,
        }

    root = tdir.resolve()
    inventory_bytes: dict[str, bytes] = {}
    decoded_utf8_by_rel: dict[str, str] = {}
    rejected_paths: set[str] = set()

    def early_failure() -> dict[str, Any]:
        return {
            "template": tdir.name,
            "root": str(root),
            "ok": False,
            "factoryPolicyOk": False,
            "openclawCompatibility": "unverified",
            "selectedFileCount": 0,
            "excludedPaths": [],
            "diagnostics": diagnostics,
        }

    # 1. package.json checks (confined, bounded regular file)
    pkg_bytes, pkg_err, pkg_msg = _read_bounded_regular_file(root, "package.json", MAX_PACKAGE_JSON_BYTES)
    if pkg_bytes is None:
        code = "missing_package_json" if pkg_err == "missing" else ("package_too_large" if pkg_err == "file_too_large" else (pkg_err or "invalid_package_json"))
        diagnostics.append(_diag(code, "package.json", pkg_msg or "Unreadable package.json"))
        return early_failure()
    inventory_bytes["package.json"] = pkg_bytes

    claw_bytes, claw_err, claw_msg = _read_bounded_regular_file(root, "CLAW.md", MAX_MANIFEST_BYTES)
    if claw_bytes is None:
        code = "missing_claw_md" if claw_err == "missing" else ("manifest_too_large" if claw_err == "file_too_large" else (claw_err or "invalid_claw_md"))
        diagnostics.append(_diag(code, "CLAW.md", claw_msg or "Unreadable CLAW.md"))
        return early_failure()
    inventory_bytes["CLAW.md"] = claw_bytes

    try:
        pkg_text = pkg_bytes.decode("utf-8")
        decoded_utf8_by_rel["package.json"] = pkg_text
        pkg = json.loads(pkg_text)
    except Exception as exc:
        diagnostics.append(_diag("invalid_package_json", "package.json", f"Invalid UTF-8 JSON: {exc}"))
        return early_failure()

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
        if b"\0" in claw_bytes:
            raise UnicodeDecodeError("utf-8", claw_bytes, 0, 1, "NUL byte forbidden")
        claw_text = claw_bytes.decode("utf-8")
        decoded_utf8_by_rel["CLAW.md"] = claw_text
    except Exception as exc:
        diagnostics.append(_diag("invalid_claw_utf8", "CLAW.md", f"CLAW.md must be valid UTF-8: {exc}"))
        return early_failure()

    claw_text_clean = claw_text.removeprefix("\ufeff")
    m = re.match(r"^---\r?\n(?:([\s\S]*?)\r?\n)?---(?:\r?\n([\s\S]*))?$", claw_text_clean)
    if not m:
        diagnostics.append(
            _diag("missing_template_frontmatter", "CLAW.md", "CLAW.md must start with --- YAML frontmatter ---")
        )
        return early_failure()

    fm_str, body_str = (m.group(1) or ""), (m.group(2) or "").strip()
    try:
        manifest = parse_simple_yaml(fm_str)
    except Exception as exc:
        diagnostics.append(_diag("invalid_manifest_yaml", "CLAW.md", f"YAML parse failure: {exc}"))
        return early_failure()

    if not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int or manifest.get("schemaVersion") != 1:
        diagnostics.append(_diag("invalid_schema_version", "CLAW.md.schemaVersion", "CLAW.md schemaVersion must be 1"))
        manifest = manifest if isinstance(manifest, dict) else {}

    unknown_manifest_keys = sorted(set(manifest.keys()) - ALLOWED_MANIFEST_KEYS)
    for uk in unknown_manifest_keys:
        diagnostics.append(
            _diag("unknown_manifest_field", f"CLAW.md.{uk}", f"Unsupported CLAW.md frontmatter key {uk!r}")
        )

    agent_cfg = manifest.get("agent")
    if not isinstance(agent_cfg, dict):
        diagnostics.append(_diag("missing_agent_block", "CLAW.md.agent", "CLAW.md must declare an agent mapping"))
        agent_cfg = {}
    else:
        aid = agent_cfg.get("id")
        aname = agent_cfg.get("name")
        if not isinstance(aid, str) or not AGENT_ID_RE.match(aid):
            diagnostics.append(_diag("invalid_agent_id", "CLAW.md.agent.id", f"Invalid agent.id: {aid!r}"))
        if not isinstance(aname, str) or not aname.strip() or aname != aname.strip():
            diagnostics.append(
                _diag(
                    "invalid_agent_name",
                    "CLAW.md.agent.name",
                    "agent.name must be a non-empty string without leading or trailing whitespace",
                )
            )

    if "categories" in manifest:
        cats = manifest.get("categories")
        if (
            not isinstance(cats, list)
            or not (1 <= len(cats) <= 3)
            or any(not isinstance(c, str) for c in cats)
            or len(set(cats)) != len(cats)
        ):
            diagnostics.append(
                _diag(
                    "invalid_categories",
                    "CLAW.md.categories",
                    "CLAW.md categories must be 1 to 3 unique lowercase ClawHub category slugs.",
                )
            )
        else:
            unsupported_cats = [c for c in cats if c not in CLAWHUB_TEMPLATE_CATEGORIES]
            if unsupported_cats:
                diagnostics.append(
                    _diag(
                        "invalid_categories",
                        "CLAW.md.categories",
                        f"Unsupported ClawHub template category slug(s) {unsupported_cats}; allowed: {sorted(CLAWHUB_TEMPLATE_CATEGORIES)}",
                    )
                )

    if "metadata" in manifest:
        metadata_cfg = manifest.get("metadata")
        if not isinstance(metadata_cfg, dict) or any(
            not isinstance(mk, str) or not mk.strip() or mk != mk.strip() or not isinstance(mv, str)
            for mk, mv in metadata_cfg.items()
        ):
            diagnostics.append(
                _diag("invalid_metadata", "CLAW.md.metadata", "metadata must be a mapping of trimmed string keys to string values")
            )
        elif "openclaw.config" in metadata_cfg:
            diagnostics.append(
                _diag(
                    "deprecated_openclaw_profile_pointer",
                    "CLAW.md.metadata.openclaw.config",
                    "Remove deprecated metadata.openclaw.config pointer; OpenClaw discovers profiles/openclaw.yml automatically.",
                )
            )

    workspace_cfg = manifest["workspace"] if "workspace" in manifest else {}
    if not isinstance(workspace_cfg, dict):
        diagnostics.append(_diag("invalid_workspace", "CLAW.md.workspace", "workspace must be a mapping"))
        workspace_cfg = {}
    else:
        for uk in sorted(set(workspace_cfg.keys()) - ALLOWED_WORKSPACE_KEYS):
            diagnostics.append(
                _diag("unknown_workspace_field", f"CLAW.md.workspace.{uk}", f"Unsupported workspace key {uk!r}")
            )

    bootstrap_files = workspace_cfg["bootstrapFiles"] if "bootstrapFiles" in workspace_cfg else {}
    if not isinstance(bootstrap_files, dict):
        diagnostics.append(_diag("invalid_bootstrap_files", "CLAW.md.workspace.bootstrapFiles", "Must be a mapping"))
        bootstrap_files = {}

    workspace_sources: list[str] = []
    workspace_targets: set[str] = set()
    declared_bootstrap_sources: dict[str, str] = {}
    for bname, bentry in bootstrap_files.items():
        if bname not in ALLOWED_BOOTSTRAP_FILE_NAMES:
            diagnostics.append(
                _diag(
                    "invalid_bootstrap_file_name",
                    f"CLAW.md.workspace.bootstrapFiles.{bname}",
                    f"Unsupported bootstrap file {bname!r}; allowed: {sorted(ALLOWED_BOOTSTRAP_FILE_NAMES)}",
                )
            )
        if not isinstance(bentry, dict) or set(bentry.keys()) != {"source"}:
            diagnostics.append(
                _diag("invalid_bootstrap_source", f"CLAW.md.workspace.bootstrapFiles.{bname}", "Must map only {source}")
            )
            continue
        src = bentry.get("source")
        if not isinstance(src, str) or not _is_safe_rel_path(src):
            diagnostics.append(
                _diag("invalid_bootstrap_source", f"CLAW.md.workspace.bootstrapFiles.{bname}", f"Unsafe source {src!r}")
            )
            continue
        workspace_sources.append(src)
        workspace_targets.add(_portable_path_key(bname))
        if bname in ALLOWED_BOOTSTRAP_FILE_NAMES:
            declared_bootstrap_sources[bname] = src

    ws_files = workspace_cfg["files"] if "files" in workspace_cfg else []
    if not isinstance(ws_files, list):
        diagnostics.append(_diag("invalid_workspace_files", "CLAW.md.workspace.files", "workspace.files must be a list"))
        ws_files = []
    managed_dest_keys: set[str] = set()
    for idx, fentry in enumerate(ws_files):
        if not isinstance(fentry, dict) or set(fentry.keys()) - {"source", "path"}:
            diagnostics.append(
                _diag("invalid_workspace_file_entry", f"CLAW.md.workspace.files[{idx}]", "Must be a {source, path} map")
            )
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
        else:
            dest_key = _portable_path_key(dst)
            if _conflicts_with_template_path({_portable_path_key("BOOTSTRAP.md")}, dest_key):
                diagnostics.append(
                    _diag(
                        "invalid_workspace_dest",
                        f"CLAW.md.workspace.files[{idx}].path",
                        "BOOTSTRAP.md uses the seed-once lifecycle and cannot be a managed workspace.files destination.",
                    )
                )
            elif _conflicts_with_template_path(workspace_targets, dest_key):
                diagnostics.append(
                    _diag(
                        "duplicate_workspace_dest",
                        f"CLAW.md.workspace.files[{idx}].path",
                        f"Workspace destination {dst!r} collides with an existing destination.",
                    )
                )
            workspace_targets.add(dest_key)
            managed_dest_keys.add(dest_key)
        if src.lower() == "package.json":
            diagnostics.append(
                _diag("project_invalid", f"CLAW.md.workspace.files[{idx}].source", "Cannot map package.json")
            )
        workspace_sources.append(src)

    if body_str and (
        "SOUL.md" in bootstrap_files
        or _conflicts_with_template_path(workspace_targets, _portable_path_key("SOUL.md"))
    ):
        diagnostics.append(
            _diag(
                "template_body_soul_conflict",
                "CLAW.md",
                "CLAW.md cannot contain both markdown body text and an explicit SOUL.md workspace declaration.",
            )
        )

    packages_cfg = manifest["packages"] if "packages" in manifest else []
    if not isinstance(packages_cfg, list):
        diagnostics.append(_diag("invalid_packages", "CLAW.md.packages", "packages must be a list"))
    else:
        seen_pkg_keys: set[str] = set()
        for idx, pentry in enumerate(packages_cfg):
            ppath = f"CLAW.md.packages[{idx}]"
            if not isinstance(pentry, dict) or set(pentry.keys()) - ALLOWED_PACKAGE_ENTRY_KEYS:
                diagnostics.append(
                    _diag("invalid_package_entry", ppath, "Each package dependency must map only {kind, source, ref, version}")
                )
                continue
            pkind = pentry.get("kind")
            psource = pentry.get("source")
            pref = pentry.get("ref")
            pver = pentry.get("version")
            if pkind not in ("skill", "plugin") or psource != "clawhub":
                diagnostics.append(_diag("invalid_package_entry", ppath, "Package must use kind skill|plugin and source clawhub"))
            if not isinstance(pref, str) or not PACKAGE_NAME_RE.match(pref):
                diagnostics.append(_diag("invalid_package_ref", f"{ppath}.ref", f"Invalid ClawHub package ref: {pref!r}"))
            if not isinstance(pver, str) or not SEMVER_RE.match(pver):
                diagnostics.append(_diag("invalid_package_version", f"{ppath}.version", f"Version must be exact SemVer: {pver!r}"))
            if isinstance(pkind, str) and isinstance(psource, str) and isinstance(pref, str):
                pkey = f"{pkind}:{psource}:{pref.lower()}"
                if pkey in seen_pkg_keys:
                    diagnostics.append(_diag("duplicate_package_ref", ppath, f"Duplicate package dependency: {pref!r}"))
                seen_pkg_keys.add(pkey)

    identity_cfg = agent_cfg.get("identity") if isinstance(agent_cfg, dict) else None
    if isinstance(identity_cfg, dict):
        avatar_ref = identity_cfg.get("avatar")
        if isinstance(avatar_ref, str) and avatar_ref and not avatar_ref.startswith("data:image/"):
            if _portable_path_key(avatar_ref) not in managed_dest_keys:
                diagnostics.append(
                    _diag(
                        "unmanaged_avatar_path",
                        "CLAW.md.agent.identity.avatar",
                        f"Workspace-relative avatar {avatar_ref!r} must match a workspace.files destination.",
                    )
                )

    # Validate & bound-read declared workspace sources into the single inventory (1 MiB / file, 4 MiB aggregate)
    validated_bootstrap_sources: dict[str, str] = {}
    workspace_byte_total = 0
    for src in workspace_sources:
        if src in inventory_bytes:
            workspace_byte_total += len(inventory_bytes[src])
            continue
        s_bytes, s_err, s_msg = _read_bounded_regular_file(
            root, src, MAX_MANAGED_FILE_BYTES, reject_hardlinks=True
        )
        if s_bytes is None:
            rejected_paths.add(src)
            code_map = {
                "missing": "missing_workspace_source",
                "file_too_large": "managed_file_too_large",
                "symlink_forbidden": "symlink_forbidden",
                "hardlink_forbidden": "hardlink_forbidden",
                "source_escapes_package": "source_escapes_package",
            }
            diagnostics.append(_diag(code_map.get(s_err or "", "invalid_workspace_source"), src, s_msg or f"Invalid {src}"))
            continue
        inventory_bytes[src] = s_bytes
        workspace_byte_total += len(s_bytes)

    if workspace_byte_total > MAX_MANAGED_WORKSPACE_BYTES:
        diagnostics.append(
            _diag(
                "workspace_sources_too_large",
                "CLAW.md.workspace",
                f"Workspace sources ({workspace_byte_total} bytes) exceed OpenClaw {MAX_MANAGED_WORKSPACE_BYTES} byte (4 MiB) aggregate limit.",
            )
        )

    for bname, bsrc in declared_bootstrap_sources.items():
        if bsrc in inventory_bytes:
            validated_bootstrap_sources[bname] = bsrc

    # mcpServers schema, version pinning, HTTPS, and env placeholder checks
    mcp_servers = manifest["mcpServers"] if "mcpServers" in manifest else {}
    if not isinstance(mcp_servers, dict):
        diagnostics.append(_diag("invalid_mcp_servers", "CLAW.md.mcpServers", "mcpServers must be a mapping"))
        mcp_servers = {}
    for srv_name, srv_cfg in mcp_servers.items():
        spath = f"CLAW.md.mcpServers.{srv_name}"
        if not isinstance(srv_name, str) or not AGENT_ID_RE.match(srv_name):
            diagnostics.append(_diag("invalid_mcp_server_name", spath, f"Invalid MCP server name: {srv_name!r}"))
        if not isinstance(srv_cfg, dict):
            diagnostics.append(_diag("invalid_mcp_server", spath, "MCP server declaration must be a mapping"))
            continue
        if isinstance(srv_cfg.get("headers"), dict):
            for hdr_k, hdr_v in srv_cfg["headers"].items():
                if hdr_k.lower() in ("authorization", "x-api-key", "api-key") and (
                    not isinstance(hdr_v, str) or "${" not in hdr_v
                ):
                    diagnostics.append(
                        _diag(
                            "mcp_header_must_use_placeholder",
                            f"{spath}.headers.{hdr_k}",
                            f"MCP auth header {hdr_k} must reference an unresolved '${{ENV_VAR}}' placeholder.",
                        )
                    )
        has_cmd = "command" in srv_cfg
        has_url = "url" in srv_cfg
        if has_cmd == has_url:
            diagnostics.append(
                _diag("invalid_mcp_server", spath, "MCP server must declare either 'command' (stdio) or 'url' (remote)")
            )
        elif has_cmd:
            extra_k = sorted(set(srv_cfg.keys()) - ALLOWED_STDIO_MCP_KEYS)
            for uk in extra_k:
                diagnostics.append(_diag("unknown_mcp_field", f"{spath}.{uk}", f"Unsupported stdio MCP field {uk!r}"))
            cmd_val = srv_cfg.get("command")
            if not isinstance(cmd_val, str) or not cmd_val.strip() or cmd_val != cmd_val.strip():
                diagnostics.append(_diag("invalid_mcp_command", f"{spath}.command", "MCP command must be a trimmed string"))
            if "transport" in srv_cfg and srv_cfg.get("transport") != "stdio":
                diagnostics.append(_diag("invalid_mcp_transport", f"{spath}.transport", "Stdio MCP transport must be 'stdio'"))
            args_val = srv_cfg.get("args", [])
            if not isinstance(args_val, list) or any(not isinstance(a, str) or not a.strip() or a != a.strip() for a in args_val):
                diagnostics.append(_diag("invalid_mcp_args", f"{spath}.args", "MCP args must be a list of trimmed non-empty strings"))
            elif isinstance(cmd_val, str) and not _is_pinned_package_manager_mcp(cmd_val, args_val):
                diagnostics.append(
                    _diag(
                        "unpinned_mcp_package",
                        f"{spath}.args",
                        "Package-manager MCP commands (npx/pnpm/yarn/bunx/uvx/pipx) must pin an exact immutable SemVer.",
                    )
                )
            if "env" in srv_cfg:
                env_map = srv_cfg.get("env")
                if not isinstance(env_map, dict):
                    diagnostics.append(_diag("invalid_mcp_env", f"{spath}.env", "MCP env must be a mapping"))
                else:
                    for env_k, env_v in env_map.items():
                        if not isinstance(env_k, str) or not PORTABLE_ENV_KEY_RE.match(env_k):
                            diagnostics.append(_diag("invalid_mcp_env_key", f"{spath}.env.{env_k}", f"Invalid env key {env_k!r}"))
                        elif env_k.upper() in DANGEROUS_HOST_ENV_KEYS:
                            diagnostics.append(
                                _diag("dangerous_mcp_env_key", f"{spath}.env.{env_k}", f"Blocked host env key {env_k!r}")
                            )
                        if not isinstance(env_v, str) or not ENV_PLACEHOLDER_RE.match(env_v):
                            diagnostics.append(
                                _diag(
                                    "mcp_env_must_be_placeholder",
                                    f"{spath}.env.{env_k}",
                                    f"MCP env value for {env_k} must be an unresolved '${{ENV_VAR}}' reference, never a literal value.",
                                )
                            )
        else:
            extra_k = sorted(set(srv_cfg.keys()) - ALLOWED_REMOTE_MCP_KEYS)
            for uk in extra_k:
                diagnostics.append(_diag("unknown_mcp_field", f"{spath}.{uk}", f"Unsupported remote MCP field {uk!r}"))
            if srv_cfg.get("transport") not in ("sse", "streamable-http"):
                diagnostics.append(
                    _diag("invalid_mcp_transport", f"{spath}.transport", "Remote MCP transport must be 'sse' or 'streamable-http'")
                )
            if "auth" in srv_cfg and srv_cfg.get("auth") != "oauth":
                diagnostics.append(_diag("invalid_mcp_auth", f"{spath}.auth", "Remote MCP auth if set must be 'oauth'"))
            url_val = srv_cfg.get("url")
            if not isinstance(url_val, str) or not url_val.strip() or url_val != url_val.strip():
                diagnostics.append(_diag("invalid_mcp_url", f"{spath}.url", "Remote MCP url must be a trimmed URL string"))
            else:
                parsed_u = urlsplit(url_val)
                host = (parsed_u.hostname or "").lower()
                loopback = host in ("localhost", "127.0.0.1", "::1")
                if parsed_u.scheme != "https" and not (parsed_u.scheme == "http" and loopback):
                    diagnostics.append(
                        _diag(
                            "insecure_mcp_url",
                            f"{spath}.url",
                            "Remote MCP URLs must use HTTPS, except HTTP on an exact loopback host.",
                        )
                    )
                if parsed_u.username or parsed_u.password or parsed_u.fragment:
                    diagnostics.append(
                        _diag(
                            "invalid_mcp_url",
                            f"{spath}.url",
                            "Remote MCP URLs must not contain user credentials or '#' fragments.",
                        )
                    )

    # cronJobs schema, schedule range/timezone & quiet/honesty check
    cron_jobs = manifest["cronJobs"] if "cronJobs" in manifest else []
    if not isinstance(cron_jobs, list):
        diagnostics.append(_diag("invalid_cron_jobs", "CLAW.md.cronJobs", "cronJobs must be a list"))
        cron_jobs = []
    seen_cron_ids: set[str] = set()
    for idx, job in enumerate(cron_jobs):
        jpath = f"CLAW.md.cronJobs[{idx}]"
        if not isinstance(job, dict):
            diagnostics.append(_diag("invalid_cron_job", jpath, "Each cronJob must be a mapping"))
            continue
        for uk in sorted(set(job.keys()) - ALLOWED_CRON_JOB_KEYS):
            diagnostics.append(_diag("unknown_cron_field", f"{jpath}.{uk}", f"Unsupported cronJob field {uk!r}"))
        jid = job.get("id")
        if not isinstance(jid, str) or not AGENT_ID_RE.match(jid):
            diagnostics.append(_diag("invalid_cron_id", f"{jpath}.id", f"Invalid cronJob id: {jid!r}"))
        elif jid in seen_cron_ids:
            diagnostics.append(_diag("duplicate_cron_id", f"{jpath}.id", f"Duplicate cronJob id: {jid!r}"))
        else:
            seen_cron_ids.add(jid)

        session_kind = job.get("session")
        if session_kind not in ("main", "isolated"):
            diagnostics.append(
                _diag(
                    "invalid_cron_session",
                    f"{jpath}.session",
                    f"cronJob session must be 'main' or 'isolated', got {session_kind!r}",
                )
            )

        sched = job.get("schedule")
        if not isinstance(sched, dict) or set(sched.keys()) - {"cron", "timezone"}:
            diagnostics.append(
                _diag("invalid_cron_schedule", f"{jpath}.schedule", "schedule must be a mapping of {cron, timezone}")
            )
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
            elif not is_valid_iana_timezone(tz):
                diagnostics.append(
                    _diag("invalid_cron_timezone", f"{jpath}.schedule.timezone", f"Invalid IANA timezone: {tz!r}")
                )
        msg = job.get("message")
        if not isinstance(msg, str) or not msg.strip():
            diagnostics.append(_diag("missing_cron_message", f"{jpath}.message", "cronJob message must be non-empty"))
        else:
            if msg != msg.strip():
                diagnostics.append(
                    _diag(
                        "invalid_cron_message_whitespace",
                        f"{jpath}.message",
                        "cronJob message must not have leading or trailing whitespace (use '|-' or '>-' for multiline YAML scalars).",
                    )
                )
            if strict_trust:
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
        if "delivery" in job:
            valid_delivery = isinstance(delivery, dict) and (
                (delivery.get("mode") == "none" and set(delivery.keys()) == {"mode"})
                or (
                    delivery.get("mode") == "announce"
                    and delivery.get("channel") == "last"
                    and set(delivery.keys()) == {"mode", "channel"}
                )
            )
            if not valid_delivery:
                diagnostics.append(
                    _diag(
                        "invalid_cron_delivery",
                        f"{jpath}.delivery",
                        'Delivery must be { mode: "none" } or { mode: "announce", channel: "last" }.',
                    )
                )

    # 3. profiles/openclaw.yml, LICENSE, and BOOTSTRAP.md checks (all into the single bounded inventory)
    has_profile = False
    prof_entry = root / "profiles" / "openclaw.yml"
    if _has_symlink_component(root, "profiles/openclaw.yml"):
        rejected_paths.add("profiles/openclaw.yml")
        diagnostics.append(
            _diag("symlink_forbidden", "profiles/openclaw.yml", "profiles/openclaw.yml must not be or traverse a symlink")
        )
    elif prof_entry.exists():
        prof_bytes, prof_err, prof_msg = _read_bounded_regular_file(
            root, "profiles/openclaw.yml", MAX_PROFILE_BYTES, reject_hardlinks=True
        )
        if prof_bytes is None:
            rejected_paths.add("profiles/openclaw.yml")
            code = "profile_too_large" if prof_err == "file_too_large" else (prof_err or "invalid_profile_yaml")
            diagnostics.append(_diag(code, "profiles/openclaw.yml", prof_msg or "Invalid profiles/openclaw.yml"))
        else:
            has_profile = True
            inventory_bytes["profiles/openclaw.yml"] = prof_bytes
            try:
                prof_txt = prof_bytes.decode("utf-8")
                decoded_utf8_by_rel["profiles/openclaw.yml"] = prof_txt
                prof = parse_simple_yaml(prof_txt)
            except Exception as exc:
                diagnostics.append(_diag("invalid_profile_yaml", "profiles/openclaw.yml", f"YAML parse error: {exc}"))
                prof = {}
            if not isinstance(prof, dict) or type(prof.get("schemaVersion")) is not int or prof.get("schemaVersion") != 1:
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
                    elif any(
                        not isinstance(t, str)
                        or not t.strip()
                        or any(ch in t for ch in "*?[]{}")
                        or t.strip() in ("group:plugins", "bundle-mcp")
                        for t in allow_list
                    ):
                        diagnostics.append(
                            _diag(
                                "wildcard_tool_forbidden",
                                "profiles/openclaw.yml.agent.tools.allow",
                                "Wildcard or unbounded ('*', '?', '[]', '{}', 'group:plugins', 'bundle-mcp') tool grants are forbidden in agent.tools.allow.",
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

    has_license = False
    lic_candidate = root / "LICENSE"
    if lic_candidate.is_symlink() or lic_candidate.exists():
        lic_bytes, lic_err, lic_msg = _read_bounded_regular_file(
            root, "LICENSE", MAX_MANAGED_FILE_BYTES, reject_hardlinks=True
        )
        if lic_bytes is None:
            rejected_paths.add("LICENSE")
            code = "symlink_forbidden" if lic_err == "symlink_forbidden" else "project_license_invalid"
            diagnostics.append(_diag(code, "LICENSE", lic_msg or "Package-root LICENSE must be a safe regular file"))
        else:
            has_license = True
            inventory_bytes["LICENSE"] = lic_bytes

    has_bootstrap_seed = False
    boot_candidate = root / "BOOTSTRAP.md"
    if boot_candidate.is_symlink() or boot_candidate.exists():
        boot_bytes, boot_err, boot_msg = _read_bounded_regular_file(
            root, "BOOTSTRAP.md", MAX_BOOTSTRAP_SEED_BYTES, reject_hardlinks=True
        )
        if boot_bytes is None:
            rejected_paths.add("BOOTSTRAP.md")
            code = "symlink_forbidden" if boot_err == "symlink_forbidden" else ("package_bootstrap_too_large" if boot_err == "file_too_large" else "package_bootstrap_invalid")
            diagnostics.append(_diag(code, "BOOTSTRAP.md", boot_msg or "Package-root BOOTSTRAP.md must be a safe regular file"))
        else:
            try:
                if b"\0" in boot_bytes:
                    raise UnicodeDecodeError("utf-8", boot_bytes, 0, 1, "NUL byte")
                boot_txt = boot_bytes.decode("utf-8")
                if not boot_txt.strip():
                    diagnostics.append(
                        _diag("package_bootstrap_empty", "BOOTSTRAP.md", "Package-root BOOTSTRAP.md must not be empty.")
                    )
                else:
                    has_bootstrap_seed = True
                    inventory_bytes["BOOTSTRAP.md"] = boot_bytes
                    decoded_utf8_by_rel["BOOTSTRAP.md"] = boot_txt
            except UnicodeDecodeError:
                diagnostics.append(
                    _diag("package_bootstrap_invalid", "BOOTSTRAP.md", "Package-root BOOTSTRAP.md must be valid UTF-8.")
                )

    # 4. OpenClaw validateTemplateProject zero-exclusion check (project.ts L378-439)
    selected_paths: list[str] = ["package.json", "CLAW.md"]
    if has_license:
        selected_paths.append("LICENSE")
    if has_bootstrap_seed:
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

    case_insensitive = _is_case_insensitive_fs(root)
    selected_project_keys = {_project_path_key(sp, case_insensitive) for sp in set(selected_paths)}

    excluded_paths: list[str] = []
    walked_files: list[str] = []
    reported_symlinks: set[str] = {
        d["path"] for d in diagnostics if d["code"] == "symlink_forbidden"
    }
    entry_count = 0
    total_inventory_bytes = sum(len(b) for b in inventory_bytes.values())

    def walk_dir(rel_dir: str) -> None:
        nonlocal entry_count, total_inventory_bytes
        abs_dir = root / rel_dir if rel_dir else root
        for entry in sorted(abs_dir.iterdir(), key=lambda p: p.name):
            entry_count += 1
            if entry_count > MAX_PROJECT_ENTRIES:
                diagnostics.append(
                    _diag("project_too_many_entries", "$", f"Template exceeds {MAX_PROJECT_ENTRIES} entries")
                )
                return
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if entry.is_symlink():
                walked_files.append(rel)
                if rel not in reported_symlinks:
                    diagnostics.append(
                        _diag("symlink_forbidden", rel, f"Template entry {rel} must not be a symlink")
                    )
                    reported_symlinks.add(rel)
                if _project_path_key(rel, case_insensitive) not in selected_project_keys:
                    excluded_paths.append(rel)
            elif entry.is_dir():
                if entry.name in (".git", "node_modules"):
                    excluded_paths.append(f"{rel}/")
                else:
                    walk_dir(rel)
            else:
                walked_files.append(rel)
                if _project_path_key(rel, case_insensitive) not in selected_project_keys:
                    excluded_paths.append(rel)
                if rel not in inventory_bytes and rel not in rejected_paths:
                    if total_inventory_bytes >= MAX_TOTAL_INVENTORY_BYTES:
                        rejected_paths.add(rel)
                        diagnostics.append(
                            _diag("inventory_budget_exceeded", rel, f"Total scanned inventory exceeds {MAX_TOTAL_INVENTORY_BYTES} bytes")
                        )
                        continue
                    w_bytes, w_err, w_msg = _read_bounded_regular_file(
                        root, rel, MAX_MANAGED_FILE_BYTES, reject_hardlinks=True
                    )
                    if w_bytes is not None:
                        inventory_bytes[rel] = w_bytes
                        total_inventory_bytes += len(w_bytes)
                    else:
                        rejected_paths.add(rel)
                        if w_err == "file_too_large":
                            diagnostics.append(_diag("managed_file_too_large", rel, w_msg or f"{rel} exceeds 1 MiB"))
                        elif w_err == "hardlink_forbidden":
                            diagnostics.append(_diag("hardlink_forbidden", rel, w_msg or f"{rel} must not be a hardlink"))

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

    # 5. Scan credential filenames & bounded file inventory (zero disk rereads) for secrets/private paths
    for sp in dict.fromkeys([*selected_paths, *walked_files]):
        if _is_forbidden_credential_file(sp):
            diagnostics.append(
                _diag(
                    "forbidden_credential_file",
                    sp,
                    f"{sp} is a credential or private-key file and must not be included in an OpenClaw template.",
                )
            )
        raw = inventory_bytes.get(sp)
        if raw is None:
            continue
        p_obj = Path(sp)
        must_be_utf8 = (p_obj.suffix.lower() in TEXT_SUFFIXES) or (
            p_obj.name in ("LICENSE", "BOOTSTRAP.md", "CLAW.md")
        )
        if must_be_utf8:
            if b"\0" in raw:
                diagnostics.append(_diag("invalid_utf8", sp, f"{sp} contains NUL bytes and is not valid UTF-8 text"))
                continue
            txt = decoded_utf8_by_rel.get(sp)
            if txt is None:
                try:
                    txt = raw.decode("utf-8")
                    decoded_utf8_by_rel[sp] = txt
                except UnicodeDecodeError:
                    diagnostics.append(_diag("invalid_utf8", sp, f"{sp} is not valid UTF-8"))
                    continue
            diagnostics.extend(_scan_text_for_secrets_and_paths(sp, txt))
        elif b"\0" not in raw:
            try:
                txt = raw.decode("utf-8")
            except UnicodeDecodeError:
                txt = raw.decode("latin-1")
            diagnostics.extend(_scan_text_for_secrets_and_paths(sp, txt))

    # 6. Factory house-rule policy heuristics on cached UTF-8 inventory only (zero disk rereads)
    if strict_trust:
        agents_src = validated_bootstrap_sources.get("AGENTS.md")
        policy_label = agents_src or "CLAW.md"
        if agents_src is not None and agents_src not in decoded_utf8_by_rel:
            # `invalid_utf8` was already emitted in Stage 5 for this validated file; skip secondary phrase noise.
            policy_text: str | None = None
        else:
            agents_txt = decoded_utf8_by_rel.get(agents_src, "") if agents_src else ""
            policy_text = f"{agents_txt}\n{body_str}".strip()

        if policy_text is not None:
            if _has_negated_trust_sentence(policy_text):
                diagnostics.append(
                    _diag(
                        "negated_trust_boundary",
                        policy_label,
                        f"{policy_label} contains language that bypasses human approval or trusts untrusted input.",
                    )
                )
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

        hb_src = validated_bootstrap_sources.get("HEARTBEAT.md")
        if hb_src is not None and hb_src in decoded_utf8_by_rel:
            hb_text = decoded_utf8_by_rel[hb_src]
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

    factory_policy_ok = len(diagnostics) == 0

    # 7. Authoritative OpenClaw CLI compatibility check (when installed on PATH)
    if openclaw_mode == "skip":
        openclaw_compat = "unverified"
    else:
        openclaw_compat, native_diags = _run_native_openclaw_validate(root)
        diagnostics.extend(native_diags)
        if openclaw_mode == "require" and openclaw_compat == "unverified":
            diagnostics.append(
                _diag(
                    "openclaw_cli_unavailable",
                    "$",
                    "Authoritative 'openclaw' CLI was not found on PATH (--require-openclaw).",
                )
            )

    return {
        "template": tdir.name,
        "root": str(root),
        "ok": len(diagnostics) == 0,
        "factoryPolicyOk": factory_policy_ok,
        "openclawCompatibility": openclaw_compat,
        "selectedFileCount": len(set(selected_paths)),
        "excludedPaths": excluded_paths,
        "diagnostics": diagnostics,
    }


def _discover_default_templates_root() -> Path:
    cwd_templates = Path.cwd() / "templates"
    if cwd_templates.is_dir():
        return cwd_templates
    for anchor in (Path(sys.argv[0]).resolve(), Path(__file__).resolve()):
        for parent in anchor.parents:
            if (parent / "templates").is_dir() and (parent / "scripts" / "verify_blobster_factory.py").is_file():
                return parent / "templates"
    return cwd_templates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Factory house-rule policy/secret heuristics and native OpenClaw CLI validation (when installed) on Agent Templates."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Template project directories to lint (default: all templates/*/ in workspace/repo).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report to stdout.")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit 0 when default templates/ directory is absent or empty (for standalone workspace maintenance).",
    )
    parser.add_argument(
        "--no-strict-trust",
        action="store_true",
        help="Check manifest/inventory/secret rules only (skip AGENTS.md/cron policy-phrase heuristics).",
    )
    oc_group = parser.add_mutually_exclusive_group()
    oc_group.add_argument(
        "--require-openclaw",
        action="store_true",
        help="Fail closed when the authoritative 'openclaw' CLI is not installed on PATH.",
    )
    oc_group.add_argument(
        "--skip-openclaw",
        action="store_true",
        help="Skip invoking 'openclaw templates validate' even if 'openclaw' is on PATH.",
    )
    args = parser.parse_args(argv)
    openclaw_mode = "require" if args.require_openclaw else ("skip" if args.skip_openclaw else "auto")

    if args.paths:
        targets = args.paths
    else:
        templates_root = _discover_default_templates_root()
        if not templates_root.is_dir():
            if args.allow_empty:
                if args.json:
                    print(
                        json.dumps(
                            {
                                "ok": True,
                                "factoryPolicyOk": True,
                                "openclawCompatibility": "unverified",
                                "templatesChecked": [],
                                "results": [],
                            },
                            indent=2,
                        )
                    )
                return 0
            print(f"error: default templates directory not found: {templates_root}", file=sys.stderr)
            return 2
        targets = sorted(p for p in templates_root.iterdir() if p.is_dir())

    if not targets:
        if args.allow_empty and not args.paths:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "factoryPolicyOk": True,
                            "openclawCompatibility": "unverified",
                            "templatesChecked": [],
                            "results": [],
                        },
                        indent=2,
                    )
                )
            return 0
        print("error: no template directories found to lint", file=sys.stderr)
        return 2

    for t in targets:
        if not t.exists() and not t.is_symlink():
            print(f"error: template directory does not exist: {t}", file=sys.stderr)
            return 2
        if not t.is_dir() and not t.is_symlink():
            print(f"error: template path is not a directory: {t}", file=sys.stderr)
            return 2

    results = [
        lint_template_dir(t, strict_trust=not args.no_strict_trust, openclaw_mode=openclaw_mode)
        for t in targets
    ]
    overall_ok = all(r["ok"] for r in results)
    overall_factory_ok = all(r["factoryPolicyOk"] for r in results)
    if any(r["openclawCompatibility"] == "failed" for r in results):
        overall_compat = "failed"
    elif results and all(r["openclawCompatibility"] == "verified" for r in results):
        overall_compat = "verified"
    else:
        overall_compat = "unverified"

    if args.json:
        print(
            json.dumps(
                {
                    "ok": overall_ok,
                    "factoryPolicyOk": overall_factory_ok,
                    "openclawCompatibility": overall_compat,
                    "templatesChecked": [r["template"] for r in results],
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        for r in results:
            status = "PASS" if r["factoryPolicyOk"] else "FAIL"
            print(
                f"[{status}] {r['template']} · Factory house rules "
                f"({r.get('selectedFileCount', 0)} selected files; secret-pattern & policy heuristics)"
            )
            compat = r["openclawCompatibility"]
            if compat == "verified":
                print("  [VERIFIED] Authoritative OpenClaw CLI ('openclaw templates validate --json') passed")
            elif compat == "failed":
                print("  [FAILED] Authoritative OpenClaw CLI ('openclaw templates validate --json') rejected template")
            else:
                print(
                    f"  [UNVERIFIED] Native OpenClaw CLI not found — run 'openclaw templates validate {r['template']}' to confirm"
                )
            for d in r["diagnostics"]:
                print(f"  - [{d['code']}] {d['path']}: {d['message']}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
