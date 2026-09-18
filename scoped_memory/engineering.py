from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


EIR_VERSION = "eir/1"
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".scoped-memory", ".tox", ".venv", "venv", "node_modules",
    "dist", "build", "coverage", "__pycache__", ".mypy_cache", ".pytest_cache",
}
SECRET_NAME = re.compile(
    r"(^|[._-])(\.env|secret|secrets|credential|credentials|token|id_rsa|id_ed25519)([._-]|$)",
    re.IGNORECASE,
)
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java",
    ".js", ".jsx", ".json", ".kt", ".kts", ".md", ".mjs", ".php", ".ps1",
    ".py", ".rb", ".rs", ".scss", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".vue", ".xml", ".yaml", ".yml",
}
LANGUAGE = {
    ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".cs": "csharp", ".go": "go",
    ".h": "c", ".hpp": "cpp", ".java": "java", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".kt": "kotlin", ".kts": "kotlin", ".php": "php",
    ".ps1": "powershell", ".py": "python", ".rb": "ruby", ".rs": "rust", ".sh": "shell",
    ".sql": "sql", ".ts": "typescript", ".tsx": "typescript", ".vue": "vue",
}
JS_IMPORT = re.compile(
    r"(?:import\s+(?:[^'\"]+?\s+from\s+)?|require\s*\()\s*['\"]([^'\"]+)['\"]"
)
JS_SYMBOL = re.compile(
    r"(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|"
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="
)
GENERIC_SYMBOL = re.compile(
    r"^\s*(?:pub\s+|export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+)*"
    r"(?:class|interface|struct|enum|trait|fn|func|function|def)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def _run(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            list(args), cwd=root, check=True, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _candidate_files(root: Path) -> list[Path]:
    raw = _run(root, "git", "ls-files", "-co", "--exclude-standard", "-z")
    if raw:
        paths = [root / value for value in raw.split("\0") if value]
    else:
        paths = []
        for current, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            paths.extend(Path(current) / name for name in sorted(names))
    return sorted({path.resolve() for path in paths if path.is_file()}, key=lambda p: p.as_posix())


def _safe_file(root: Path, path: Path, max_file_bytes: int) -> bool:
    try:
        rel = path.relative_to(root)
        stat = path.stat()
    except (OSError, ValueError):
        return False
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if SECRET_NAME.search(path.name) or stat.st_size > max_file_bytes:
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in {
        "Dockerfile", "Makefile", "Procfile", "requirements.txt",
    }


def _roles(path: str) -> list[str]:
    lowered = path.casefold()
    roles = []
    if re.search(r"(^|/)(tests?|specs?)(/|$)|(^|/)(test|spec)[_.-]", lowered):
        roles.append("test")
    if path in {"package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"}:
        roles.append("manifest")
    if path.endswith(("README.md", "README.en.md", "README.pt-BR.md")):
        roles.append("doc")
    if path.endswith(("Dockerfile", ".yml", ".yaml", ".toml")) or "/.github/" in f"/{path}":
        roles.append("config")
    return roles


def _python_facts(text: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    symbols, imports = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            imports.append(prefix + (node.module or ""))
    return sorted(set(symbols))[:64], sorted(set(imports))[:64]


def _text_facts(path: Path, text: str) -> tuple[list[str], list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _python_facts(text)
    if suffix in {".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue"}:
        symbols = [a or b for a, b in JS_SYMBOL.findall(text)]
        return sorted(set(symbols))[:64], sorted(set(JS_IMPORT.findall(text)))[:64]
    return sorted(set(GENERIC_SYMBOL.findall(text)))[:64], []


def _manifest_facts(relative: str, text: str) -> dict[str, Any] | None:
    if relative == "package.json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return {
            "p": relative,
            "scripts": sorted((value.get("scripts") or {}).keys()),
            "deps": sorted({*(value.get("dependencies") or {}), *(value.get("devDependencies") or {})}),
        }
    if relative == "requirements.txt":
        deps = []
        for line in text.splitlines():
            value = line.strip()
            if value and not value.startswith(("#", "-")):
                deps.append(re.split(r"[<=>!~\[]", value, 1)[0].strip())
        return {"p": relative, "deps": sorted(set(deps))}
    return None


def _local_edges(files: list[dict[str, Any]]) -> list[list[str]]:
    paths = {item["p"] for item in files}
    python_modules = {
        path.removesuffix("/__init__.py").removesuffix(".py").replace("/", "."): path
        for path in paths if path.endswith(".py")
    }
    edges: set[tuple[str, str, str]] = set()
    for item in files:
        source = item["p"]
        for target in item.get("imp", []):
            resolved = None
            if source.endswith(".py"):
                name = target.lstrip(".")
                resolved = python_modules.get(name)
                if resolved is None:
                    resolved = next((path for module, path in python_modules.items() if module.endswith(f".{name}")), None)
            elif target.startswith("."):
                base = (Path(source).parent / target).as_posix()
                variants = [base, *(base + ext for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs")),
                            *(f"{base}/index{ext}" for ext in (".ts", ".tsx", ".js", ".jsx"))]
                resolved = next((value for value in variants if value in paths), None)
            if resolved:
                edges.add((source, "imp", resolved))
    return [list(edge) for edge in sorted(edges)]


def build_engineering_index(
    root: Path,
    *,
    max_files: int = 2000,
    max_file_bytes: int = 256_000,
) -> dict[str, Any]:
    root = root.resolve()
    files, manifests, skipped = [], [], {"secret": 0, "binary_or_large": 0, "limit": 0}
    for path in _candidate_files(root):
        if len(files) >= max_files:
            skipped["limit"] += 1
            continue
        if SECRET_NAME.search(path.name):
            skipped["secret"] += 1
            continue
        if not _safe_file(root, path, max_file_bytes):
            skipped["binary_or_large"] += 1
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            skipped["binary_or_large"] += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        relative = path.relative_to(root).as_posix()
        symbols, imports = _text_facts(path, text)
        node: dict[str, Any] = {
            "p": relative,
            "k": LANGUAGE.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "text"),
            "b": len(raw),
            "h": hashlib.sha256(raw).hexdigest()[:16],
        }
        if symbols:
            node["sym"] = symbols
        if imports:
            node["imp"] = imports
        if roles := _roles(relative):
            node["role"] = roles
        files.append(node)
        if manifest := _manifest_facts(relative, text):
            manifests.append(manifest)

    revision = _run(root, "git", "rev-parse", "HEAD") or None
    dirty_lines = _run(root, "git", "status", "--porcelain=v1").splitlines()
    payload: dict[str, Any] = {
        "v": EIR_VERSION,
        "rev": revision,
        "dirty": len(dirty_lines),
        "files": files,
        "edges": _local_edges(files),
        "manifests": manifests,
        "stats": {
            "files": len(files),
            "symbols": sum(len(item.get("sym", [])) for item in files),
            "edges": 0,
            "bytes": sum(item["b"] for item in files),
            "skipped": skipped,
        },
    }
    payload["stats"]["edges"] = len(payload["edges"])
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def estimate_tokens(value: str) -> int:
    ascii_count = sum(ord(char) < 128 for char in value)
    return (ascii_count + 3) // 4 + len(value) - ascii_count


def bounded_engineering_context(index: dict[str, Any], query: str, token_budget: int) -> dict[str, Any]:
    terms = [value.casefold() for value in re.split(r"\s+", query) if value]
    ranked = []
    for item in index.get("files", []):
        searchable = " ".join([
            item.get("p", ""), *item.get("sym", []), *item.get("imp", []), *item.get("role", []),
        ]).casefold()
        if terms:
            score = sum(3 if term in item.get("p", "").casefold() else 1 for term in terms if term in searchable)
            if score == 0:
                continue
        else:
            score = 3 * int("manifest" in item.get("role", [])) + 2 * int("test" in item.get("role", []))
        ranked.append((score, item["p"], item))
    ranked.sort(key=lambda value: (-value[0], value[1]))

    packet: dict[str, Any] = {
        "v": EIR_VERSION,
        "digest": index.get("digest"),
        "rev": index.get("rev"),
        "dirty": index.get("dirty", 0),
        "stats": index.get("stats", {}),
        "files": [],
        "edges": [],
        "manifests": index.get("manifests", []),
    }
    selected: set[str] = set()
    for _, _, item in ranked:
        candidate = dict(packet)
        candidate["files"] = [*packet["files"], item]
        rendered = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if estimate_tokens(rendered) > token_budget:
            continue
        packet["files"].append(item)
        selected.add(item["p"])
    packet["edges"] = [edge for edge in index.get("edges", []) if edge[0] in selected and edge[2] in selected]
    rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if estimate_tokens(rendered) > token_budget:
        packet["edges"] = []
        packet["manifests"] = []
        rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "format": EIR_VERSION,
        "context": rendered,
        "estimated_tokens": estimate_tokens(rendered),
        "selected_files": len(packet["files"]),
        "available_files": len(index.get("files", [])),
        "truncated": len(packet["files"]) < len(ranked),
    }
