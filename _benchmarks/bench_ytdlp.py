"""
bench_ytdlp.py — Benchmark de yt-dlp: latencia real por tipo de query
======================================================================
Mide con precision:
  - Tiempo de extraccion por tipo de busqueda
  - ytmsearch5 vs ytsearch1 vs URL directa
  - Con y sin Spotify refine
  - Variabilidad (stdev, min/max)
  - Impacto del re-fetch de URL fresca

EJECUTAR (con el venv del rodolfo-bot activo):
    cd C:\Users\Lenovo\Desktop\ProyectoAudio\_benchmarks
    python bench_ytdlp.py
"""

import asyncio
import time
import statistics
import json
import os
import sys
from datetime import datetime

# Agregar rodolfo-bot al path para importar sus modulos
BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "rodolfo-bot")
sys.path.insert(0, BOT_DIR)

try:
    import yt_dlp
except ImportError:
    print("ERROR: yt_dlp no instalado en este entorno")
    print("Ejecuta desde el venv de rodolfo-bot")
    sys.exit(1)

# Opciones identicas a las de search.py
YTDL_OPTIONS = {
    "format":         "bestaudio/best",
    "noplaylist":     True,
    "quiet":          True,
    "no_warnings":    True,
    "source_address": "0.0.0.0",
}

N_ITERATIONS = 3  # yt-dlp es lento, 3 iteraciones son suficientes

TEST_QUERIES = [
    # (label, query, modo)
    ("ytmsearch_song",        "despacito luis fonsi",           "ytmsearch5"),
    ("ytmsearch_song2",       "la bicicleta carlos vives",      "ytmsearch5"),
    ("ytmsearch_spanish",     "canserbero epico",               "ytmsearch5"),
    ("ytsearch1_fast",        "despacito luis fonsi",           "ytsearch1"),
    ("ytsearch1_fast2",       "mi gente j balvin",              "ytsearch1"),
    ("ytmsearch_ambiguous",   "perdoname",                      "ytmsearch5"),
    ("ytmsearch_short",       "ponte",                          "ytmsearch5"),
    ("ytmsearch_nquery",      "tengo un angel",                 "ytmsearch5"),
]

# Queries con URL directa (las mas rapidas teoricamente)
DIRECT_URL_QUERIES = [
    ("direct_url_short", "https://www.youtube.com/watch?v=kTJczUoc26U"),  # Despacito
]


def _extract_sync(ytdl, query: str) -> tuple[dict, float]:
    """Extrae info de yt-dlp sincronamente y retorna (info, elapsed_ms)."""
    t0 = time.perf_counter()
    try:
        info = ytdl.extract_info(query, download=False)
        elapsed = (time.perf_counter() - t0) * 1000

        # Normalizar: tomar el primer entry si es una lista
        if "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if entry and (entry.get("url") or entry.get("formats")):
                    return {"title": entry.get("title","?"), "url": entry.get("url","")}, elapsed
            info = info["entries"][0]

        return {"title": info.get("title","?"), "url": info.get("url","")}, elapsed
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {"error": str(e)}, elapsed


async def bench_query(label: str, query_text: str, search_mode: str) -> dict:
    """Benchmark de una query especifica en N iteraciones."""
    ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
    loop = asyncio.get_event_loop()

    if search_mode == "ytmsearch5":
        full_query = f"ytmsearch5:{query_text}"
    elif search_mode == "ytsearch1":
        full_query = f"ytsearch1:{query_text}"
    else:
        full_query = query_text  # URL directa

    timings = []
    results = []

    for i in range(N_ITERATIONS):
        print(f"    iter {i+1}/{N_ITERATIONS}", end=" ", flush=True)
        result, elapsed = await loop.run_in_executor(None, _extract_sync, ytdl, full_query)
        timings.append(elapsed)
        results.append(result)
        print(f"→ {elapsed:.0f}ms", end="")
        if "error" in result:
            print(f" [ERROR: {result['error'][:40]}]")
        else:
            print(f" '{result['title'][:40]}'")

    valid_timings = [t for t, r in zip(timings, results) if "error" not in r]
    errors = len(timings) - len(valid_timings)

    if not valid_timings:
        return {
            "label":  label,
            "query":  query_text,
            "mode":   search_mode,
            "error":  "all iterations failed",
            "errors": errors,
        }

    return {
        "label":      label,
        "query":      query_text,
        "mode":       search_mode,
        "n":          N_ITERATIONS,
        "errors":     errors,
        "mean_ms":    round(statistics.mean(valid_timings), 1),
        "median_ms":  round(statistics.median(valid_timings), 1),
        "min_ms":     round(min(valid_timings), 1),
        "max_ms":     round(max(valid_timings), 1),
        "stdev_ms":   round(statistics.stdev(valid_timings), 1) if len(valid_timings) > 1 else 0,
        "title_sample": results[0].get("title", "?")[:50],
    }


async def bench_url_refresh(url: str, n: int = 3) -> dict:
    """
    Mide el tiempo del re-fetch de URL fresca que hace _play_track().
    Este es el yt_search() que se hace OTRA VEZ antes de reproducir.
    """
    print(f"  [url_refresh] Midiendo re-fetch de URL fresca...")
    ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
    loop = asyncio.get_event_loop()
    timings = []

    for i in range(n):
        result, elapsed = await loop.run_in_executor(None, _extract_sync, ytdl, url)
        timings.append(elapsed)
        print(f"    iter {i+1}: {elapsed:.0f}ms")

    return {
        "mode":     "direct_url_refresh",
        "mean_ms":  round(statistics.mean(timings), 1),
        "min_ms":   round(min(timings), 1),
        "max_ms":   round(max(timings), 1),
    }


async def main():
    print("=" * 65)
    print("BENCHMARK: yt-dlp")
    print(f"Iteraciones: {N_ITERATIONS} por query")
    print(f"Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    all_results = []

    # Benchmark por modo de busqueda
    for label, query, mode in TEST_QUERIES:
        print(f"\n[{label}] '{query}' ({mode})")
        r = await bench_query(label, query, mode)
        all_results.append(r)

    # Benchmark de URL directa
    for label, url in DIRECT_URL_QUERIES:
        print(f"\n[{label}] URL directa")
        r = await bench_query(label, url, "direct_url")
        all_results.append(r)

    # Benchmark de re-fetch (el que hace _play_track antes de reproducir)
    print(f"\n[url_refresh] Re-fetch de URL fresca (como en player._play_track)")
    refresh_r = await bench_url_refresh("https://www.youtube.com/watch?v=kTJczUoc26U")
    all_results.append({"label": "url_refresh", **refresh_r})

    # Resumen
    print("\n" + "=" * 65)
    print("RESUMEN — yt-dlp latencia por modo")
    print("=" * 65)
    print(f"{'Label':<25} {'Modo':<12} {'Mean':>8} {'Median':>8} {'Min':>8} {'Max':>8} {'Stdev':>8}")
    print("-" * 65)
    for r in all_results:
        if "error" not in r and "mean_ms" in r:
            print(f"  {r['label']:<23} {r.get('mode',''):<12} "
                  f"{r['mean_ms']:>7}ms {r.get('median_ms','-'):>7}ms "
                  f"{r['min_ms']:>7}ms {r['max_ms']:>7}ms "
                  f"{r.get('stdev_ms',0):>7}ms")
        elif "error" in r:
            print(f"  {r['label']:<23}  ERROR: {r.get('error','?')[:30]}")

    # Comparativa ytmsearch5 vs ytsearch1
    ms5 = [r for r in all_results if r.get("mode") == "ytmsearch5"]
    ms1 = [r for r in all_results if r.get("mode") == "ytsearch1" and "mean_ms" in r]
    if ms5 and ms1:
        avg5 = statistics.mean([r["mean_ms"] for r in ms5 if "mean_ms" in r])
        avg1 = statistics.mean([r["mean_ms"] for r in ms1])
        print(f"\n[COMPARATIVA ytmsearch5 vs ytsearch1]")
        print(f"  ytmsearch5 promedio: {avg5:.0f}ms (busca en YouTube Music, mas precisa)")
        print(f"  ytsearch1  promedio: {avg1:.0f}ms (busqueda directa YouTube, mas rapida)")
        print(f"  Diferencia: {avg5-avg1:.0f}ms — ytsearch1 {'ES' if avg1 < avg5 else 'NO ES'} mas rapida")

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "results_ytdlp.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts":         datetime.now().isoformat(),
            "iterations": N_ITERATIONS,
            "results":    all_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
