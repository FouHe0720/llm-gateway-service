"""Review aid for the Git index. Not a substitute for reviewing staged files."""

import re
import subprocess
from pathlib import Path

PATTERNS = {
    "credential": re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"),
    "AWS credential": re.compile(r"AKIA[A-Z0-9]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "machine path": re.compile(r"/(?:home|Users)/[A-Za-z0-9_]|/mnt/[c-z]/Users/"),
}


def main() -> None:
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    if Path.cwd().resolve() != Path(root).resolve() or Path(root).name != "llm-gateway-service":
        raise SystemExit("Run from the llm-gateway-service repository root")
    files = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], text=True
    ).splitlines()
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    failures = []
    for name in tracked:
        parts = Path(name).parts
        if any(
            p in {".venv", ".env", "__pycache__", ".pytest_cache", "downloads"} for p in parts
        ):
            failures.append(f"{name}: forbidden tracked path")
        data = subprocess.check_output(["git", "show", f":{name}"]).decode(
            "utf-8", errors="replace"
        )
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append(f"{name}: possible {label}; review required")
    for ignored in [
        ".env",
        ".venv/probe",
        "tmp/probe.log",
        "data/probe.sqlite",
        "downloads/probe",
    ]:
        if subprocess.run(["git", "check-ignore", "-q", ignored]).returncode:
            failures.append(f"Missing ignore rule: {ignored}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"Privacy checks passed for {len(tracked)} indexed files ({len(files)} staged changes)."
    )
    print(
        "Review staged diff and upstream URLs before publishing; heuristic checks have limits."
    )


if __name__ == "__main__":
    main()
