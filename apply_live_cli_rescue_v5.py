# apply_live_cli_rescue_v5.py
# ASCII-only. Патчит runner/live.py и cli_integrated.py.
import os, re, shutil

BASE = os.path.dirname(__file__)

def patch_live():
    p = os.path.join(BASE, "runner", "live.py")
    if not os.path.exists(p):
        print("SKIP - runner/live.py not found")
        return
    txt = open(p, "r", encoding="utf-8").read()
    orig = txt

    # 1) Нормализуем табы -> пробелы (защита от unexpected indent)
    txt = txt.replace("\t", "    ")

    # 2) Чиним опечатку self.getattr(...) -> getattr(self.config, ...)
    #    Сначала убираем самопальный self.getattr(
    txt = txt.replace("self.getattr(", "getattr(")
    #    Затем убедимся, что первое положение - это self.config
    txt = txt.replace("getattr(config,", "getattr(self.config,")

    # 3) Переписываем _setup_signal_handlers с корректными отступами
    #    Ищем определение функции и заменяем весь её блок
    m = re.search(r"(?m)^(?P<i>[ ]*)def[ ]+_setup_signal_handlers\s*\(.*?\):", txt)
    if m:
        indent = m.group("i")
        body_start = m.end()
        # ищем следующий def/async def на том же уровне отступа
        m2 = re.search(r"(?m)^(%s)(def|async[ ]+def)[ ]+" % indent, txt[body_start:])
        func_end = (body_start + m2.start()) if m2 else len(txt)

        new_block = (
            f"{indent}def _setup_signal_handlers(self) -> None:\n"
            f"{indent}    try:\n"
            f"{indent}        import signal\n"
            f"{indent}        import asyncio\n"
            f"{indent}        loop = asyncio.get_running_loop()\n"
            f"{indent}        for _sig in (signal.SIGINT, signal.SIGTERM):\n"
            f"{indent}            loop.add_signal_handler(\n"
            f"{indent}                _sig,\n"
            f"{indent}                lambda s=_sig: asyncio.create_task(self.signal_handler(s))\n"
            f"{indent}            )\n"
            f"{indent}    except Exception as e:\n"
            f"{indent}        import logging\n"
            f"{indent}        logging.getLogger(__name__).warning(\n"
            f"{indent}            \"Signal handlers not fully installed: %s\", e\n"
            f"{indent}        )\n"
        )
        txt = txt[:m.start()] + new_block + txt[func_end:]
        changed = True
    else:
        changed = False

    if txt != orig:
        bak = p + ".bak_live_fix_v5"
        shutil.copy2(p, bak)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt)
        print("OK  - Patched runner\\live.py (indent + getattr fix). Backup:", os.path.basename(bak))
    else:
        msg = "OK  - runner\\live.py already patched" if changed else "SKIP- runner\\live.py no changes"
        print(msg)

def patch_cli():
    p = os.path.join(BASE, "cli_integrated.py")
    if not os.path.exists(p):
        print("SKIP- cli_integrated.py not found")
        return
    txt = open(p, "r", encoding="utf-8").read()
    orig = txt

    # Pydantic v2: заменяем доступ к __fields__ на кросс-версионный
    txt = txt.replace(
        "Config.__fields__",
        '(getattr(Config, "model_fields", {}) or getattr(Config, "__fields__", {}))'
    )

    if txt != orig:
        bak = p + ".bak_cli_fix_v5"
        shutil.copy2(p, bak)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt)
        print("OK  - Patched cli_integrated.py (pydantic fields fix). Backup:", os.path.basename(bak))
    else:
        print("SKIP- cli_integrated.py already OK")

if __name__ == "__main__":
    patch_live()
    patch_cli()
    print("Done.")
