import sys
import os
import asyncio
import time

# Añadir rodolfo-bot al PATH para poder importar los módulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rodolfo-bot")))

from modules.music.cache import (
    normalize_query,
    get_cached_query,
    save_query,
    get_track,
    save_track,
    refresh_stream_url,
    extract_track_key,
    log_stat,
    cleanup_expired
)
from modules.music.cache.database import get_connection

async def run_tests():
    print("=== INICIANDO PRUEBAS DE CACHÉ MUSICAL ===")
    
    # 1. Normalización de consultas
    queries_to_test = [
        ("Rodo pon Flaca porfa", "flaca"),
        ("ponme DESPACITO a la cola", "despacito"),
        ("poner carlos vives la bicicleta", "carlos vives la bicicleta"),
        ("  ALGO de Calamaro   ", "algo de calamaro")
    ]
    
    for raw, expected in queries_to_test:
        normalized = normalize_query(raw)
        print(f"Normalizar: '{raw}' -> '{normalized}' (Esperado: '{expected}')")
        assert normalized == expected, f"Fallo: {normalized} != {expected}"
    print("✔ Normalizador de consultas funciona correctamente.")
    
    # Limpiar cualquier residuo de test anterior
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_queries WHERE user_key IN ('test_user_a', 'test_user_b')")
    c.execute("DELETE FROM tracks WHERE track_key LIKE 'test_track%'")
    conn.commit()
    conn.close()
    
    # 2. Guardar un track inicial
    track_key = "test_track_1"
    save_track(
        track_key=track_key,
        title="Flaca Test",
        artist="Andres Calamaro",
        duration=220,
        webpage_url="https://youtube.com/watch?v=test1234567",
        stream_url="https://youtube-streaming-url.com/stream1",
        stream_expires_at=int(time.time() + 3600), # Expira en 1 hora (Válida)
    )
    
    # 3. Guardar query de usuario
    user_a = "test_user_a"
    user_b = "test_user_b"
    query_text = "flaca"
    
    save_query(user_a, query_text, track_key)
    print(f"✔ Query '{query_text}' asociada a '{track_key}' para '{user_a}'")
    
    # 4. Verificar L1 Hit (URL válida)
    t0 = time.time()
    cached_a = get_cached_query(user_a, query_text)
    latency_ms = int((time.time() - t0) * 1000)
    
    assert cached_a is not None, "Debería retornar un track"
    assert cached_a["stream_url"] == "https://youtube-streaming-url.com/stream1", "Debería tener el stream_url válido"
    print(f"✔ L1 Hit detectado en {latency_ms}ms para '{user_a}'. Stream URL: {cached_a['stream_url']}")
    
    # 5. Verificar comportamiento multiusuario (test_user_b no debería tener flaca asociada)
    cached_b = get_cached_query(user_b, query_text)
    assert cached_b is None, f"'{user_b}' no debería tener preferencias de '{user_a}'"
    print(f"✔ Aislamiento multiusuario verificado. '{user_b}' tiene Cache Miss.")
    
    # 6. Guardar preferencia distinta para el usuario B para la misma query
    track_key_b = "test_track_2"
    save_track(
        track_key=track_key_b,
        title="Flaca (En vivo) Test",
        artist="Andres Calamaro",
        duration=230,
        webpage_url="https://youtube.com/watch?v=test7654321",
        stream_url="https://youtube-streaming-url.com/stream2",
        stream_expires_at=int(time.time() + 3600),
    )
    save_query(user_b, query_text, track_key_b)
    
    cached_b_new = get_cached_query(user_b, query_text)
    assert cached_b_new is not None
    assert cached_b_new["track_key"] == track_key_b
    print(f"✔ Preferencias separadas verificadas: '{user_a}' -> '{cached_a['title']}', '{user_b}' -> '{cached_b_new['title']}'")
    
    # 7. Simular L2 Hit / URL Expirada
    # Actualizar la base de datos para que la URL expire en el pasado
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tracks SET stream_expires_at = ? WHERE track_key = ?", (int(time.time() - 100), track_key))
    conn.commit()
    conn.close()
    
    # lookup en base de datos para verificar que está expirada
    cached_a_exp = get_cached_query(user_a, query_text)
    assert cached_a_exp is not None
    now = int(time.time())
    is_expired = cached_a_exp["stream_expires_at"] < now
    assert is_expired, "Debería estar expirada en la base de datos"
    print(f"✔ L2 Expiración simulada correctamente. stream_expires_at={cached_a_exp['stream_expires_at']} vs now={now}")
    
    # 8. Limpieza de datos (Mantenimiento)
    cleanup_expired()
    # Verificar que el stream_url quedó en NULL pero el track y la query siguen existiendo
    track_cleaned = get_track(track_key)
    assert track_cleaned["stream_url"] is None, "El stream_url debería haber sido limpiado por cleanup_expired"
    assert track_cleaned["webpage_url"] is not None, "La webpage_url debe permanecer intacta para refrescos L2"
    print("✔ Cleanup de streams expirados verificado correctamente.")
    
    # 9. Limpieza de tablas de prueba
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_queries WHERE user_key IN ('test_user_a', 'test_user_b')")
    c.execute("DELETE FROM tracks WHERE track_key LIKE 'test_track%'")
    conn.commit()
    conn.close()
    print("=== TODAS LAS PRUEBAS PASARON EXITOSAMENTE ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
