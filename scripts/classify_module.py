#!/usr/bin/env python3
"""
classify_module.py — Classify a module as TRIGGER / CODE / GATEWAY.

Uses heuristic analysis of imports, branching keywords, and file patterns
to determine which node role a module serves.

Usage:
    python3 classify_module.py path/to/file.ts
    python3 classify_module.py --batch src/  (scan all .ts/.tsx files)
"""

import argparse
import re
import sys
from pathlib import Path


# Heuristic weights — the highest-scoring category wins
WEIGHTS = {
    "TRIGGER_SIGNALS": {
        # Page components and entry points
        "patterns": [r"React\.lazy", r"Route\(", r"createBrowserRouter",
                      r"export default function \w+Page", r"createRoot"],
        "weight": 3,
    },
    "GATEWAY_SIGNALS": {
        # Branching and orchestration
        "patterns": [r"if\s*\(.*role", r"switch\s*\(.*role",
                      r"switch\s*\(.*status", r"useState", r"useEffect",
                      r"useQuery", r"useMutation",
                      r"import.*services/", r"from.*\.\.\/hooks",
                      r"Promise\.all\s*\[", r"React\.createContext"],
        "weight": 2,
    },
    "CODE_SIGNALS": {
        # Pure IO and computation
        "patterns": [r"import.*from ['\"]firebase", r"import.*from ['\"]@google-cloud",
                      r"getDoc\s*\(", r"getDocs\s*\(", r"addDoc\s*\(", r"setDoc\s*\(",
                      r"updateDoc\s*\(", r"deleteDoc\s*\(", r"runTransaction",
                      r"collection\s*\(", r"doc\s*\(", r"query\s*\(",
                      r"limit\s*\(", r"orderBy\s*\(", r"where\s*\("],
        "weight": 1,
    },
}

FILE_BY_CONVENTION = {
    # If the path matches, it overrides heuristic classification
    "TRIGGER": [
        r"src/pages/", r"src/App\.tsx$",
        r"src/cloud-functions/", r"src/contexts/",
        r"src/scripts/",
    ],
    "CODE": [
        r"src/lib/dal/", r"src/lib/utils/",
        r"src/lib/auth/pin", r"src/lib/auth/token",
        r"src/lib/auth/userProfile",
        r"src/lib/llm/", r"src/lib/pdf/",
        r"src/lib/report-card/", r"src/lib/migrations/",
        r"src/lib/constants", r"src/lib/formatters",
        r"src/lib/dateUtils", r"src/lib/logger",
        r"src/lib/i18n", r"src/lib/featureFlags",
        r"src/lib/scoreTier", r"src/lib/scheduleUtils",
        r"src/lib/userDisplay", r"src/lib/tutorColors",
        r"packages/",
    ],
    "GATEWAY": [
        r"src/services/", r"src/hooks/",
        r"src/test/", r"src/__tests__/",
    ],
}


def classify_by_convention(file_path: str) -> str | None:
    """Classify by file location (convention over configuration)."""
    for role, patterns in FILE_BY_CONVENTION.items():
        for pat in patterns:
            if re.search(pat, file_path):
                return role
    return None


def classify_by_heuristic(content: str) -> str:
    """Score the file content against role signals."""
    scores = {"TRIGGER": 0, "CODE": 0, "GATEWAY": 0}

    # Count signal patterns
    for role, signals in WEIGHTS.items():
        role_name = role.replace("_SIGNALS", "")
        for pat in signals["patterns"]:
            matches = re.findall(pat, content, re.MULTILINE)
            scores[role_name] += len(matches) * signals["weight"]

    # Anti-patterns: things that disqualify a role
    if re.search(r"if\s*\(.*role|switch\s*\(.*(role|status)", content):
        scores["CODE"] -= 10  # Branching logic disqualifies pure CODE

    if re.search(r"getDoc|getDocs|addDoc|setDoc", content):
        # Has Firestore operations → likely CODE or GATEWAY, not TRIGGER
        scores["TRIGGER"] -= 3

    if re.search(r"React\.lazy|Route|createRoot", content):
        # Page-level → likely TRIGGER
        scores["TRIGGER"] += 5

    # Winner
    return max(scores, key=scores.get)


def classify(file_path: str, content: str | None = None) -> tuple[str, str]:
    """
    Classify a module. Returns (role, method).

    Method is 'convention', 'heuristic', or 'unknown'.
    """
    # Try convention first (most reliable)
    role = classify_by_convention(file_path)
    if role:
        return role, "convention"

    # Fall back to heuristic
    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "UNKNOWN", "error"

    role = classify_by_heuristic(content)
    return role, "heuristic"


def main():
    parser = argparse.ArgumentParser(description="Classify a module as TRIGGER/CODE/GATEWAY")
    parser.add_argument("path", nargs="?", help="File or directory to classify")
    parser.add_argument("--batch", "-b", dest="batch_dir",
                        help="Scan all .ts/.tsx files in a directory")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Only output the role (no explanation)")
    args = parser.parse_args()

    if args.batch_dir:
        # Batch mode: scan directory
        base = Path(args.batch_dir)
        if not base.exists():
            print(f"Directory not found: {base}", file=sys.stderr)
            sys.exit(1)

        files = sorted(base.rglob("*.[jt]s?(x)"))
        for f in files:
            if "node_modules" in str(f) or "__tests__" in str(f):
                continue
            role, method = classify(str(f))
            print(f"{role:8} {method:12} {f}")
        sys.exit(0)

    if not args.path:
        parser.print_help()
        sys.exit(1)

    target = Path(args.path)
    if not target.exists():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(1)

    if target.is_dir():
        # Scan all files in directory
        files = sorted(target.rglob("*.[jt]s?(x)"))
        for f in files:
            if "node_modules" in str(f) or "__tests__" in str(f):
                continue
            role, method = classify(str(f))
            if args.quiet:
                print(role)
            else:
                print(f"{role:8} {method:12} {f}")
        sys.exit(0)

    # Single file
    role, method = classify(str(target))
    if args.quiet:
        print(role)
    else:
        print(f"{role:8} {method:12} {target}")


if __name__ == "__main__":
    main()
