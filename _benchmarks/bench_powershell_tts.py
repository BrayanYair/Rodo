"""
bench_powershell_tts.py — Benchmark de TTS local (Windows SAPI via PowerShell)
==============================================================================
Amigo.py usa subprocess.run(["powershell", ...]) para TTS local.
Este benchmark mide:
  - Tiempo de startup de PowerShell
  - Latencia total (startup + TTS)
  - Comparacion con alternativas: pyttsx3, edge-tts local

EJECUTAR:
    cd C:/Users/Lenovo/Desktop/ProyectoAudio/_benchmarks
    python bench_powershell_tts.py
"""

import subprocess
import time
import statistics
import json
import os
from datetime import datetime

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

N_ITERATIONS = 5

TEST_TEXTS = [
    ("short",   "Ok"),
    ("medium",  "Poniendo despacito"),
    ("long",    "Hola, acabo de conectarme al canal de voz"),
]


def bench_powershell_speak(text: str, n: int = N_ITERATIONS) -> dict:
    """Mide el modo actual: subprocess PowerShell SAPI."""
    timings = []
    safe    = text.replace("'", "").replace('"', "")
    cmd     = [
        "powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-Command",
        f"Add-Type -AssemblyName System.Speech; "
        f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = 1; $s.Speak('{safe}')"
    ]

    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run(cmd, timeout=20, creationflags=_NO_WINDOW,
                       capture_output=True)
        elapsed = (time.perf_counter() - t0) * 1000
        timings.append(elapsed)

    return {
        "mode":      "powershell_sapi",
        "n":         n,
        "mean_ms":   round(statistics.mean(timings), 1),
        "median_ms": round(statistics.median(timings), 1),
        "min_ms":    round(min(timings), 1),
        "max_ms":    round(max(timings), 1),
        "stdev_ms":  round(statistics.stdev(timings), 1) if n > 1 else 0,
        "note":      "incluye startup PS + TTS + reproduccion completa",
    }


def bench_powershell_startup_only(n: int = N_ITERATIONS) -> dict:
    """
    Mide SOLO el startup de PowerShell (sin TTS).
    Esto nos dice cuanto del tiempo es PS overhead vs TTS real.
    """
    timings = []
    cmd     = [
        "powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-Command", "exit 0"
    ]

    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run(cmd, timeout=10, creationflags=_NO_WINDOW,
                       capture_output=True)
        elapsed = (time.perf_counter() - t0) * 1000
        timings.append(elapsed)

    return {
        "mode":      "powershell_startup_only",
        "n":         n,
        "mean_ms":   round(statistics.mean(timings), 1),
        "median_ms": round(statistics.median(timings), 1),
        "min_ms":    round(min(timings), 1),
        "max_ms":    round(max(timings), 1),
        "stdev_ms":  round(statistics.stdev(timings), 1) if n > 1 else 0,
        "note":      "SOLO startup PowerShell, sin hablar",
    }


def bench_pyttsx3(text: str, n: int = N_ITERATIONS) -> dict:
    """
    Mide pyttsx3 como alternativa.
    pyttsx3 reutiliza el engine (sin startup por frase).
    """
    try:
        import pyttsx3
    except ImportError:
        return {
            "mode":  "pyttsx3",
            "error": "pyttsx3 no instalado (pip install pyttsx3)",
        }

    timings = []
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)

        # Warmup
        engine.save_to_file(text, os.devnull)
        engine.runAndWait()

        for _ in range(n):
            t0 = time.perf_counter()
            engine.say(text)
            engine.runAndWait()
            elapsed = (time.perf_counter() - t0) * 1000
            timings.append(elapsed)

        engine.stop()
    except Exception as e:
        return {"mode": "pyttsx3", "error": str(e)}

    return {
        "mode":      "pyttsx3",
        "n":         n,
        "mean_ms":   round(statistics.mean(timings), 1),
        "median_ms": round(statistics.median(timings), 1),
        "min_ms":    round(min(timings), 1),
        "max_ms":    round(max(timings), 1),
        "stdev_ms":  round(statistics.stdev(timings), 1) if n > 1 else 0,
        "note":      "engine reutilizado — sin startup por frase",
    }


def main():
    print("=" * 65)
    print("BENCHMARK: TTS Local — PowerShell SAPI vs pyttsx3")
    print(f"Iteraciones: {N_ITERATIONS}")
    print(f"Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    all_results = []

    # Medir startup de PS solamente
    print("\n[PowerShell startup-only (overhead fijo por llamada)]")
    startup_r = bench_powershell_startup_only()
    all_results.append(startup_r)
    print(f"  mean={startup_r['mean_ms']}ms  min={startup_r['min_ms']}ms  "
          f"max={startup_r['max_ms']}ms  stdev={startup_r['stdev_ms']}ms")
    print(f"  → Este overhead se paga en CADA llamada a _speak_local()")

    # Por texto
    for label, text in TEST_TEXTS:
        print(f"\n[{label}] '{text}'")

        print("  PowerShell SAPI:", end=" ", flush=True)
        ps_r = bench_powershell_speak(text)
        all_results.append({"label": label, **ps_r})
        tts_only = ps_r["mean_ms"] - startup_r["mean_ms"]
        print(f"total={ps_r['mean_ms']}ms  startup={startup_r['mean_ms']:.0f}ms  "
              f"tts_only≈{tts_only:.0f}ms")

        print("  pyttsx3:", end=" ", flush=True)
        py_r = bench_pyttsx3(text)
        all_results.append({"label": label, **py_r})
        if "error" not in py_r:
            print(f"mean={py_r['mean_ms']}ms  (ahorro vs PS: "
                  f"{ps_r['mean_ms'] - py_r['mean_ms']:.0f}ms)")
        else:
            print(f"ERROR: {py_r['error']}")

    # Resumen
    print("\n" + "=" * 65)
    print("RESUMEN — Impacto real del TTS local en amigo.py")
    print("=" * 65)
    print(f"\n  Startup PowerShell: ~{startup_r['mean_ms']:.0f}ms (overhead fijo)")
    print(f"  Cada vez que amigo habla, paga este overhead ANTES de decir nada")
    print(f"  En modo Discord (TTS_OUTPUT=discord), amigo.py NO habla localmente")
    print(f"  → El TTS local solo importa si el usuario usa modo 'local' o 'both'")

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "results_tts_local.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts":      datetime.now().isoformat(),
            "n":       N_ITERATIONS,
            "results": all_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    main()
