"""
bench_edgetts.py — Benchmark de edge-tts: save() vs stream()
============================================================
Mide con precision:
  - Tiempo hasta primer byte de audio (TTFB)
  - Tiempo hasta archivo completo
  - Tamaño del MP3 generado
  - Relacion duracion_texto / latencia
  - Variabilidad entre ejecuciones (min/max/p50/p95)
"""

import asyncio
import time
import os
import tempfile
import statistics
import json
from datetime import datetime

import edge_tts

VOICE = "es-ES-ElviraNeural"

# Corpus de textos representativos de lo que Rodo realmente dice
TEST_TEXTS = [
    # Fast-path commands (lo mas frecuente)
    ("resp_skip",       "Saltando cancion"),
    ("resp_stop",       "Deteniendo la musica"),
    ("resp_pause",      "Pausada"),
    ("resp_resume",     "Continuando"),
    # Confirmacion de play (el caso mas critico)
    ("resp_play_short", "Poniendo despacito"),
    ("resp_play_med",   "Poniendo La Bicicleta de Carlos Vives y Shakira"),
    ("resp_play_long",  "Poniendo Mi Gente de J Balvin y Willy William. Agregando a la cola."),
    # Greeting / status (menos critico)
    ("resp_greet",      "Hola, que tal"),
    ("resp_status",     "Actualmente esta sonando Despacito de Luis Fonsi"),
    ("resp_long",       "Hola Brayan, acabo de conectarme al canal. No escuche bien tu cancion, podrias repetirla por favor?"),
]

N_ITERATIONS = 5   # Repeticiones por texto para calcular estadisticas


async def bench_save(text: str, n: int = N_ITERATIONS) -> dict:
    """Mide edge_tts.Communicate().save() — el modo actual de Rodo."""
    timings = []
    sizes   = []
    for _ in range(n):
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        t0 = time.perf_counter()
        communicate = edge_tts.Communicate(text, voice=VOICE)
        await communicate.save(tmp_path)
        elapsed = (time.perf_counter() - t0) * 1000  # ms

        size = os.path.getsize(tmp_path)
        timings.append(elapsed)
        sizes.append(size)
        os.unlink(tmp_path)

    return {
        "mode":     "save()",
        "n":        n,
        "mean_ms":  round(statistics.mean(timings), 1),
        "median_ms":round(statistics.median(timings), 1),
        "min_ms":   round(min(timings), 1),
        "max_ms":   round(max(timings), 1),
        "p95_ms":   round(sorted(timings)[int(n * 0.95)], 1) if n >= 5 else None,
        "stdev_ms": round(statistics.stdev(timings), 1) if n > 1 else 0,
        "mean_bytes": round(statistics.mean(sizes)),
    }


async def bench_stream_ttfb(text: str, n: int = N_ITERATIONS) -> dict:
    """
    Mide edge_tts stream() — tiempo hasta primer chunk de audio.
    TTFB = Time To First (audio) Byte.
    """
    ttfb_times  = []
    total_times = []
    chunk_counts = []

    for _ in range(n):
        t0 = time.perf_counter()
        ttfb = None
        chunks = 0

        communicate = edge_tts.Communicate(text, voice=VOICE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                if ttfb is None:
                    ttfb = (time.perf_counter() - t0) * 1000
                chunks += 1

        total = (time.perf_counter() - t0) * 1000
        if ttfb:
            ttfb_times.append(ttfb)
            total_times.append(total)
            chunk_counts.append(chunks)

    if not ttfb_times:
        return {"mode": "stream()", "error": "no audio chunks received"}

    return {
        "mode":           "stream()",
        "n":              n,
        "ttfb_mean_ms":   round(statistics.mean(ttfb_times), 1),
        "ttfb_median_ms": round(statistics.median(ttfb_times), 1),
        "ttfb_min_ms":    round(min(ttfb_times), 1),
        "ttfb_max_ms":    round(max(ttfb_times), 1),
        "total_mean_ms":  round(statistics.mean(total_times), 1),
        "total_median_ms":round(statistics.median(total_times), 1),
        "avg_chunks":     round(statistics.mean(chunk_counts), 1),
        "streaming_advantage_ms": round(statistics.mean(total_times) - statistics.mean(ttfb_times), 1),
    }


async def main():
    print("=" * 65)
    print("BENCHMARK: edge-tts  save() vs stream()")
    print(f"Voz: {VOICE}  |  {N_ITERATIONS} iteraciones por texto")
    print(f"Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    results = {}

    for label, text in TEST_TEXTS:
        print(f"\n[{label}] '{text[:55]}{'...' if len(text)>55 else ''}'")
        print(f"  chars={len(text)} palabras={len(text.split())}")

        save_r   = await bench_save(text)
        stream_r = await bench_stream_ttfb(text)

        advantage = save_r["mean_ms"] - stream_r.get("ttfb_mean_ms", save_r["mean_ms"])

        print(f"  save()  →  mean={save_r['mean_ms']}ms  median={save_r['median_ms']}ms  "
              f"min={save_r['min_ms']}ms  max={save_r['max_ms']}ms  "
              f"stdev={save_r['stdev_ms']}ms  size={save_r['mean_bytes']//1024}KB")

        if "error" not in stream_r:
            print(f"  stream()→  TTFB mean={stream_r['ttfb_mean_ms']}ms  "
                  f"TTFB min={stream_r['ttfb_min_ms']}ms  "
                  f"total={stream_r['total_mean_ms']}ms  "
                  f"chunks={stream_r['avg_chunks']}")
            print(f"  *** VENTAJA de stream sobre save: {advantage:.0f}ms "
                  f"({'si' if advantage > 0 else 'NO'} vale la pena)")
        else:
            print(f"  stream() → ERROR: {stream_r['error']}")

        results[label] = {
            "text_chars": len(text),
            "text_words": len(text.split()),
            "save":   save_r,
            "stream": stream_r,
            "streaming_advantage_ms": round(advantage, 1),
        }

    # Resumen final
    print("\n" + "=" * 65)
    print("RESUMEN — Impacto real del streaming TTS")
    print("=" * 65)
    print(f"{'Label':<20} {'save mean':>10} {'TTFB mean':>10} {'Ventaja':>10} {'Vale?':>6}")
    print("-" * 65)
    for label, r in results.items():
        save_ms = r["save"]["mean_ms"]
        ttfb_ms = r["stream"].get("ttfb_mean_ms", save_ms)
        adv     = r["streaming_advantage_ms"]
        vale    = "✅" if adv > 150 else ("~" if adv > 50 else "❌")
        print(f"  {label:<18} {save_ms:>9}ms {ttfb_ms:>9}ms {adv:>9}ms {vale:>6}")

    # Guardar JSON
    out_path = os.path.join(os.path.dirname(__file__), "results_edgetts.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts": datetime.now().isoformat(),
            "voice": VOICE,
            "n_iterations": N_ITERATIONS,
            "results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
