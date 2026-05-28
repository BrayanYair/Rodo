import sqlite3
import time
from pathlib import Path

DB_DIR = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = DB_DIR / "music_cache.db"


def get_connection() -> sqlite3.Connection:
    """
    Retorna una conexión SQLite con WAL mode y check_same_thread=False.

    WAL (Write-Ahead Logging) es CRÍTICO en entornos asyncio/Discord/threads
    porque elimina el error "database is locked" al tener múltiples readers
    concurrentes con un writer.

    check_same_thread=False es necesario porque asyncio puede ejecutar
    callbacks en distintos threads del executor pool de Python.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,   # Seguro con WAL y GIL de Python
        timeout=10.0,              # Esperar hasta 10s antes de lanzar OperationalError
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-4000;")   # ~16MB en RAM
    return conn


def init_db():
    """Inicializa la base de datos y crea las tablas e índices requeridos si no existen."""
    conn = get_connection()
    cursor = conn.cursor()

    # ── Tabla 1: tracks (global, compartida entre usuarios) ────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        track_key TEXT UNIQUE NOT NULL,
        title TEXT,
        artist TEXT,
        duration INTEGER,
        webpage_url TEXT NOT NULL,
        stream_url TEXT,
        thumbnail TEXT,
        source TEXT DEFAULT 'youtube',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_stream_refresh INTEGER,
        stream_expires_at INTEGER,
        play_count INTEGER DEFAULT 0,
        -- stream_invalid=1 indica que la URL fue invalidada por fallo de playback
        -- fuerza L3 re-extracción aunque el TTL no haya expirado.
        stream_invalid INTEGER DEFAULT 0
    );
    """)

    # ── Tabla 2: user_queries — ESQUEMA 1:N con confidence multidimensional ───
    #
    # DECISIÓN DE DISEÑO: Un usuario puede tener MÚLTIPLES candidatos para
    # la misma query. Ej: "flaca" puede apuntar a:
    #   - youtube:abc (Calamaro, score=0.85, usage=15) ← ganador actual
    #   - youtube:xyz (cover genérico, score=0.42, usage=1) ← perdedor
    #
    # Se elimina UNIQUE(user_key, normalized_query) y se usa un índice compuesto
    # no-único. La lógica de selección elige el candidato con mayor final_confidence.
    #
    # Columnas de confidence:
    #   source_score   : 0.60–1.00 según fuente (Spotify URL > Spotify refine > YT texto)
    #   usage_count    : cuántas veces el usuario pidió esta query → este track
    #   confidence     : final_confidence calculado y cacheado al guardar
    #                    (se recalcula en get_best_cached_query)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_key TEXT NOT NULL,
        normalized_query TEXT NOT NULL,
        track_key TEXT NOT NULL,
        source_score REAL DEFAULT 0.70,
        usage_count INTEGER DEFAULT 1,
        confidence REAL DEFAULT 0.70,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );
    """)

    # ── Tabla 3: cache_stats ───────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cache_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT,
        query TEXT,
        cache_level TEXT,
        latency_ms INTEGER,
        created_at INTEGER NOT NULL
    );
    """)

    # ── Índices ────────────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_user_query
    ON user_queries(user_key, normalized_query);
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_track_key
    ON tracks(track_key);
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_stream_expire
    ON tracks(stream_expires_at);
    """)

    # Índice para hot tracks: queries muy usadas por cualquier usuario
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_usage_count
    ON user_queries(usage_count DESC);
    """)

    # Índice para buscar el mejor candidato por (user, query) ordenado por confidence DESC
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_user_query_confidence
    ON user_queries(user_key, normalized_query, confidence DESC);
    """)

    # ── Migraciones para DBs existentes ───────────────────────────────────────
    _run_migrations(cursor)

    conn.commit()
    conn.close()


def _run_migrations(cursor):
    """
    Aplica migraciones de esquema de forma idempotente.
    Cada ALTER TABLE falla silenciosamente si la columna ya existe.
    """
    migrations = [
        # Fase 6: invalidación por fallo de playback
        "ALTER TABLE tracks ADD COLUMN stream_invalid INTEGER DEFAULT 0;",
        # Fase 7: confidence multidimensional
        "ALTER TABLE user_queries ADD COLUMN source_score REAL DEFAULT 0.70;",
        "ALTER TABLE user_queries ADD COLUMN confidence REAL DEFAULT 0.70;",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except Exception:
            pass  # Columna ya existe → ignorar


# ── Migración de unicidad: user_queries pasó de 1:1 a 1:N ────────────────────
def _migrate_unique_constraint(conn):
    """
    SQLite no soporta DROP CONSTRAINT directamente.
    Si existe el índice único antiguo (idx_user_query_unique), lo elimina.
    Esto permite que la misma (user_key, normalized_query) tenga múltiples track_keys.
    """
    cursor = conn.cursor()
    try:
        # Detectar si el índice único viejo existe
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_user_query_unique'
        """)
        if cursor.fetchone():
            cursor.execute("DROP INDEX idx_user_query_unique;")
            conn.commit()
            print("[CACHE DB] Migración: eliminado índice único de user_queries → ahora 1:N")
    except Exception as e:
        print(f"[CACHE DB] Nota migración 1:N: {e}")


# Inicializar al importar
_conn_temp = get_connection()
_migrate_unique_constraint(_conn_temp)
_conn_temp.close()
init_db()
