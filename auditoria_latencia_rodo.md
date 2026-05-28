# 🔍 Auditoría Técnica de Latencia y Arquitectura de Voz — Rodo

> Basada en análisis del código fuente y 1,511 eventos reales del `performance_log.jsonl`

---

## 1. ¿Qué hace actualmente Rodo?

Rodo es un asistente de voz orientado exclusivamente a **control de música en Discord y del sistema de audio de Windows**. No utiliza LLM ni IA conversacional. Funciona como un **command dispatcher de voz**: escucha, transcribe, parsea con regex, y envía órdenes a una API HTTP interna.

Existe en tres variantes con distintas capacidades:
- **`rodolfo-amigo`** (clientes): mic → Google STT → HTTP POST al bot
- **`rodolfo-host`** (dueño): mic → Google STT (+ Whisper fallback) → control local (volumen, nircmd) + HTTP al bot
- **`rodolfo-bot`** (servidor): recibe comandos, controla Discord, reproduce música vía yt-dlp + FFmpeg, habla con edge-tts

---

## 2. Flujo Completo del Pipeline de Voz

### Camino completo de un comando tipo "Rodo pon despacito":

```
[Micrófono físico]
        │
        ▼  ~0ms — audio continuo
[amigo.py: recognizer.listen()]
        │  ~500-700ms — espera fin de frase (pause_threshold=0.8s DEFAULT en amigo)
        ▼
[Google STT — HTTP API]
        │  ~750-2,000ms — latencia red + nube (ver logs reales)
        ▼
[Corrección STT (regex) + Detección de activador]
        │  ~0ms — procesamiento local inmediato
        ▼
[Lógica de contexto Discord (opcional)]
        │  ~100-300ms — GET /context al bot si discord_mode==None
        ▼
[HTTP POST /command al bot]
        │  ~50-200ms — red local o ngrok
        ▼
[Bot: command_parser.full_parse()]
        │  ~0ms — regex local
        ▼
[Bot: _spotify_refine()] (si hay Spotify configurado)
        │  ~300-800ms — llamada API Spotify (BLOQUEANTE)
        ▼
[Bot: yt_search() — yt-dlp]
        │  ~1,000-3,000ms — yt-dlp extracción (BLOQUEANTE, en executor)
        ▼
[TTS: edge_tts.Communicate().save()] 
        │  ~500-1,500ms — genera MP3 completo (BLOQUEANTE)
        ▼
[Discord: player.say() → reproduce el MP3 en el canal]
        │  Latencia de buffer de Discord ~100-300ms
        ▼
[🔊 Usuario escucha "Poniendo despacito"]

[En paralelo: player.connect() + _play_track()]
        │  ~200-500ms — conexión + inicio de FFmpeg stream
        ▼
[🎵 Música comienza a sonar]
```

**Tiempo total estimado TTFA (Time To First Audio): 3,500 – 8,000ms**

---

## 3. Lo que SÍ está optimizado

| Aspecto | Detalle |
|---|---|
| **Filtrado sin activador** | Regex eficiente O(1) — no envía nada al servidor si no hay "Rodo" |
| **Command parser local** | Cero latencia, regex sin dependencias de red |
| **Socket timeout en STT** | `socket.setdefaulttimeout(3.0)` evita bloqueos eternos |
| **Lazy playlist streaming** | Las playlists de Spotify resuelven solo 3 canciones al inicio, el resto en fondo |
| **Re-fetch de URL fresca** | Antes de reproducir, yt-dlp refresca la URL para evitar error 403/138 |
| **Debounce de acciones** | Skip/Stop/Pause bloqueados si se repiten en <2s |
| **Watchdog del listener** | Reinicia el micrófono si 5 minutos sin audio (host) |
| **Prefetch paralelo** | `asyncio.ensure_future(_maybe_prefetch())` adelanta canciones en background |
| **Performance logging** | `performance_log.jsonl` permite análisis post-hoc de latencia real |
| **VAD básico en amigo** | `adjust_for_ambient_noise` reduce falsos positivos |
| **Reanudar música post-TTS** | Guarda posición exacta (`absolute_position`) y reanuda donde paró |
| **Semáforos en búsquedas batch** | `asyncio.Semaphore(5)` para playlists evita throttling de YouTube |

---

## 4. Lo que NO está optimizado (problemas ordenados por impacto)

### 🔴 CRÍTICO

#### C1. TTS bloqueante: genera todo el audio antes de reproducir
```python
# player.py línea 240-241 — EL PROBLEMA MÁS GRAVE
communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
await communicate.save(tmp_path)   # ← Bloquea hasta tener TODO el MP3
```
**Impacto: +500 a +1,500ms de latencia innecesaria.**
Edge-TTS soporta streaming real vía `communicate.stream()`, pero no se usa. El usuario podría escuchar las primeras sílabas mientras se genera el resto.

#### C2. Google STT batch-mode: espera el fin de frase completo
En `amigo.py`, el flujo de escucha es:
```python
audio = recognizer.listen(source, timeout=10, phrase_time_limit=7)  # Bloquea
text = recognizer.recognize_google(audio, ...)  # Envía DESPUÉS de cortar
```
El sistema opera en modo **half-duplex puro**: espera silencio → corta → envía todo el audio → espera respuesta nube. Esto es arquitecturalmente diferente al streaming STT que usa Alexa/Google Assistant donde el audio se envía chunk a chunk y la respuesta llega antes de que el usuario termine.

**Impacto: +700ms a +1,200ms por `pause_threshold` (default 0.8s en amigo, 0.5s en host).**

#### C3. `adjust_for_ambient_noise` en cada iteración del loop (amigo)
```python
while True:
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.2)  # ← CADA VEZ
        audio = recognizer.listen(...)
```
Esto añade 200ms de overhead ANTES de cada captura. El host lo hace solo al inicio (correcto). Amigo lo repite en cada ciclo del loop.

**Impacto: +200ms garantizados por cada ciclo de escucha.**

#### C4. Contexto Discord: HTTP request bloqueante en el fast path
```python
if _is_music_command(text) and _session["discord_mode"] is None:
    ctx = _check_context()   # GET /context — bloquea el hilo principal
    if ctx.get("in_discord"):
        answer = _ask_discord_preference(recognizer, mic, location)  # +8 segundos TTS + escucha!
```
Cuando `discord_mode` es `None` (inicio de sesión), el primer comando de música dispara:
1. Una petición HTTP GET síncrona
2. Luego un TTS local bloqueante preguntando preferencia
3. Luego una ventana de escucha de 8 segundos

**Impacto: Primera interacción puede tardar 10+ segundos.**

#### C5. Spotify refine + yt-dlp secuencial, no paralelo
```python
refined = await _spotify_refine(query)     # ~500ms API Spotify
track   = await yt_search(refined, ...)    # ~1,500ms yt-dlp
```
Ambas llamadas son secuenciales. No se puede paralelizar el Spotify refine con la búsqueda directa en YouTube (como fallback simultáneo).

**Impacto: +500ms si hay Spotify configurado, que se suman a yt-dlp.**

#### C6. Voice receive roto por Discord DAVE (E2E encryption)
```python
# sink.py línea 4-7
# ⚠️  ESTADO (2026): Discord DAVE (E2E encryption) rompe voice receive en py-cord.
```
La funcionalidad de "escuchar voz directamente en el canal de Discord" está completamente inutilizada por un bug de infraestructura externo. Todos los usuarios de Discord necesitan usar mensajes de texto o notas de voz.

---

### 🟡 MEDIO

#### M1. Creación de sesión HTTP nueva en cada `_music_bot()` call
```python
# controller.py — rodolfo-host
def _music_bot(self, method, path, data=None):
    url = f"{self.MUSIC_BOT_URL}{path}"
    if method == "POST":
        r = requests.post(url, json=data or {}, headers=headers, timeout=30)
```
Cada llamada HTTP crea una **nueva conexión TCP** (sin `requests.Session()`). El TLS handshake adicional (si es HTTPS via ngrok) puede sumar 50-200ms por request.

#### M2. amigo.py: `_is_music_command()` doble normalización
```python
def _is_music_command(text: str) -> bool:
    norm = normalize(text)              # normaliza completo
    for name in ACTIVATOR_NAMES:
        norm = re.sub(rf"\b{name}\b", "", norm).strip()  # strips activator
    words = set(norm.split())
    return bool(words & _MUSIC_VERBS)
```
Esta función se llama, y luego `normalize()` se vuelve a llamar más adelante en el mismo ciclo. Computacionalmente irrelevante, pero indica código no consolidado.

#### M3. Background listener no está activo en amigo (solo en host)
El `rodolfo-host` usa `listen_in_background()` con una cola de audio, eliminando gaps entre capturas. `rodolfo-amigo` usa el modo síncrono `with mic as source: listen()`, que:
- Cierra y reabre el micrófono cada ciclo
- Añade 200ms de calibración
- No puede escuchar mientras procesa

#### M4. TTS local en amigo usa subprocess PowerShell (Windows SAPI)
```python
def _speak_local(text: str):
    subprocess.run(["powershell", "-NoProfile", ..., f"$s.Speak('{safe}')"], ...)
```
Cada TTS local crea un proceso nuevo de PowerShell. El startup de PowerShell puede tardar **300-800ms** antes de que empiece a hablar.

---

### 🟢 BAJO

#### B1. `send_command()` en amigo no reintenta ante fallo de red
Si el bot está momentáneamente down, el comando se pierde silenciosamente.

#### B2. Falta pre-warming de conexión Discord al arrancar
El bot conecta a Discord al primer play. Debería estar siempre en standby.

#### B3. Logs de performance (`_log_perf`) escriben a disco en el hilo principal
Operación I/O en el hot path. Mínimo impacto, pero debería ser async.

---

## 5. Estimación de Latencia por Etapa (TTFA actual vs ideal)

### Datos reales del log (rodolfo-host, 1,511 eventos):
```
STT (Google) — comandos con activador:
  Mediana:  ~1,200ms
  Rango:      400ms – 3,500ms
  Outliers: hasta 9,106ms (timeouts de red)

first_response_ms — tiempo entre STT y primer speak():
  Rango:      0ms – 14ms  ← EXCELENTE (el parser es instantáneo)
  Nota: este mide hasta el speak(), NO hasta que el audio llega al usuario
```

### Desglose TTFA completo (modo Discord, comando de música):

| Etapa | Tiempo actual | Tiempo ideal |
|---|---|---|
| Usuario habla | variable | variable |
| `pause_threshold` (espera silencio) | **800ms** (amigo) / 500ms (host) | 200ms (VAD moderno) |
| Calibración noise (amigo) | **200ms** | 0ms (solo al inicio) |
| Google STT (nube) | **900-1,500ms** | 200-400ms (streaming) |
| Detección activador + parse | ~1ms | ~1ms |
| GET /context (si discord_mode=None) | **100-300ms** (+ hasta 10s de dialogo!) | 0ms (precachear contexto) |
| HTTP POST /command al bot | **50-200ms** | 50ms (WebSocket persistente) |
| `_spotify_refine()` | **300-800ms** | 0-300ms (paralelo) |
| `yt_search()` via yt-dlp | **1,000-3,000ms** | 500-1,500ms (caché) |
| `edge_tts.save()` completo | **500-1,500ms** | 50-100ms (streaming) |
| Discord audio buffer | **100-300ms** | 100ms |
| **TTFA TOTAL** | **~4,000-8,000ms** | **~1,000-2,000ms** |

> **El TTFA ideal de Alexa/Google Assistant ronda los 300-800ms.**
> **Rodo está 4-10× más lento en el camino crítico.**

---

## 6. Operaciones que pueden ejecutarse en PARALELO

Actualmente todo es secuencial. Estas operaciones son independientes:

```
ACTUAL (secuencial):
STT → [detect context] → POST /command → spotify_refine → yt_search → edge_tts → reproduce

IDEAL (paralelo):
STT ──────────────────────────────────── → POST /command
                                                   │
                                          ┌────────┴──────────┐
                                          ▼                   ▼
                                    yt_search()          edge_tts("un momento")
                                          │                   │
                                          ▼                   ▼
                                    track_ready          reproducir feedback inmediato
                                          │
                                          ▼
                                    reproducir música
```

### Paralelizaciones de alto impacto:

1. **TTS de feedback + búsqueda de canción**: En cuanto parsea "play_music", disparar simultáneamente el TTS de "Un momento..." y el yt_search. Actualmente es secuencial.

2. **Spotify refine + yt_search directo en paralelo**:
   ```python
   # Lanzar ambas búsquedas simultáneamente, usar la primera que sea buena
   spotify_task = asyncio.create_task(_spotify_refine(query))
   yt_task      = asyncio.create_task(yt_search(query))  # búsqueda directa como fallback
   ```

3. **HTTP context check en background**: El `GET /context` podría correrse cada 5s en background y cachearse localmente en lugar de ser síncrono en el hot path de cada comando de música.

4. **Conexión al canal de voz**: `player.connect()` podría iniciarse al detectar el activador, antes de terminar la transcripción.

---

## 7. Fast Path vs Slow Path

Rodo no diferencia formalmente fast path de slow path. Sin embargo, implícitamente:

### Fast Path (actual, funciona bien):
- `stop_music`, `skip_music`, `pause_music`, `resume_music`
- El parser regex lo detecta en 0ms
- La respuesta HTTP al bot es ~100ms
- **No necesita TTS de confirmación vocal** (chime bastaría)
- **¿Por qué genera TTS?** Innecesario para estos comandos. Un beep corto ahorraría 500ms+

### Slow Path (actual, problemático):
- `play_music`: debe resolver la canción → Spotify + YouTube (1,500-3,500ms bloqueantes)
- Sin feedback durante la búsqueda → el usuario no sabe si fue escuchado
- La primera respuesta audible llega cuando YA encontró y está anunciando la canción

### Lo que debería existir:

| Path | Comandos | Latencia target | Feedback |
|---|---|---|---|
| **Fast Path 0** | stop, skip, pause, resume | <100ms | Chime inmediato |
| **Fast Path 1** | status, volume, overlay | <500ms | TTS corto vía streaming |
| **Slow Path** | play (búsqueda) | <2,000ms | TTS "buscando..." mientras busca |
| **Async Path** | move bot, disconnect | <300ms | Sin audio necesario |

---

## 8. UX Auditiva

### ✅ Lo que funciona bien:
- El **overlay visual** (estados: listening, processing, sending, ok, error) da feedback no-auditivo inmediato
- **Chimes opcionales** en rodolfo-host para success/error/listening
- El sistema **descarta ruido** sin alertar al usuario (correcto)
- El modo "ventana de activador" (6s) permite comandos de dos frases sin repetir "Rodo"

### ❌ Problemas de UX auditiva:

| Problema | Impacto |
|---|---|
| **Silencio total entre "Rodo pon X" y "Poniendo X"** (3-8 segundos) | Usuario no sabe si fue escuchado. Repite el comando. Loop de confusión. |
| **Sin feedback de "te escuché"** inmediato | El overlay cambia a `processing` pero el usuario puede no estar mirando la pantalla |
| **Primera interacción pregunta por Discord** con TTS bloqueante antes de hacer nada | Experiencia confusa la primera vez |
| **TTS de host usa PowerShell SAPI** con 300-800ms de startup | La voz llega tarde, se siente desconectada de la acción |
| **amigo.py pide canción si no viene en el comando** (`play_music` sin query) | Añade +10 segundos de latencia de forma innecesaria |
| **No hay sonido de confirmación de escucha** al detectar "Rodo" solo | Si el usuario dice solo "Rodo", no hay ningún feedback auditivo |

---

## 9. Manejo de Interrupciones (Barge-in)

### Estado actual:

**rodolfo-host**: ✅ Tiene implementación de barge-in
```python
# controller.py
def _check_for_interruptions(self):
    rec = sr.Recognizer()
    while self.is_speaking and not self.interrupt_speech:
        with sr.Microphone() as source:
            audio = rec.listen(source, timeout=0.3, phrase_time_limit=1.5)
        cmd = rec.recognize_google(audio, ...)
        self._handle_interruption_text(cmd)
```
Funciona con palabras como "para", "stop", "espera". Detecta interrupciones mientras el TTS local está reproduciendo.

**rodolfo-amigo**: ❌ Sin barge-in implementado
- El TTS es Windows SAPI y bloquea en un subprocess
- No hay forma de interrumpir la respuesta vocal del asistente
- Si el bot está hablando en Discord, el usuario no puede cancelarlo

### Problemas del barge-in actual (host):
1. Abre un nuevo `sr.Microphone()` cada 50ms → potencial conflicto con el listener principal
2. Depende de Google STT para detectar palabras simples → latencia innecesaria para detectar "para" (debería ser VAD local)
3. No hay detección por amplitud (palabra de stop con volumen alto) como hacen Alexa/Echo

### Diagnóstico half-duplex vs full-duplex:
- **Rodo es half-duplex**: no puede escuchar mientras habla de forma confiable
- Un sistema moderno (ChatGPT Voice, Alexa) es **full-duplex**: escucha siempre, puede ser interrumpido en cualquier momento

---

## 10. Arquitectura de Red

### Configuración actual:

```
amigo.py → ngrok (HTTP) → rodolfo-bot (aiohttp)
host.py  → HTTP directo → rodolfo-bot (aiohttp)
```

### Problemas detectados:

| Problema | Detalle | Impacto |
|---|---|---|
| **HTTP polling para contexto Discord** | `GET /context` cada 5s desde el monitor de voz | 5s de delay máximo para detectar que el usuario salió del canal |
| **Sin WebSocket persistente** | Cada comando abre una nueva conexión TCP HTTP | +50-150ms de overhead por request (TCP handshake) |
| **requests sin Session()** | `controller.py` hace `requests.post()` sin reusar conexiones | +50-200ms en modo HTTPS |
| **Timeout de socket en amigo: 3s** | Si STT tarda >3s, falla silenciosamente | Pérdida de comandos en red lenta |
| **ngrok introduce overhead variable** | La latencia de ngrok puede variar 50-500ms según carga | Experiencia inconsistente |
| **No hay retry automático** | Si `send_command` falla, el comando se pierde | Mala resiliencia |

### Red ideal:
- WebSocket persistente para comandos del cliente → bot (elimina overhead de conexión)
- SSE (Server-Sent Events) o WebSocket para push de estado desde bot → cliente (elimina polling)
- Connection pooling con `httpx.AsyncClient` o `aiohttp.ClientSession` reutilizable

---

## 11. Análisis STT Detallado

### Motor actual: Google Speech Recognition (Cloud)

| Característica | Estado en Rodo |
|---|---|
| **Modo** | Batch (envía audio completo después del silencio) |
| **Streaming** | ❌ No implementado |
| **VAD** | `pause_threshold` basado en duración de silencio (no energía) |
| **Latencia promedio** | 900-1,500ms (según logs reales) |
| **Precisión en español** | Alta (~95% comandos simples) |
| **Costo** | Gratuito (SpeechRecognition usa endpoint sin API key) |
| **Fallback** | Whisper local (en host, desactivado por defecto — correctamente) |

### Problemas del VAD actual:

**amigo.py** usa `pause_threshold` default de `speech_recognition` (0.8s):
```python
recognizer = sr.Recognizer()
# NO se configura pause_threshold → usa default 0.8s
```

**controller.py (host)** sí lo reduce:
```python
self.recognizer.pause_threshold = 0.5
self.recognizer.non_speaking_duration = 0.4
```

La diferencia: **amigo espera 300ms más de silencio antes de cortar** que el host.

### STT ideal para un asistente de voz:
- **Google Streaming STT** (v1beta1 o v2): empieza a transcribir en tiempo real, latencia <200ms hasta primera palabra
- **Deepgram Nova-2 Español**: latencia ~100ms, excelente precisión, streaming nativo
- **WhisperLive o faster-whisper**: local, ~150ms por utterance con VAD silero integrado
- **VAD con Silero**: detecta fin de frase en ~50ms sin depender de duración de silencio

---

## 12. Uso del LLM / IA

### Diagnóstico: **Rodo NO usa LLM.**

El "procesamiento de intención" es 100% basado en regex y listas de keywords:

```python
# command_parser.py — toda la "IA" de Rodo
if re.search(r"\b(stop|deten|...)...", cmd):
    return {"action": "stop_music"}
for verb in play_verbs:
    if cmd.startswith(verb + " "):
        return {"action": "play_music", "query": ...}
```

### Implicaciones:

**Positivo:**
- Latencia de parsing: ~0ms (no hay red, no hay modelo)
- Sin costos de API
- Determinístico y predecible

**Negativo:**
- No entiende variaciones naturales del lenguaje:
  - "échamelo" ✅ / "dale con algo de trap" ❌ (falla si no hay verbo conocido)
  - "pásamela" ✅ / "quiero escuchar algo del Flaco" ❌
- No tiene contexto de conversación
- No puede responder preguntas ("¿qué artistas tiene la cola?")
- La lista de reglas crece indefinidamente y se vuelve difícil de mantener

### ¿Debería usar LLM?

Para el caso de uso actual (comandos de música), el LLM no es necesario. Sin embargo, si el objetivo es "experiencia tipo Jarvis", un pequeño LLM local (Phi-3 mini, Gemma 2B, o llamadas a GPT-4o mini) como clasificador de intención sería transformador:

```
Input: "quiero escuchar algo de Bad Bunny pero relajante"
Output: {"action": "play_music", "query": "Bad Bunny relajante"}

Input: "sácalo del canal, estamos durmiendo"  
Output: {"action": "disconnect_music"}
```

---

## 12. Diagnóstico Final

### A. Problemas Críticos (por impacto en experiencia)

| # | Problema | Impacto en TTFA |
|---|---|---|
| 🔴 1 | **Silencio largo (3-8s) entre comando y respuesta** | El problema más visible para el usuario |
| 🔴 2 | **TTS edge_tts genera MP3 completo antes de reproducir** | +500-1,500ms recuperables |
| 🔴 3 | **Google STT batch: espera silencio completo** | +800ms de pause_threshold |
| 🔴 4 | **adjust_for_ambient_noise en cada ciclo en amigo** | +200ms garantizados por iteración |
| 🔴 5 | **Spotify refine + yt_search secuenciales** | +300-800ms recuperables |
| 🔴 6 | **Sin feedback de "te escuché" hasta tener el resultado** | UX percibida como rota |
| 🔴 7 | **Voice receive roto por Discord DAVE** | Feature completamente inactiva |

---

### B. Mejoras Recomendadas

#### PRIORIDAD ALTA

**A1. TTS Streaming en edge-tts** (Mayor ROI)
```python
# ACTUAL (bloqueante):
await communicate.save(tmp_path)

# IDEAL (streaming):
async def _speak_streaming(text, voice_client):
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            # Enviar chunk de audio directamente al voice_client
            # sin esperar el MP3 completo
```
**Ahorro estimado: 300-1,000ms**

**A2. Feedback inmediato antes de buscar**
```python
# En http_command(), al detectar play_music:
asyncio.ensure_future(player.say("Buscando..."))  # Fire-and-forget
# LUEGO hacer la búsqueda
tracks = await resolve_query(query)
```
**Impacto en percepción: elimina el silencio incómodo completamente**

**A3. Quitar calibración por ciclo en amigo**
```python
# ANTES de while True:
with mic as source:
    recognizer.adjust_for_ambient_noise(source, duration=1.5)  # Solo una vez

# Dentro del while True: eliminar esta línea:
# recognizer.adjust_for_ambient_noise(source, duration=0.2)  ← ELIMINAR

# Usar background listener como lo hace host:
audio_queue = queue.Queue()
stop = recognizer.listen_in_background(mic, lambda r, a: audio_queue.put(a))
```
**Ahorro: 200ms por cada ciclo de escucha**

**A4. Reducir pause_threshold en amigo**
```python
recognizer = sr.Recognizer()
recognizer.pause_threshold = 0.5           # default 0.8 → -300ms
recognizer.non_speaking_duration = 0.4    # default 0.8 → -400ms
```
**Ahorro: 300-400ms de tiempo de corte**

**A5. requests.Session() reutilizable**
```python
# En rodolfo-host/controller.py:
self._session = requests.Session()
self._session.headers.update(self._auth_headers())

def _music_bot(self, method, path, data=None):
    url = f"{self.MUSIC_BOT_URL}{path}"
    r = self._session.post(url, json=data or {}, timeout=30)
```
**Ahorro: 50-200ms por request en modo HTTPS**

---

#### PRIORIDAD MEDIA

**M1. Búsqueda paralela: Spotify refine + yt_search directo**
```python
spotify_task = asyncio.create_task(_spotify_refine(query))
yt_direct    = asyncio.create_task(yt_search(query))   # fallback simultáneo
refined = await spotify_task
if refined:
    track = await yt_search(refined, fast=True)
else:
    track = await yt_direct
```

**M2. Contexto Discord pre-cacheado**
En vez de hacer GET /context en el hot path, el voice monitor ya lo corre cada 5s. Usar ese resultado cacheado en `_session["discord_context"]`.

**M3. Separar comandos fast-path de slow-path**
```python
INSTANT_ACTIONS = {"stop_music", "skip_music", "pause_music", "resume_music"}
if action in INSTANT_ACTIONS:
    # Ejecutar + chime, SIN TTS, SIN esperar
    execute_instant(action)
    play_chime("success")   # <10ms
    return
```

**M4. Migrar TTS local en amigo a pyttsx3 o win32com.client**
```python
# ACTUAL: subprocess.run(["powershell", ...]) → 300-800ms startup
# IDEAL:
import pyttsx3
engine = pyttsx3.init()    # Una sola vez al inicio
engine.say(text)           # ~30ms
engine.runAndWait()
```

---

#### PRIORIDAD BAJA

**B1. Implementar retries con backoff en send_command**

**B2. Persistir `httpx.AsyncClient` en el bot para las llamadas de yt-dlp**

**B3. Caché de tracks recientemente reproducidos** (LRU de 50 items, para canciones repetidas el yt_search sea 0ms)

**B4. Mover `_log_perf()` a un thread daemon** para no bloquear el loop principal

---

### C. Quick Wins (cambios pequeños, impacto grande)

| # | Cambio | Archivos | Tiempo | Ganancia |
|---|---|---|---|---|
| QW1 | Sacar `adjust_for_ambient_noise` del loop en `amigo.py` | `amigo.py` línea 682 | 5 min | -200ms/ciclo |
| QW2 | `recognizer.pause_threshold = 0.5` en `amigo.py` | `amigo.py` línea 625 | 2 min | -300ms |
| QW3 | `asyncio.ensure_future(player.say("Un momento"))` antes de buscar | `api.py` línea 300-320 | 10 min | Elimina silencio percibido |
| QW4 | `requests.Session()` en `controller.py` | `controller.py` `__init__` | 5 min | -100ms/request |
| QW5 | Quitar TTS en acciones fast-path (skip/stop/pause) | `cog.py` y `controller.py` | 15 min | -500ms en comandos frecuentes |
| QW6 | `recognizer.dynamic_energy_threshold = False` + threshold fijo | `amigo.py` | 5 min | Consistencia del VAD |

---

### D. Arquitectura Ideal Recomendada

```
┌─────────────────────────────────────────────────────────┐
│                  CLIENTE RODO.EXE (amigo)               │
│                                                         │
│  [Silero VAD] ──► [Audio chunks 200ms]                  │
│       │                   │                             │
│       ▼                   ▼                             │
│  Detecta fin         [WebSocket Stream]                 │
│  de utterance         → Deepgram/Whisper                │
│       │               streaming STT                     │
│       │                   │                             │
│       ▼                   ▼                             │
│  [Activator       [Texto en tiempo real]                │
│   keyword check]          │                             │
│                    [Intent Classification]              │
│                     (regex fast-path)                   │
│                           │                             │
│              ┌────────────┴──────────────┐              │
│              ▼                           ▼              │
│       Fast Path (<100ms)          Slow Path (<2s)       │
│    stop/skip/pause/resume         play music            │
│     → WS message + chime         → WS + feedback TTS   │
│                                         │               │
└─────────────────────────────────────────┼───────────────┘
                                          │ WebSocket persistente
                                          ▼
┌─────────────────────────────────────────────────────────┐
│               RODOLFO-BOT (servidor)                    │
│                                                         │
│  [WS Handler] → [Parser] → [Action Router]             │
│                                 │                       │
│       ┌─────────────────────────┼────────────┐         │
│       ▼                         ▼            ▼         │
│  [Discord API]           [Music Search]  [TTS Engine]  │
│  stop/skip/pause      Spotify→YT paralelo  edge-tts    │
│                             │              streaming   │
│                             ▼                  │       │
│                      [Track Cache]              │       │
│                      (LRU 50 items)             │       │
│                             │                  ▼       │
│                             └──► [FFmpeg → Discord VC] │
└─────────────────────────────────────────────────────────┘

Reducción TTFA estimada: 4,000-8,000ms → 800-1,500ms
```

---

## Conclusión

| Dimensión | Estado Actual | Estado Ideal |
|---|---|---|
| **TTFA** | 4,000-8,000ms | 800-1,500ms |
| **STT** | Batch, espera silencio completo | Streaming, corte por VAD energético |
| **TTS** | Genera MP3 completo antes de reproducir | Streaming chunk-by-chunk |
| **Feedback usuario** | Silencio 3-8s | "Un momento..." en <500ms |
| **Paralelismo** | 0% — todo secuencial | 60%+ paralelizable |
| **Interrupciones** | Solo en host, con Google STT | VAD local, full-duplex |
| **Red** | HTTP sin pool, polling cada 5s | WebSocket persistente |
| **Intención** | Regex determinístico | Regex fast-path + LLM fallback |
| **Experiencia** | "Funciona" | "Se siente vivo" |

> **Rodo tiene una arquitectura sólida como base, pero opera en modo secuencial-bloqueante en todos sus puntos críticos.** Los quick wins pueden recortar 40-50% de la latencia percibida en 1-2 horas de trabajo. La arquitectura ideal llevaría la experiencia a nivel de asistente comercial.
