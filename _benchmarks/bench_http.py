"""
bench_http.py — Benchmark HTTP: latencia de llamadas al bot
============================================================
Mide con precision:
  - Tiempo de request al bot (localhost vs ngrok)
  - Con y sin requests.Session() (connection reuse)
  - Endpoints fast-path: /skip, /stop, /pause
  - Endpoint slow-path: /command (parse incluido)
  - Latencia de /context (el que amigo.py llama en el hot path)
  - Impacto de TCP handshake repetido vs Session reutilizada

EJECUTAR (con el bot corriendo):
    cd C:\Users\Lenovo\Desktop\ProyectoAudio\_benchmarks
    python bench_http.py
"""

import time
import statistics
import json
import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

# Cargar .env del rodolfo-host para obtener el token
HOST_ENV = os.path.join(os.path.dirname(__file__), "..", "rodolfo-host", ".env")
BOT_ENV  = os.path.join(os.path.dirname(__file__), "..", "rodolfo-bot", ".env")

for env_path in [HOST_ENV, BOT_ENV]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

BOT_URL   = os.getenv("MUSIC_BOT_URL", "http://127.0.0.1:5000").rstrip("/")
API_TOKEN = os.getenv("API_TOKEN", "")

N_ITERATIONS = 10  # 10 requests por endpoint para estadisticas


def make_headers():
    h = {}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def bench_endpoint_no_session(method: str, path: str, body: dict = None,
                               n: int = N_ITERATIONS) -> dict:
    """Sin requests.Session() — nueva conexion TCP cada vez (modo actual del host)."""
    url     = f"{BOT_URL}{path}"
    headers = make_headers()
    timings = []
    errors  = 0

    for _ in range(n):
        t0 = time.perf_counter()
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=5)
            else:
                r = requests.post(url, json=body or {}, headers=headers, timeout=5)
            elapsed = (time.perf_counter() - t0) * 1000
            if r.status_code < 500:
                timings.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    if not timings:
        return {"path": path, "error": "all requests failed", "errors": errors}

    return {
        "path":       path,
        "mode":       "no_session",
        "n":          n,
        "errors":     errors,
        "mean_ms":    round(statistics.mean(timings), 1),
        "median_ms":  round(statistics.median(timings), 1),
        "min_ms":     round(min(timings), 1),
        "max_ms":     round(max(timings), 1),
        "stdev_ms":   round(statistics.stdev(timings), 1) if len(timings) > 1 else 0,
    }


def bench_endpoint_with_session(method: str, path: str, body: dict = None,
                                  n: int = N_ITERATIONS) -> dict:
    """Con requests.Session() — reutiliza TCP/HTTP keepalive."""
    url     = f"{BOT_URL}{path}"
    headers = make_headers()
    session = requests.Session()
    session.headers.update(headers)
    timings = []
    errors  = 0

    # Warmup: primer request establece conexion
    try:
        if method == "GET":
            session.get(url, timeout=5)
        else:
            session.post(url, json=body or {}, timeout=5)
    except Exception:
        pass  # ignorar el warmup si falla

    for _ in range(n):
        t0 = time.perf_counter()
        try:
            if method == "GET":
                r = session.get(url, timeout=5)
            else:
                r = session.post(url, json=body or {}, timeout=5)
            elapsed = (time.perf_counter() - t0) * 1000
            if r.status_code < 500:
                timings.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    session.close()

    if not timings:
        return {"path": path, "error": "all requests failed (session)", "errors": errors}

    return {
        "path":       path,
        "mode":       "with_session",
        "n":          n,
        "errors":     errors,
        "mean_ms":    round(statistics.mean(timings), 1),
        "median_ms":  round(statistics.median(timings), 1),
        "min_ms":     round(min(timings), 1),
        "max_ms":     round(max(timings), 1),
        "stdev_ms":   round(statistics.stdev(timings), 1) if len(timings) > 1 else 0,
    }


def check_bot_alive() -> bool:
    """Verifica que el bot este corriendo."""
    try:
        r = requests.get(f"{BOT_URL}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            print(f"  Bot online — guilds={data.get('guilds')} latency_discord={data.get('latency')}ms")
            return True
    except Exception as e:
        print(f"  Bot OFFLINE o error: {e}")
    return False


def main():
    print("=" * 65)
    print(f"BENCHMARK HTTP — {BOT_URL}")
    print(f"Token: {'configurado' if API_TOKEN else 'NO CONFIGURADO'}")
    print(f"Iteraciones: {N_ITERATIONS} por endpoint")
    print(f"Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)

    print("\n[CHECK] Verificando conectividad con el bot...")
    bot_alive = check_bot_alive()
    if not bot_alive:
        print("  ⚠️  Bot no disponible — los benchmarks no pueden correr")
        print(f"  Verifica que el bot este corriendo en {BOT_URL}")
        print("  (Los benchmarks de edge-tts y STT NO requieren el bot)")
        return

    all_results = []

    # Endpoints fast-path (los que deberian ser instantaneos)
    fast_path_endpoints = [
        ("GET",  "/health",  None),
        ("GET",  "/context", None),
        ("POST", "/skip",    {}),
        ("POST", "/stop",    {}),
        ("POST", "/pause",   {}),
        ("POST", "/resume",  {}),
        ("GET",  "/status",  None),
    ]

    print("\n[FAST-PATH ENDPOINTS — sin Session()]")
    for method, path, body in fast_path_endpoints:
        print(f"  {method} {path}...", end=" ", flush=True)
        r = bench_endpoint_no_session(method, path, body)
        all_results.append(r)
        if "error" not in r:
            print(f"mean={r['mean_ms']}ms  min={r['min_ms']}ms  max={r['max_ms']}ms  "
                  f"stdev={r['stdev_ms']}ms")
        else:
            print(f"ERROR: {r.get('error')}")

    print("\n[FAST-PATH ENDPOINTS — con Session() (keepalive)]")
    for method, path, body in fast_path_endpoints:
        print(f"  {method} {path}...", end=" ", flush=True)
        r = bench_endpoint_with_session(method, path, body)
        all_results.append(r)
        if "error" not in r:
            print(f"mean={r['mean_ms']}ms  min={r['min_ms']}ms  max={r['max_ms']}ms  "
                  f"stdev={r['stdev_ms']}ms")
        else:
            print(f"ERROR: {r.get('error')}")

    # /command: el endpoint universal de amigo.py
    cmd_bodies = [
        ("cmd_skip",     {"text": "siguiente"}),
        ("cmd_stop",     {"text": "para la musica"}),
        ("cmd_status",   {"text": "que esta sonando"}),
    ]

    print("\n[/command ENDPOINT — parse incluido]")
    for label, body in cmd_bodies:
        print(f"  {label}...", end=" ", flush=True)
        r = bench_endpoint_no_session("POST", "/command", body)
        r["label"] = label
        all_results.append(r)
        if "error" not in r:
            print(f"mean={r['mean_ms']}ms  min={r['min_ms']}ms  max={r['max_ms']}ms")
        else:
            print(f"ERROR: {r.get('error')}")

    # Resumen comparativo: no_session vs with_session
    print("\n" + "=" * 65)
    print("COMPARATIVA: sin Session vs con Session")
    print("=" * 65)

    no_sess  = [r for r in all_results if r.get("mode") == "no_session" and "mean_ms" in r]
    with_ses = [r for r in all_results if r.get("mode") == "with_session" and "mean_ms" in r]

    paired = {}
    for r in no_sess:
        paired[r["path"]] = {"no_session": r}
    for r in with_ses:
        if r["path"] in paired:
            paired[r["path"]]["with_session"] = r

    print(f"\n{'Endpoint':<15} {'NoSession':>10} {'WithSess':>10} {'Diff':>10} {'Vale?':>6}")
    print("-" * 65)
    savings = []
    for path, p in paired.items():
        ns = p.get("no_session", {}).get("mean_ms", 0)
        ws = p.get("with_session", {}).get("mean_ms", 0)
        if ns and ws:
            diff = ns - ws
            savings.append(diff)
            vale = "✅" if diff > 10 else ("~" if diff > 3 else "❌")
            print(f"  {path:<13} {ns:>9}ms {ws:>9}ms {diff:>+9}ms {vale:>6}")

    if savings:
        avg_saving = statistics.mean(savings)
        print(f"\n  Ahorro promedio con Session: {avg_saving:+.1f}ms por request")
        print(f"  {'✅ Vale la pena' if avg_saving > 15 else '⚠️  Beneficio marginal (<15ms)'}")

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "results_http.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "ts":      datetime.now().isoformat(),
            "bot_url": BOT_URL,
            "n":       N_ITERATIONS,
            "results": all_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out_path}")


if __name__ == "__main__":
    main()
