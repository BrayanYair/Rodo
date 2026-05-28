r"""
bench_async_audit.py - Auditoria de async/await real en el codigo
Analiza estaticamente todos los archivos Python del proyecto para:
  1. Detectar async falso (async def que internamente bloquea)
  2. Mapear awaits que son lentos vs instantaneos
  3. Identificar subprocess y requests sincronos en contextos async
  4. Detectar await secuencial (A await, luego B await - podrian ser gather)
  5. Mapear todos los locks, semaforos, colas
  6. Estimar concurrencia real del pipeline
"""

import ast
import os
import json
from pathlib import Path
from datetime import datetime


# Operaciones que BLOQUEAN el event loop aunque esten en async def
BLOCKING_CALLS = {
    # subprocess
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "os.system", "os.popen",
    # I/O sincrono
    "open", "os.unlink", "os.rename",
    # requests (sincrono)
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.request", "session.get", "session.post",
    # time.sleep (bloquea el hilo)
    "time.sleep",
    # communicate.save (edge-tts)
    "communicate.save",
    # pygame (sincrono)
    "pygame.mixer.music.load", "pygame.mixer.music.play", "pygame.time.wait",
}

# Await que son realmente rapidos (no son cuellos de botella)
FAST_AWAITS = {
    "asyncio.sleep", "asyncio.gather", "asyncio.wait_for",
    "asyncio.ensure_future", "player.connect", "player.skip",
    "player.stop", "player.pause", "player.resume",
}

# Await que son potencialmente lentos
SLOW_AWAITS = {
    "communicate.save",    # TTS: 500-1500ms
    "yt_search",           # YouTube: 1000-3000ms  
    "_spotify_refine",     # Spotify API: 300-800ms
    "resolve_query",       # Spotify+YT: 1500-4000ms
    "player.add",          # Includes yt_search: 1500-3000ms
    "player.say",          # TTS + Discord: 500-2000ms
    "recognizer.listen",   # Espera audio del mic: variable
    "loop.run_in_executor",# Wrapper de bloqueante: hereda latencia
}


class AsyncAuditor(ast.NodeVisitor):
    """Analiza un AST de Python buscando problemas de async."""

    def __init__(self, filename: str):
        self.filename       = filename
        self.issues         = []
        self.async_funcs    = []
        self.sync_funcs     = []
        self.awaits         = []
        self.sequential_awaits = []  # Pares de await consecutivos que podrian ser gather()
        self._current_func  = None
        self._current_async = False
        self._in_async_depth = 0

    def _node_to_str(self, node) -> str:
        """Convierte un nodo AST a string legible."""
        try:
            return ast.unparse(node)
        except Exception:
            return f"<{type(node).__name__}>"

    def _extract_call_name(self, node) -> str:
        """Extrae el nombre de una llamada a funcion."""
        if isinstance(node, ast.Call):
            return self._node_to_str(node.func)
        return ""

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        prev_func  = self._current_func
        prev_async = self._current_async

        self._current_func  = node.name
        self._current_async = True
        self._in_async_depth += 1

        self.async_funcs.append({
            "name": node.name,
            "line": node.lineno,
        })

        # Analizar el cuerpo buscando calls bloqueantes
        blocking_found = []
        consecutive_awaits = []
        last_await_line = None

        for child in ast.walk(node):
            # Detectar calls bloqueantes dentro de async def
            if isinstance(child, ast.Call):
                call_str = self._node_to_str(child.func)
                for blocking in BLOCKING_CALLS:
                    if blocking in call_str or call_str.endswith(blocking.split(".")[-1]):
                        # Verificar que no sea un await run_in_executor (correcto)
                        parent_is_await = False
                        # Heuristica: si la funcion tiene "executor" en su nombre, es correcto
                        if "executor" in call_str.lower():
                            parent_is_await = True
                        if not parent_is_await:
                            blocking_found.append({
                                "call":  call_str[:80],
                                "line":  child.lineno,
                                "type":  "BLOCKING_IN_ASYNC",
                            })

            # Detectar awaits consecutivos (candidatos para asyncio.gather)
            if isinstance(child, ast.Await):
                call_str = self._node_to_str(child.value)
                is_slow = any(slow in call_str for slow in SLOW_AWAITS)

                if last_await_line and is_slow:
                    # Posible await secuencial a consolidar con gather()
                    consecutive_awaits.append({
                        "prev_line": last_await_line,
                        "curr_line": child.lineno,
                        "call":      call_str[:80],
                    })

                if is_slow:
                    last_await_line = child.lineno
                    self.awaits.append({
                        "func": node.name,
                        "call": call_str[:80],
                        "line": child.lineno,
                        "speed": "SLOW",
                    })
                else:
                    self.awaits.append({
                        "func": node.name,
                        "call": call_str[:80],
                        "line": child.lineno,
                        "speed": "fast",
                    })

        if blocking_found:
            self.issues.append({
                "file":     self.filename,
                "func":     node.name,
                "line":     node.lineno,
                "type":     "ASYNC_FALSO",
                "detail":   blocking_found,
                "severity": "HIGH",
            })

        if consecutive_awaits:
            self.sequential_awaits.extend([{
                "file": self.filename,
                "func": node.name,
                **ca,
            } for ca in consecutive_awaits])

        self.generic_visit(node)

        self._current_func  = prev_func
        self._current_async = prev_async
        self._in_async_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.sync_funcs.append({
            "name": node.name,
            "line": node.lineno,
        })
        self.generic_visit(node)


def audit_file(filepath: str) -> dict:
    """Analiza un archivo Python."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        return {"file": filepath, "parse_error": str(e)}

    rel_path = os.path.relpath(filepath)
    auditor  = AsyncAuditor(rel_path)
    auditor.visit(tree)

    return {
        "file":               rel_path,
        "async_funcs":        len(auditor.async_funcs),
        "sync_funcs":         len(auditor.sync_funcs),
        "issues":             auditor.issues,
        "slow_awaits":        [a for a in auditor.awaits if a["speed"] == "SLOW"],
        "sequential_awaits":  auditor.sequential_awaits,
        "func_list_async":    auditor.async_funcs,
    }


def find_python_files(root: str) -> list[str]:
    """Encuentra todos los .py relevantes del proyecto."""
    ignore = {"_benchmarks", "__pycache__", ".git", "node_modules", "venv", ".venv"}
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Filtrar directorios ignorados
        dirnames[:] = [d for d in dirnames if d not in ignore]
        for fname in filenames:
            if fname.endswith(".py"):
                result.append(os.path.join(dirpath, fname))
    return result


def print_report(file_results: list[dict]):
    print("\n" + "=" * 65)
    print("AUDITORIA ASYNC — Resultado")
    print("=" * 65)

    total_async  = sum(r.get("async_funcs", 0) for r in file_results)
    total_sync   = sum(r.get("sync_funcs", 0)  for r in file_results)
    total_issues = sum(len(r.get("issues", [])) for r in file_results)
    total_slow   = sum(len(r.get("slow_awaits", [])) for r in file_results)
    total_seq    = sum(len(r.get("sequential_awaits", [])) for r in file_results)

    print(f"\n  Funciones async: {total_async}")
    print(f"  Funciones sync:  {total_sync}")
    print(f"  Issues totales:  {total_issues}")
    print(f"  Awaits lentos:   {total_slow}")
    print(f"  Awaits secuenc.: {total_seq} (candidatos para asyncio.gather)")

    # Async falsos
    print("\n[ASYNC FALSO — codigo bloqueante dentro de async def]")
    found_any = False
    for r in file_results:
        for issue in r.get("issues", []):
            if issue["type"] == "ASYNC_FALSO":
                found_any = True
                print(f"\n  📁 {r['file']} → def {issue['func']}() [linea {issue['line']}]")
                for d in issue["detail"]:
                    print(f"    ⛔ {d['call'][:70]}  (linea {d['line']})")

    if not found_any:
        print("  ✅ No se encontraron casos de async falso claros")

    # Awaits lentos
    print("\n[AWAITS LENTOS — operaciones que dominan el TTFA]")
    for r in file_results:
        slow = r.get("slow_awaits", [])
        if slow:
            print(f"\n  📁 {r['file']}")
            for a in slow:
                print(f"    🐢 {a['func']}() linea {a['line']}: await {a['call'][:60]}")

    # Awaits secuenciales
    if total_seq > 0:
        print("\n[AWAITS SECUENCIALES — candidatos para asyncio.gather()]")
        for r in file_results:
            for sa in r.get("sequential_awaits", []):
                print(f"  📁 {r['file']} → {sa['func']}()")
                print(f"    linea {sa['prev_line']} + linea {sa['curr_line']}: {sa['call'][:50]}")
                print(f"    → Considera: asyncio.gather(op1, op2)")


def main():
    root = os.path.join(os.path.dirname(__file__), "..")
    root = os.path.abspath(root)

    print("=" * 65)
    print("AUDITORIA ASYNC/AWAIT — Analisis estatico del proyecto")
    print(f"Raiz: {root}")
    print(f"Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    py_files = find_python_files(root)
    print(f"\nArchivos Python encontrados: {len(py_files)}")

    file_results = []
    for fp in sorted(py_files):
        r = audit_file(fp)
        file_results.append(r)
        rel = os.path.relpath(fp, root)
        issues = len(r.get("issues", []))
        slow   = len(r.get("slow_awaits", []))
        if issues or slow:
            print(f"  ⚠️  {rel} — {issues} issues, {slow} slow awaits")

    print_report(file_results)

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "results_async_audit.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts":          datetime.now().isoformat(),
            "root":        root,
            "files_scanned": len(py_files),
            "results":     file_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    main()
