"""
run_all.py — Orquestador de todos los benchmarks
=================================================
Corre los benchmarks en orden logico y genera un reporte final.
Los que NO requieren el bot (edgetts, stt, async_audit, powershell) corren siempre.
Los que requieren el bot (http, ytdlp) dan warning si el bot esta offline.

EJECUTAR desde el venv del rodolfo-bot (tiene todas las dependencias):
    cd C:/Users/Lenovo/Desktop/ProyectoAudio/_benchmarks
    python run_all.py [--quick] [--no-ytdlp] [--no-http]

Flags:
  --quick     : Reduce N_ITERATIONS a 2 para prueba rapida
  --no-ytdlp  : Salta yt-dlp (requiere internet y es lento)
  --no-http   : Salta HTTP (requiere el bot corriendo)
"""

import sys
import os
import subprocess
import time
import json
from datetime import datetime
from pathlib import Path

BENCH_DIR  = Path(__file__).parent
PYTHON     = sys.executable


def run_benchmark(script: str, label: str, required: bool = True) -> tuple[bool, str]:
    """Ejecuta un script de benchmark y captura su salida."""
    script_path = BENCH_DIR / script
    if not script_path.exists():
        print(f"  ⚠️  Script no encontrado: {script}")
        return False, ""

    print(f"\n{'='*65}")
    print(f"▶  {label}")
    print(f"{'='*65}")
    t0 = time.time()

    result = subprocess.run(
        [PYTHON, str(script_path)],
        capture_output=False,   # Mostrar output en tiempo real
        cwd=str(BENCH_DIR),
    )
    elapsed = time.time() - t0

    success = result.returncode == 0
    status  = "✅ OK" if success else "❌ ERROR"
    print(f"\n  {status} — Completado en {elapsed:.1f}s")
    return success, ""


def main():
    args        = sys.argv[1:]
    skip_ytdlp  = "--no-ytdlp" in args
    skip_http   = "--no-http"   in args

    print("=" * 65)
    print("RODO — SUITE COMPLETA DE BENCHMARKS DE LATENCIA")
    print(f"Python: {PYTHON}")
    print(f"Directorio: {BENCH_DIR}")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    results = {}

    # 1. Analisis estatico (no requiere nada externo)
    ok, _ = run_benchmark(
        "bench_async_audit.py",
        "1/5 — Auditoria Async/Await (analisis estatico)",
    )
    results["async_audit"] = ok

    # 2. STT: analisis del log existente (no requiere internet en este momento)
    ok, _ = run_benchmark(
        "bench_stt.py",
        "2/5 — STT Latency (analisis del performance_log.jsonl real)",
    )
    results["stt"] = ok

    # 3. PowerShell TTS local
    ok, _ = run_benchmark(
        "bench_powershell_tts.py",
        "3/5 — TTS Local PowerShell vs pyttsx3",
    )
    results["tts_local"] = ok

    # 4. edge-tts (requiere internet)
    ok, _ = run_benchmark(
        "bench_edgetts.py",
        "4/5 — edge-tts: save() vs stream() TTFB",
    )
    results["edgetts"] = ok

    # 5. HTTP latency (requiere bot corriendo)
    if not skip_http:
        ok, _ = run_benchmark(
            "bench_http.py",
            "5a/5 — HTTP Latency: sin Session vs con Session",
        )
        results["http"] = ok
    else:
        print("\n  [SKIP] HTTP benchmark (--no-http)")
        results["http"] = None

    # 6. yt-dlp (requiere internet, es lento)
    if not skip_ytdlp:
        ok, _ = run_benchmark(
            "bench_ytdlp.py",
            "5b/5 — yt-dlp: ytmsearch5 vs ytsearch1 vs URL directa",
        )
        results["ytdlp"] = ok
    else:
        print("\n  [SKIP] yt-dlp benchmark (--no-ytdlp)")
        results["ytdlp"] = None

    # Resumen final
    print("\n" + "=" * 65)
    print("RESUMEN DE EJECUCION")
    print("=" * 65)
    for name, ok in results.items():
        status = "✅ OK" if ok is True else ("⏭  SKIP" if ok is None else "❌ ERROR")
        result_file = BENCH_DIR / f"results_{name}.json"
        file_exists = "📄" if result_file.exists() else "  "
        print(f"  {status}  {file_exists}  {name}")

    print(f"\n  Resultados JSON en: {BENCH_DIR}")
    print("\n  PROXIMOS PASOS:")
    print("  1. Revisar results_async_audit.json para async falso")
    print("  2. Revisar results_stt.json para distribucion real STT")
    print("  3. Revisar results_edgetts.json para decision save() vs stream()")
    print("  4. Revisar results_ytdlp.json para decision ytmsearch vs ytsearch")
    print("  5. Revisar results_http.json para decision Session vs no-Session")


if __name__ == "__main__":
    main()
