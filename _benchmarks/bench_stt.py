"""
bench_stt.py - Benchmark de Google STT: latencia por duracion de audio
Usa los datos reales del performance_log.jsonl para calcular:
  - Distribucion de latencia STT por duracion
  - Percentiles reales (P50, P95, P99)
  - Outliers
  - Impacto del socket timeout (3s)
  - Tasa de error (UnknownValueError)
  - Hot path vs cold path
"""

import json
import statistics
import os
from collections import defaultdict
from datetime import datetime

# Path al log de performance del rodolfo-host
PERF_LOG = os.path.join(
    os.path.dirname(__file__), "..", "rodolfo-host", "performance_log.jsonl"
)


def load_perf_log(path: str) -> list[dict]:
    """Carga el performance_log.jsonl y filtra entradas validas."""
    entries = []
    errors  = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if isinstance(e.get("stt_ms"), (int, float)) and e["stt_ms"] > 0:
                    entries.append(e)
            except Exception:
                errors += 1
    print(f"[LOAD] {len(entries)} entradas validas, {errors} errores de parse")
    return entries


def percentile(data: list[float], p: float) -> float:
    """Calcula el percentil p (0-100) de una lista de numeros."""
    sorted_d = sorted(data)
    idx = int(len(sorted_d) * p / 100)
    return sorted_d[min(idx, len(sorted_d) - 1)]


def analyze_stt(entries: list[dict]):
    """Analiza la distribucion de latencia STT."""
    all_stt    = [e["stt_ms"] for e in entries]
    commands   = [e for e in entries if e.get("action") not in ("ignored", None)]
    ignored    = [e for e in entries if e.get("action") == "ignored"]

    print("\n" + "=" * 65)
    print("ANALISIS STT — Performance Log Real")
    print(f"Total eventos: {len(entries)} | Comandos: {len(commands)} | Ignorados: {len(ignored)}")
    print("=" * 65)

    # Distribucion global
    print("\n[DISTRIBUCION GLOBAL — todo el audio que procesa STT]")
    print(f"  N:       {len(all_stt)}")
    print(f"  Media:   {statistics.mean(all_stt):.0f}ms")
    print(f"  Mediana: {statistics.median(all_stt):.0f}ms")
    print(f"  Stdev:   {statistics.stdev(all_stt):.0f}ms")
    print(f"  Min:     {min(all_stt):.0f}ms")
    print(f"  Max:     {max(all_stt):.0f}ms")
    print(f"  P50:     {percentile(all_stt, 50):.0f}ms")
    print(f"  P75:     {percentile(all_stt, 75):.0f}ms")
    print(f"  P90:     {percentile(all_stt, 90):.0f}ms")
    print(f"  P95:     {percentile(all_stt, 95):.0f}ms")
    print(f"  P99:     {percentile(all_stt, 99):.0f}ms")

    # Outliers (>3s — probables timeouts de red)
    outliers_3s = [x for x in all_stt if x > 3000]
    outliers_5s = [x for x in all_stt if x > 5000]
    print(f"\n  Outliers >3s: {len(outliers_3s)} ({100*len(outliers_3s)/len(all_stt):.1f}%)")
    print(f"  Outliers >5s: {len(outliers_5s)} ({100*len(outliers_5s)/len(all_stt):.1f}%)")
    if outliers_3s:
        print(f"  Max outlier:  {max(outliers_3s):.0f}ms")

    # Solo comandos exitosos (el que le importa al usuario)
    if commands:
        cmd_stt = [e["stt_ms"] for e in commands]
        print(f"\n[SOLO COMANDOS CON ACTIVADOR (n={len(commands)})]")
        print(f"  Media:   {statistics.mean(cmd_stt):.0f}ms")
        print(f"  Mediana: {statistics.median(cmd_stt):.0f}ms")
        print(f"  P95:     {percentile(cmd_stt, 95):.0f}ms")

    # Distribucion por buckets de tiempo
    print("\n[HISTOGRAMA STT (buckets de 500ms)]")
    buckets = defaultdict(int)
    for ms in all_stt:
        bucket = int(ms // 500) * 500
        buckets[bucket] += 1
    for bucket in sorted(buckets):
        count = buckets[bucket]
        bar   = "█" * (count * 30 // len(all_stt))
        label = f"{bucket}-{bucket+499}ms"
        pct   = 100 * count / len(all_stt)
        print(f"  {label:<15} {bar:<32} {count:>4} ({pct:4.1f}%)")

    # Cuanto aporta el socket timeout de 3s
    pct_over_3s = 100 * len(outliers_3s) / len(all_stt)
    print(f"\n[IMPACTO DEL SOCKET TIMEOUT = 3s]")
    print(f"  El {pct_over_3s:.1f}% de los STTs superan 3s → son los que el timeout detiene")
    print(f"  Sin timeout: esos esperarian hasta la respuesta de Google (potencialmente 10s+)")
    print(f"  El timeout AYUDA pero genera RequestError → se descarta el audio")

    # Impacto hipotetico de reducir pause_threshold
    # En amigo.py: pause_threshold = 0.8s (default)
    # En host: pause_threshold = 0.5s
    # La diferencia va AL INICIO antes del STT (en la fase de VAD)
    # No aparece en stt_ms (ese solo mide el tiempo de recognize_google)
    print(f"\n[NOTA SOBRE pause_threshold]")
    print(f"  El stt_ms mide SOLO el tiempo de recognize_google() en nube")
    print(f"  El pause_threshold (0.8s en amigo, 0.5s en host) ocurre ANTES")
    print(f"  No esta capturado en este log — es latencia 'invisible' al sistema")
    print(f"  Impacto estimado de amigo vs host: +300ms por comando")

    # first_response_ms
    resp_entries = [e for e in commands if isinstance(e.get("first_response_ms"), (int, float))]
    if resp_entries:
        resp_ms = [e["first_response_ms"] for e in resp_entries]
        print(f"\n[FIRST RESPONSE MS — tiempo STT hasta primer speak()]")
        print(f"  N:       {len(resp_ms)}")
        print(f"  Media:   {statistics.mean(resp_ms):.1f}ms")
        print(f"  Mediana: {statistics.median(resp_ms):.1f}ms")
        print(f"  Max:     {max(resp_ms):.0f}ms")
        print(f"  Nota: este mide desde STT hasta speak() — NO hasta audio en Discord")

    # Por accion
    by_action = defaultdict(list)
    for e in commands:
        by_action[e.get("action", "unknown")].append(e["stt_ms"])

    if len(by_action) > 1:
        print(f"\n[STT POR TIPO DE ACCION]")
        for action, times in sorted(by_action.items()):
            print(f"  {action:<20}  n={len(times):<4} "
                  f"median={statistics.median(times):.0f}ms "
                  f"max={max(times):.0f}ms")

    return {
        "total": len(all_stt),
        "mean_ms": round(statistics.mean(all_stt), 1),
        "median_ms": round(statistics.median(all_stt), 1),
        "p95_ms": round(percentile(all_stt, 95), 1),
        "p99_ms": round(percentile(all_stt, 99), 1),
        "outliers_3s_pct": round(pct_over_3s, 1),
        "commands_n": len(commands),
    }


def analyze_hot_paths(entries: list[dict]):
    """Analiza cuales son los comandos mas frecuentes (hot paths reales)."""
    print("\n" + "=" * 65)
    print("HOT PATHS — Comandos mas frecuentes en uso real")
    print("=" * 65)

    from collections import Counter
    action_counts = Counter(e.get("action", "unknown") for e in entries)

    total = len(entries)
    print(f"\n{'Accion':<25} {'Count':>6} {'%':>6}  {'Categoria'}")
    print("-" * 65)
    for action, count in action_counts.most_common(20):
        pct = 100 * count / total
        cat = "FAST-PATH" if action in ("skip_music","stop_music","pause_music","resume_music") else \
              "SLOW-PATH" if action in ("play_music","queue_music") else \
              "NOOP"
        print(f"  {action:<23} {count:>6} {pct:>6.1f}%  {cat}")

    # Tasa de conversion: cuantos STTs resultan en comandos reales
    real_commands = sum(1 for e in entries if e.get("action") not in ("ignored", "unknown", None))
    print(f"\n[TASA DE CONVERSION STT → COMANDO]")
    print(f"  Total STTs procesados: {total}")
    print(f"  Resultaron en comando: {real_commands} ({100*real_commands/total:.1f}%)")
    print(f"  Descartados (ignored): {total - real_commands} ({100*(total-real_commands)/total:.1f}%)")
    print(f"  → El {100*(total-real_commands)/total:.0f}% del trabajo de STT es 'ruido' — no activa nada")

    return dict(action_counts)


def main():
    print("=" * 65)
    print("BENCHMARK STT — Analisis de Performance Log Real")
    print(f"Log: {os.path.abspath(PERF_LOG)}")
    print(f"Timestamp: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    if not os.path.exists(PERF_LOG):
        print(f"ERROR: No se encontro el log en {PERF_LOG}")
        return

    entries = load_perf_log(PERF_LOG)
    if not entries:
        print("ERROR: Log vacio o sin entradas validas")
        return

    stt_stats    = analyze_stt(entries)
    action_dist  = analyze_hot_paths(entries)

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "results_stt.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts":          datetime.now().isoformat(),
            "log_path":    PERF_LOG,
            "stt_stats":   stt_stats,
            "action_dist": action_dist,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    main()
