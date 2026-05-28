from .query_normalizer import normalize_query
from .cache_manager import (
    # Lookups
    get_best_cached_query,
    get_cached_query,         # alias retrocompatible
    get_track,
    get_hot_tracks,
    # Escrituras
    save_query,
    save_track,
    refresh_stream_url,
    mark_stream_invalid,
    # Confidence
    compute_confidence,
    should_trust_cache,
    SOURCE_SCORES,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    # Helpers
    extract_track_key,
    # Métricas
    log_stat,
    record_hit,
    get_hit_ratio_report,
    get_stats_summary,
    # Mantenimiento
    cleanup_expired,
    maybe_pre_refresh_hot_tracks,
    # Concurrencia
    _get_track_lock,
)
