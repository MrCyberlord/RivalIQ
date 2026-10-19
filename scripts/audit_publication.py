"""Read-only publication audit. Prints locations/types, never matched values."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VENDOR = {"node_modules", ".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache", "dist", ".mypy_cache", ".ruff_cache", ".publication-tools"}
PATTERNS = {
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential_uri": re.compile(r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql)://[^\s:/]+:[^\s@]+@", re.I),
    "aws_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}


def candidates():
    import os
    for base, directories, files in os.walk(ROOT):
        directories[:] = [d for d in directories if d not in VENDOR]
        for name in files:
            yield Path(base) / name


def audit():
    files = list(candidates())
    secrets = set()
    local_env = []
    for path in files:
        if path.name.startswith(".env") and path.name != ".env.example":
            local_env.append(str(path.relative_to(ROOT)))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                key, sep, value = line.partition("=")
                if sep and re.search(r"KEY|TOKEN|PASSWORD|SECRET|DSN|URI", key, re.I):
                    value = value.strip().strip('\"\'')
                    if len(value) >= 12:
                        secrets.add(value)
    findings = []
    checked = 0
    for path in files:
        if str(path.relative_to(ROOT)) in local_env:
            continue
        data = path.read_bytes()
        checked += 1
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            kinds = [kind for kind, pattern in PATTERNS.items() if pattern.search(line)]
            if any(secret in line for secret in secrets):
                kinds.append("matches_local_secret")
            # Test fixtures and sanitizer regexes can contain intentionally fake URIs.
            if kinds:
                findings.append({"file": str(path.relative_to(ROOT)), "line": number, "types": kinds})
    print(json.dumps({"project_files_checked": checked, "local_env_files_to_exclude": local_env,
                      "vendor_generated_directories_excluded_from_publication": sorted(VENDOR),
                      "findings_requiring_review": findings}, indent=2))
    if (ROOT / ".git").exists():
        tracked = subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files"], cwd=ROOT, text=True).splitlines()
        unwanted = [p for p in tracked if any(part in VENDOR - {".git"} for part in Path(p).parts)
                    or (Path(p).name.startswith(".env") and Path(p).name != ".env.example") or p.endswith(".log")]
        print(json.dumps({"unsafe_tracked_paths": unwanted}))


if __name__ == "__main__":
    audit()
