from pathlib import Path
import ast

root = Path(".")
tests = sorted(
    p for p in root.rglob("test*.py")
    if ".venv" not in p.parts
    and "__pycache__" not in p.parts
)

print("=" * 80)
print("HAFNOT AI TRADING AGENT — TEST SUITE AUDIT")
print("=" * 80)
print(f"Test files found: {len(tests)}")
print()

for p in tests:
    text = p.read_text(encoding="utf-8", errors="ignore")

    flags = []

    if "raise SystemExit" in text:
        flags.append("SYSTEMEXIT")
    if "sys.exit(" in text:
        flags.append("SYS.EXIT")
    if "if __name__" in text:
        flags.append("MAIN BLOCK")
    if "asyncio.run(" in text:
        flags.append("ASYNCIO.RUN")
    if "requests." in text or "httpx." in text:
        flags.append("NETWORK")
    if "subprocess" in text:
        flags.append("SUBPROCESS")

    try:
        ast.parse(text)
        syntax = "OK"
    except SyntaxError as e:
        syntax = f"SYNTAX ERROR line {e.lineno}: {e.msg}"

    print(f"{p}")
    print(f"  Syntax : {syntax}")
    print(f"  Flags  : {', '.join(flags) if flags else 'none'}")
    print()

print("=" * 80)
print("DIRECTED PYTEST COLLECTION")
print("=" * 80)

import subprocess

safe_tests = [
    str(p) for p in tests
    if "raise SystemExit" not in p.read_text(encoding="utf-8", errors="ignore")
    and "sys.exit(" not in p.read_text(encoding="utf-8", errors="ignore")
]

print(f"Candidate clean test files: {len(safe_tests)}")
print()

if safe_tests:
    result = subprocess.run(
        ["python", "-m", "pytest", "-q", *safe_tests],
        capture_output=True,
        text=True,
        timeout=300,
    )

    print(result.stdout)

    if result.stderr:
        print("STDERR:")
        print(result.stderr)

    print(f"PYTEST EXIT CODE: {result.returncode}")

print("=" * 80)
