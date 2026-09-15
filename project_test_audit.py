from pathlib import Path
import ast
import subprocess
import sys

root = Path(".").resolve()

tests = sorted(
    p for p in root.rglob("test*.py")
    if ".venv" not in p.parts
    and "__pycache__" not in p.parts
    and p.name not in {"test_audit.py"}
)

print("=" * 80)
print("HAFNOT AI TRADING AGENT — TEST SUITE AUDIT")
print("=" * 80)
print(f"Python executable : {sys.executable}")
print(f"Test files found  : {len(tests)}")
print()

problem_files = []

for p in tests:
    raw = p.read_bytes()

    # Handle UTF-8 BOM safely.
    text = raw.decode("utf-8-sig", errors="ignore")

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
        problem_files.append((p, "SYNTAX"))

    print(str(p.relative_to(root)))
    print(f"  Syntax : {syntax}")
    print(f"  Flags  : {', '.join(flags) if flags else 'none'}")
    print()

print("=" * 80)
print("PYTEST COLLECTION")
print("=" * 80)

result = subprocess.run(
    [sys.executable, "-m", "pytest", "--collect-only", "-q", *map(str, tests)],
    capture_output=True,
    text=True,
    timeout=300,
)

print(result.stdout)

if result.stderr:
    print("STDERR:")
    print(result.stderr)

print(f"PYTEST COLLECTION EXIT CODE: {result.returncode}")

print("=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"Total test files       : {len(tests)}")
print(f"Syntax problems        : {len(problem_files)}")
print(f"Python used by audit   : {sys.executable}")

if problem_files:
    print()
    print("PROBLEM FILES:")
    for p, reason in problem_files:
        print(f"  {p} -> {reason}")

print()
print("IMPORTANT:")
print("- No production files were modified.")
print("- Live trading remains disabled.")
print("- This audit only inspects/collects tests.")
print("=" * 80)
