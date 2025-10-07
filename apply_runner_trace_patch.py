# apply_runner_trace_patch.py
import re, shutil
from pathlib import Path

OK = "\u2705"; WARN = "\u26A0\uFE0F"
BASE = Path(__file__).resolve().parent

def backup(p: Path, suf=".bak_trace"):
    if p.exists(): shutil.copy2(p, p.with_suffix(p.suffix + suf))

def patch_file(p: Path):
    if not p.exists():
        print(f"{WARN} {p} not found, skip"); return
    txt = p.read_text(encoding="utf-8", errors="ignore")
    changed=False
    # типовая замена только в блоках 'except Exception as e: logger.error(...'
    new = re.sub(r"(\.logger)\.error\(([^)]+)\)", r"\1.exception(\2)", txt)
    if new != txt:
        backup(p); p.write_text(new, encoding="utf-8"); changed=True
        print(f"{OK} Patched {p.relative_to(BASE)} (exception trace enabled)")
    else:
        print(f"{OK} {p.relative_to(BASE)} already has exception tracing")

def main():
    for rel in ("runner/paper.py", "runner/live.py"):
        patch_file(BASE / rel)
    print("\\nDone.")

if __name__ == "__main__":
    main()
