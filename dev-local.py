"""
dev-local.py — Lanza rodolfo-bot/ y rodolfo-host/ en una sola ventana
para probar la nueva estructura localmente antes del deploy a Hetzner.

Uso:
    python dev-local.py
    o doble clic en dev-local.bat
"""

import os
import sys
import time
import threading
import subprocess
from pathlib import Path

if sys.platform == "win32":
    os.system("")

BASE   = Path(__file__).parent
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


class TaggedProcess:
    def __init__(self, label, color, cwd, script):
        self.label = label
        self.color = color
        self.cwd = cwd
        self.script = script
        self.proc = None

    def start(self):
        path = self.cwd / self.script
        if not path.exists():
            print(f"{RED}[LAUNCHER] No encuentro {path}{RESET}")
            return False

        self.proc = subprocess.Popen(
            [sys.executable, "-u", self.script],
            cwd=str(self.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1, text=True, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=self._pump, daemon=True).start()
        return True

    def _pump(self):
        prefix = f"{self.color}{BOLD}[{self.label}]{RESET}"
        try:
            for line in self.proc.stdout:
                line = line.rstrip()
                if line:
                    print(f"{prefix} {line}", flush=True)
        except Exception:
            pass

    def is_alive(self):
        return self.proc and self.proc.poll() is None

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        except Exception:
            pass


def main():
    print(f"{YELLOW}{BOLD}=== Rodolfo (Local Dev) ==={RESET}")
    print(f"{GRAY}  Bot: rodolfo-bot/bot.py{RESET}")
    print(f"{GRAY}  Host: rodolfo-host/controller.py{RESET}")
    print()

    bot  = TaggedProcess("BOT",  CYAN,  BASE / "rodolfo-bot",  "bot.py")
    host = TaggedProcess("HOST", GREEN, BASE / "rodolfo-host", "controller.py")

    print(f"{GRAY}[1/2]{RESET} Iniciando bot...")
    if not bot.start():
        return 1

    print(f"{GRAY}      Esperando 7s a que conecte...{RESET}")
    time.sleep(7)

    print(f"{GRAY}[2/2]{RESET} Iniciando host...")
    if not host.start():
        bot.stop()
        return 1

    print(f"\n{GREEN}{BOLD}[OK] Todo arriba.{RESET}  Ctrl+C para detener.\n")

    try:
        while True:
            time.sleep(1)
            if not bot.is_alive():
                print(f"\n{RED}[LAUNCHER] BOT se cerró.{RESET}")
                break
            if not host.is_alive():
                print(f"\n{RED}[LAUNCHER] HOST se cerró.{RESET}")
                break
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[LAUNCHER] Cerrando...{RESET}")
    finally:
        host.stop()
        bot.stop()
        print(f"{GRAY}[LAUNCHER] Bye.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
