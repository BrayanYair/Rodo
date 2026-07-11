"""
train_byarox.py — Entrena un clasificador personalizado para el wake word "oye rodo".

Usa el embedding_model.onnx de openwakeword + LogisticRegression de sklearn.
NO requiere PyTorch.

Uso:
    python -m modules.wakeword.train_byarox
    (ejecutar desde rodolfo-amigo/)
"""

import asyncio
import os
import sys
import shutil
import subprocess
import pickle
import logging
import numpy as np

logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("train_byarox")

_HERE = os.path.dirname(os.path.abspath(__file__))
TMP_POS = os.path.join(_HERE, "tmp_positive")
TMP_NEG = os.path.join(_HERE, "tmp_negative")
OUTPUT_PKL = os.path.join(_HERE, "rodo_verifier.pkl")

VOICES = [
    ("es-PE-AlexNeural",   ["+0%", "+15%", "-10%"]),
    ("es-MX-DaliaNeural",  ["+0%", "+15%", "-10%"]),
    ("es-ES-AlvaroNeural", ["+0%", "+15%", "-10%"]),
    ("es-AR-TomasNeural",  ["+0%", "+15%", "-10%"]),
]
# Variantes fonéticas de "oye rodo" para mayor cobertura
TEXTS_POSITIVE = [
    "oye rodo", "oye rodo", "oye rodo",
    "hey rodo", "ey rodo",
    "oye rodo pon", "oye rodo para", "oye rodo siguiente",
    "oye rodo sigue", "oye rodo pausa", "oye rodo pon musica",
    "rodo pon", "rodo para",
]

TEXTS_NEGATIVE = [
    "oye todo", "oye lodo", "oye modo", "oye robo", "oye rolo",
    "todo", "lodo", "modo", "robo", "rolo",
    "pon todo", "no todo", "de todos modos", "me robo", "el lodo",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mp3_to_wav_16k(mp3_path: str, wav_path: str) -> bool:
    """Convierte mp3 a WAV 16kHz mono usando ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        for candidate in [
            r"C:\ffmpeg-8.1.1-essentials_build\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.EXE",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]:
            if os.path.exists(candidate):
                ffmpeg = candidate
                break
    if not ffmpeg:
        log.error("ffmpeg no encontrado. Instalá ffmpeg y agregalo al PATH.")
        return False
    result = subprocess.run(
        [ffmpeg, "-y", "-i", mp3_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", wav_path],
        capture_output=True,
    )
    return result.returncode == 0


async def _generate_positive_mp3(mp3_path: str, text: str, voice: str, rate: str):
    """Genera un mp3 con edge-tts."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(mp3_path)


def _generate_all_positives() -> list:
    """Genera WAVs positivos con edge_tts + ffmpeg. Retorna lista de paths."""
    os.makedirs(TMP_POS, exist_ok=True)
    tasks = []
    for voice, rates in VOICES:
        for rate in rates:
            for text in TEXTS_POSITIVE:
                tasks.append((voice, rate, text))

    # Mezclar para variedad
    import random
    random.shuffle(tasks)
    tasks = tasks[:40]  # máx 40 muestras

    wav_files = []
    log.info(f"Generando {len(tasks)} muestras positivas con edge_tts...")

    async def _run_all():
        mp3_files = []
        for i, (voice, rate, text) in enumerate(tasks):
            mp3_path = os.path.join(TMP_POS, f"pos_{i:03d}.mp3")
            try:
                await _generate_positive_mp3(mp3_path, text, voice, rate)
                mp3_files.append((i, mp3_path, voice, rate))
                log.info(f"  + pos_{i:03d}.mp3 [{voice}, rate={rate}]")
            except Exception as e:
                log.warning(f"  ! pos_{i:03d} falló: {e}")
        return mp3_files

    mp3_files = asyncio.run(_run_all())

    for i, mp3_path, voice, rate in mp3_files:
        wav_path = os.path.join(TMP_POS, f"pos_{i:03d}.wav")
        if _mp3_to_wav_16k(mp3_path, wav_path):
            wav_files.append(wav_path)
            os.remove(mp3_path)
        else:
            log.warning(f"  ! Conversión fallida para pos_{i:03d}.mp3")

    log.info(f"Positivos OK: {len(wav_files)}")
    return wav_files


async def _generate_negative_mp3(mp3_path: str, text: str, voice: str, rate: str):
    """Genera un mp3 negativo con edge_tts."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(mp3_path)


def _generate_negatives(n: int = 40) -> list:
    """Genera WAVs negativos: frases parecidas, silencio y ruido gaussiano."""
    os.makedirs(TMP_NEG, exist_ok=True)
    import wave, struct

    tasks = []
    for voice, rates in VOICES:
        for rate in rates:
            for text in TEXTS_NEGATIVE:
                tasks.append((voice, rate, text))

    import random
    random.shuffle(tasks)
    tasks = tasks[: min(len(tasks), n // 2)]

    wav_files = []
    log.info(f"Generando {len(tasks)} muestras negativas habladas con edge_tts...")

    async def _run_all():
        mp3_files = []
        for i, (voice, rate, text) in enumerate(tasks):
            mp3_path = os.path.join(TMP_NEG, f"neg_voice_{i:03d}.mp3")
            try:
                await _generate_negative_mp3(mp3_path, text, voice, rate)
                mp3_files.append((i, mp3_path))
                log.info(f"  - neg_voice_{i:03d}.mp3 [{voice}, rate={rate}, text={text}]")
            except Exception as e:
                log.warning(f"  ! neg_voice_{i:03d} falló: {e}")
        return mp3_files

    mp3_files = asyncio.run(_run_all())
    for i, mp3_path in mp3_files:
        wav_path = os.path.join(TMP_NEG, f"neg_voice_{i:03d}.wav")
        if _mp3_to_wav_16k(mp3_path, wav_path):
            wav_files.append(wav_path)
            os.remove(mp3_path)
        else:
            log.warning(f"  ! Conversión fallida para neg_voice_{i:03d}.mp3")

    SR = 16000
    DURATION = 1.5  # segundos
    N_SAMPLES = int(SR * DURATION)
    synthetic_count = max(10, n - len(wav_files))

    for i in range(synthetic_count):
        wav_path = os.path.join(TMP_NEG, f"neg_{i:03d}.wav")
        if i < synthetic_count // 2:
            # Silencio puro
            samples = np.zeros(N_SAMPLES, dtype=np.int16)
        else:
            # Ruido gaussiano de baja amplitud (ambiente)
            noise_amp = np.random.randint(100, 3000)
            samples = np.random.normal(0, noise_amp, N_SAMPLES).clip(-32768, 32767).astype(np.int16)

        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(samples.tobytes())
        wav_files.append(wav_path)

    log.info(f"Negativos generados: {len(wav_files)}")
    return wav_files


# ─── Extracción de embeddings ─────────────────────────────────────────────────

def _extract_embeddings_from_wav(wav_path: str, oww_model, min_rms: float = 0.0) -> np.ndarray:
    """
    Lee un WAV 16kHz mono y extrae embeddings usando el preprocessor de openwakeword.
    Retorna array de shape (N_windows, 1536) donde 1536 = 16 frames * 96 dims.
    """
    from scipy.io import wavfile
    try:
        sr, data = wavfile.read(wav_path)
    except Exception as e:
        log.warning(f"    No se pudo leer {wav_path}: {e}")
        return np.empty((0, 1536), dtype=np.float32)

    if data.dtype != np.int16:
        data = (data * 32767).astype(np.int16) if data.dtype in [np.float32, np.float64] else data.astype(np.int16)

    if sr != 16000:
        log.warning(f"    {wav_path}: sample rate {sr} != 16000, saltando")
        return np.empty((0, 1536), dtype=np.float32)

    # Resetear el preprocessor para no contaminar embeddings entre archivos
    oww_model.preprocessor.reset()

    CHUNK = 1280  # 80ms a 16kHz
    features_list = []

    # Procesar en chunks, tomando snapshots del feature buffer tras cada chunk
    for i in range(0, len(data) - CHUNK, CHUNK):
        chunk = data[i : i + CHUNK]
        rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768.0) ** 2)))
        if rms < min_rms:
            continue
        oww_model.predict(chunk)
        # get_features(16) devuelve shape (1, 16, 96) — la ventana más reciente
        feats = oww_model.preprocessor.get_features(16)  # (1, 16, 96)
        if feats.shape[1] == 16:
            features_list.append(feats.reshape(1, -1))  # (1, 1536)

    if not features_list:
        return np.empty((0, 1536), dtype=np.float32)

    return np.vstack(features_list).astype(np.float32)


def _build_dataset(pos_wavs: list, neg_wavs: list):
    """Extrae embeddings de todos los WAVs y construye X, y."""
    import warnings
    warnings.filterwarnings("ignore")

    from openwakeword.model import Model
    log.info("Cargando openwakeword para extracción de embeddings...")
    oww = Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")

    X_list, y_list = [], []

    log.info("Extrayendo embeddings de positivos...")
    for wav in pos_wavs:
        emb = _extract_embeddings_from_wav(wav, oww, min_rms=0.01)
        if emb.shape[0] > 0:
            X_list.append(emb)
            y_list.extend([1] * emb.shape[0])

    log.info("Extrayendo embeddings de negativos...")
    for wav in neg_wavs:
        emb = _extract_embeddings_from_wav(wav, oww)
        if emb.shape[0] > 0:
            X_list.append(emb)
            y_list.extend([0] * emb.shape[0])

    if not X_list:
        raise RuntimeError("No se extrajeron embeddings. Verificá los WAVs.")

    X = np.vstack(X_list)
    y = np.array(y_list)
    log.info(f"Dataset: {X.shape[0]} muestras — {y.sum()} pos / {(y==0).sum()} neg")
    return X, y


# ─── Entrenamiento ────────────────────────────────────────────────────────────

def _train_classifier(X: np.ndarray, y: np.ndarray) -> object:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    clf = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=1.0, max_iter=500, class_weight="balanced"),
    )
    clf.fit(X, y)

    # Eval rápida en train (no es hold-out pero da un número)
    acc = clf.score(X, y)
    pos_prob = clf.predict_proba(X[y == 1])[:, 1].mean()
    neg_prob = clf.predict_proba(X[y == 0])[:, 1].mean()
    log.info(f"Train acc: {acc:.2%}  |  P(rodo|pos)={pos_prob:.3f}  P(rodo|neg)={neg_prob:.3f}")
    return clf


# ─── Main ─────────────────────────────────────────────────────────────────────

def train():
    log.info("=" * 60)
    log.info("Entrenamiento del clasificador 'oye rodo'")
    log.info("=" * 60)

    # 1. Generar positivos
    log.info("\n[1/4] Generando muestras positivas...")
    pos_wavs = _generate_all_positives()
    if len(pos_wavs) < 5:
        log.error(f"Muy pocas muestras positivas ({len(pos_wavs)}). Abortando.")
        return False

    # 2. Generar negativos
    log.info("\n[2/4] Generando muestras negativas...")
    neg_wavs = _generate_negatives(40)

    # 3. Extraer embeddings y entrenar
    log.info("\n[3/4] Extrayendo embeddings y entrenando...")
    X, y = _build_dataset(pos_wavs, neg_wavs)
    clf = _train_classifier(X, y)

    # Guardar
    with open(OUTPUT_PKL, "wb") as f:
        pickle.dump(clf, f)
    log.info(f"\nClasificador guardado en: {OUTPUT_PKL}")

    # 4. Limpiar temporales
    log.info("\n[4/4] Limpiando temporales...")
    for d in [TMP_POS, TMP_NEG]:
        if os.path.exists(d):
            shutil.rmtree(d)
            log.info(f"Limpiado: {d}")

    log.info("\n✓ Entrenamiento completado. WakeWordEngine usará rodo_verifier.pkl.")
    return True


if __name__ == "__main__":
    ok = train()
    sys.exit(0 if ok else 1)
