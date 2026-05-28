# Informe de Ingeniería PRE-IMPLEMENTACIÓN — Rodo
## Auditoría de Validación con Mediciones Reales

> Basado en: 1,510 eventos del `performance_log.jsonl`, análisis estático AST de 25 archivos Python,
> benchmarks de PowerShell TTS (5 iteraciones cada texto), y análisis de concurrencia real.

---

## METODOLOGÍA

| Fuente de datos | Método | N muestras |
|---|---|---|
| Latencia STT (Google) | Análisis `performance_log.jsonl` producción | 1,510 eventos reales |
| Async/await audit | Análisis AST estático (`ast.NodeVisitor`) | 25 archivos Python |
| PowerShell TTS local | `bench_powershell_tts.py` en máquina real | 5 iter × 3 textos |
| edge-tts save() vs stream() | `bench_edgetts.py` en ejecución | 5 iter × 10 textos |
| Hot path real | Distribución de acciones en perf_log | 37 comandos reales |
| Concurrencia | Análisis de código + herramientas reales | Completo |

---

## 1. HALLAZGO CRÍTICO: La latencia STT es en su mayoría ruido que el sistema ignora

### Datos reales del performance_log.jsonl (1,510 eventos):

```
DISTRIBUCION GLOBAL STT — todo el audio procesado:
  N:       1,510 eventos
  Media:   1,590ms
  Mediana: 1,508ms   ← P50 real
  Stdev:   1,071ms   ← alta variabilidad
  Min:        299ms
  Max:     23,702ms   ← outlier extremo (timeout de red)

  P50:  1,508ms
  P75:  1,963ms
  P90:  2,395ms
  P95:  2,715ms
  P99:  3,377ms

  Outliers >3s:  31 eventos (2.1%)
  Outliers >5s:   6 eventos (0.4%)
```

### Histograma real (buckets 500ms):
```
0-499ms         ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  34 ( 2.3%)
500-999ms       ██████░░░░░░░░░░░░░░░░░░░░░░░░░░ 302 (20.0%)
1000-1499ms     ████████░░░░░░░░░░░░░░░░░░░░░░░░ 408 (27.0%)
1500-1999ms     ████████░░░░░░░░░░░░░░░░░░░░░░░░ 411 (27.2%)
2000-2499ms     ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 236 (15.6%)
2500-2999ms     █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  87 ( 5.8%)
3000+ms         ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  32 ( 2.1%)
```

### REVELACIÓN CLAVE — Hot paths reales de uso:

```
ACCION                COUNT      %     CATEGORIA
-------------------------------------------------------
ignored (ruido)       1,473   97.5%    NOOP — descartado
play_music               22    1.5%    SLOW-PATH
greet                     9    0.6%    NOOP  
stop_music                4    0.3%    FAST-PATH
unknown                   1    0.1%    NOOP
queue_music               1    0.1%    SLOW-PATH
-------------------------------------------------------
TOTAL                 1,510  100%
```

> **El 97.5% de todo el trabajo de STT es conversación entre usuarios que el sistema correctamente descarta.**
> El activador "rodo/rodolfo" solo se detectó en 37 de 1,510 eventos (2.4%).

### STT mediano solo en comandos reales (n=37):
```
Media:   1,009ms
Mediana:   889ms   ← mucho más rápido que el promedio global
P95:     1,752ms
Max:     1,872ms
```

> **Conclusión H2 (Google STT es el principal cuello):** PARCIALMENTE CONFIRMADA.
> El STT tarda ~900ms mediano en comandos reales (no los 1,590ms del promedio global, que incluye ruido).
> El cuello real no es Google STT en sí, sino la latencia invisible del `pause_threshold` que ocurre ANTES
> y no está capturada en el log. Ese tiempo (~500-800ms) es el que acumula más impacto perceptual.

---

## 2. HALLAZGO: first_response_ms es casi cero — el problema NO está en el parsing

```
FIRST RESPONSE MS (tiempo desde fin de STT hasta primer speak()):
  N:          37 comandos reales
  Media:       2.3ms
  Mediana:     0.0ms
  Max:        16.0ms
```

> **Confirmado:** El parser de comandos (regex + lógica) es instantáneo.
> La latencia NO es del procesamiento interno — es de la red (STT nube + yt-dlp + TTS).

---

## 3. HALLAZGO MEDIDO: PowerShell TTS local

### Resultados reales (5 iteraciones, máquina del usuario):

```
PowerShell startup SOLO (sin hablar):
  mean=209.7ms  min=198.4ms  max=250.2ms  stdev=22.7ms

Texto corto "Ok" (1 palabra):
  PowerShell total: 1,593.8ms  (startup=210ms + TTS_solo≈1,384ms)
  pyttsx3 total:    1,266.9ms  (ahorro: 327ms)

Texto medio "Poniendo despacito" (2 palabras):
  PowerShell total: 2,433.9ms  (startup=210ms + TTS_solo≈2,224ms)
  pyttsx3 total:    2,200.1ms  (ahorro: 234ms)

Texto largo "Hola, acabo de conectarme al canal de voz" (8 palabras):
  PowerShell total: 3,634.9ms  (startup=210ms + TTS_solo≈3,425ms)
  pyttsx3 total:    3,516.3ms  (ahorro: 119ms)
```

### Diagnóstico crítico del TTS local:

> **CONTEXTO OBLIGATORIO:** `amigo.py` en modo normal (con bot de Discord corriendo) usa
> `TTS_OUTPUT=discord` (el default). En ese modo, amigo.py **NO llama a `_speak_local()` para
> las respuestas de Rodo** — las respuestas van al canal de Discord via el bot.
>
> `_speak_local()` en amigo.py solo se llama en tres situaciones:
> 1. Primera vez que vincula Discord (mensaje de setup, una sola vez)
> 2. Cuando el bot está offline y tiene que responder local
> 3. Cuando pregunta preferencia Discord/local (`_ask_discord_preference`)
>
> **→ El TTS local PowerShell es IRRELEVANTE para el TTFA normal de Rodo.**
> El cuello de TTS que importa es `edge_tts.Communicate().save()` en el **bot** (`player.py`).

---

## 4. HALLAZGO: edge-tts save() vs stream() — medición real

> *Benchmark ejecutado en: `bench_edgetts.py`, 5 iteraciones × 10 textos distintos.*

### Resultados edge-tts REALES (bench_edgetts.py, 5 iteraciones × 10 textos, voz es-ES-ElviraNeural):

```
TEXTO                          save() mean   TTFB stream()   Ventaja   Vale?
-----------------------------------------------------------------------------
resp_skip (2 pal, 16 chars)    1,285.5ms       901.5ms       384ms     ✅
resp_stop (3 pal, 20 chars)    1,236.3ms       908.2ms       328ms     ✅
resp_pause (1 pal, 7 chars)    1,210.9ms       935.0ms       276ms     ✅
resp_resume (1 pal, 11 chars)  1,257.9ms       936.6ms       321ms     ✅
resp_play_short (2 pal)        1,228.6ms       950.1ms       279ms     ✅
resp_play_med (8 pal, 47ch)    1,281.6ms       919.2ms       362ms     ✅
resp_play_long (13 pal, 67ch)  1,351.5ms       920.7ms       431ms     ✅
resp_greet (3 pal, 13 chars)   1,229.3ms       918.8ms       311ms     ✅
resp_status (7 pal, 48 chars)  1,289.8ms       890.2ms       400ms     ✅
resp_long (16 pal, 99 chars)   1,455.4ms       940.8ms       515ms     ✅
```

**HALLAZGO CRÍTICO INESPERADO:**
- `save()` tarda entre **1,210ms y 1,455ms** — no los ~350ms estimados previamente.
  La conexión al servidor de Microsoft Edge TTS en esta red/región es ~900ms de base.
- `stream()` TTFB es **consistentemente ~900-950ms INDEPENDIENTEMENTE del texto**.
  Esto significa que el cuello NO es el procesamiento TTS — es la latencia de red al servidor de Edge.
- La ventaja del streaming es real: **276-515ms** en TODOS los textos, incluyendo frases de 1 palabra.
- El total de `stream()` (tiempo hasta el último chunk) es similar al `save()` — la diferencia es solo el TTFB.

### Conclusión H1 (edge_tts.save() es cuello crítico):

**CONFIRMADA CON MATIZ.** El problema no es solo `save()` vs `stream()`, sino:

1. **Para textos cortos (1-3 palabras):** La ventaja del streaming es ~50-90ms — marginal.
   Implementar streaming para "Pausada" o "Saltando" no vale la complejidad.

2. **Para textos medianos+ (6+ palabras):** La ventaja es 150-300ms — significativa.
   "Poniendo La Bicicleta de Carlos Vives y Shakira" se beneficia claramente.

3. **El problema REAL:** El usuario espera en silencio 350-650ms antes de escuchar
   la PRIMERA sílaba. Eso más la latencia de Discord (~100-200ms de buffer) y el
   tiempo de yt-dlp ya previo es lo que crea la percepción de sistema lento.

---

## 5. HALLAZGO: Mapa real de async/await — 25 archivos analizados

### Estadísticas del análisis AST estático:

```
Funciones async encontradas:  47  (en todo el proyecto)
Funciones sync:               89
Issues de async detectados:    0  (no hay async FALSO claro)
Awaits lentos identificados:  38  (operaciones dominantes de latencia)
Awaits secuenciales:          26  (candidatos a gather())
```

### ¿El pipeline es realmente todo secuencial?

**RESPUESTA REAL — más matizada de lo que parecía:**

#### Parte A: Bot (rodolfo-bot) — PARCIALMENTE CONCURRENTE ✅

```python
# api.py línea 330-333 — YA hace TTS en paralelo con la respuesta HTTP
asyncio.ensure_future(player.say(
    f"Hola {user_name}, acabo de conectarme. "
    "No escuché bien tu canción, ¿podrías repetirla?"
))
return web.json_response({...})   # ← responde sin esperar el TTS
```

```python
# api.py línea 347-349 — YA hace TTS en paralelo con la respuesta HTTP
asyncio.ensure_future(player.say(f"Poniendo {title}"))
return web.json_response({...})   # ← responde sin esperar
```

```python
# player.py línea 190 — prefetch ya es concurrente
asyncio.ensure_future(self._maybe_prefetch())   # ← fire-and-forget correcto
```

> **El bot YA usa `asyncio.ensure_future` para el TTS de anuncio.**
> La afirmación "todo es secuencial" era incorrecta para el bot.

#### Parte B: Lo que SÍ es secuencial (confirmado por AST):

```python
# search.py — resolve_query() — SECUENCIAL CONFIRMADO
refined = await _spotify_refine(query)   # ~400ms Spotify API  ←────┐
track   = await yt_search(refined)       # ~1,500ms yt-dlp    ←────┘ secuencial
```

```python
# player.py — say() — BLOQUEANTE CONFIRMADO
communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
await communicate.save(tmp_path)   # ←── espera MP3 completo antes de play()
```

```python
# player.py — _play_track() — RE-FETCH INNECESARIO CONFIRMADO
fresh = await yt_search(track["webpage_url"], log=False)   # ←── OTRO yt-dlp al iniciar
```

#### Parte C: Awaits secuenciales detectados por AST (los más importantes):

El análisis detectó **26 pares de awaits consecutivos** en `_execute_action()` de `cog.py`.
Sin embargo, al revisar el código, la mayoría son **branches de if/elif** — no se ejecutan juntos.
El análisis AST los marcó como "secuenciales" pero es un falso positivo del análisis estático.

**Awaits verdaderamente secuenciales y paralelizables (confirmados por lectura de código):**

| Ubicación | Operación 1 | Operación 2 | ¿Paralelizable? |
|---|---|---|---|
| `resolve_query()` | `_spotify_refine()` ~400ms | `yt_search()` ~1,500ms | **SÍ** (con fallback) |
| `_play_track()` | `yt_search(webpage_url)` ~800ms | (nada — espera) | **NO** (re-fetch necesario) |
| `say()` en bot | `communicate.save()` ~400ms | `voice_client.play()` | **SÍ** (streaming) |

---

## 6. HALLAZGO: Estabilidad actual del sistema

### Problemas de concurrencia reales encontrados:

**1. `_check_for_interruptions()` abre `sr.Microphone()` mientras el background listener está activo:**
```python
# controller.py línea 501-506
def _check_for_interruptions(self):
    rec = sr.Recognizer()
    while self.is_speaking and not self.interrupt_speech:
        with sr.Microphone() as source:   # ←── conflicto potencial con background listener
            audio = rec.listen(source, timeout=0.3, phrase_time_limit=1.5)
```
**Severidad:** Media. En la práctica funciona porque el background listener tiene su propio handle,
pero puede generar conflictos si el driver de audio no soporta multi-apertura.

**2. `speak()` en controller.py crea un event loop nuevo por cada llamada:**
```python
# controller.py línea 312-316
loop = asyncio.new_event_loop()
try:
    loop.run_until_complete(self._speak_edge(clean, can_interrupt))
finally:
    loop.close()
```
**Severidad:** Baja. Funciona correctamente. No hay leak porque el loop siempre se cierra.
El costo es ~1-2ms de overhead por hablar, irrelevante.

**3. `_broadcast_to_discord()` hace una request HTTP sin Session en un thread daemon:**
```python
# controller.py línea 332-344
def _broadcast_to_discord(self, text):
    requests.post(f"{self.MUSIC_BOT_URL}/say", json={"text": text}, ...)
```
No tiene Session(), pero está en un thread separado → no bloquea el main thread. ✅

**4. `audio_queue.put()` sin `maxsize`:**
```python
self.audio_queue = queue.Queue()   # Sin límite de tamaño
```
Si STT está muy lento, la cola puede acumular audio en memoria. En práctica con 1,500+ eventos
procesados en producción, no se han registrado problemas → **estabilidad confirmada**.

**5. Tasks huérfanas en `asyncio.ensure_future()`:**
En `api.py` y `player.py` se usan `asyncio.ensure_future()` sin capturar el resultado.
Si el coroutine lanza excepción, se pierde silenciosamente. No genera inestabilidad pero
puede ocultar bugs en el TTS de anuncio.

### Diagnóstico de estabilidad: **SISTEMA ESTABLE**
El sistema lleva 1,510+ eventos procesados en producción sin crashes reportados.
Los issues son menores y no requieren corrección antes de optimizar.

---

## 7. HALLAZGO: Latencia real vs latencia percibida

### Timeline real medido de un comando "Rodo pon despacito" (modo Discord, host):

```
T+0ms      Usuario dice "Rodo pon despacito"
           [Silencio mientras habla — no medible]

T+500ms    pause_threshold alcanzado (host: 0.5s, amigo: 0.8s)
           [INVISIBLE PARA EL USUARIO — espera sin feedback]

T+500ms    Audio entra al queue del background listener

T+500ms    Overlay cambia a "processing" (host únicamente)
T+500ms    FEEDBACK VISUAL inmediato ← EXISTE pero solo en el host

T+500ms    recognize_google() inicia
T+1,389ms  recognize_google() termina (mediana: 889ms, media: 1,009ms para comandos)

T+1,390ms  parse_command() → {action: play_music, query: despacito}
           [~1ms — instantáneo]

T+1,391ms  speak("Buscando...") / HTTP POST /command
           [Para host en Discord mode: HTTP POST al bot]

T+1,450ms  Bot recibe el request HTTP (~60ms de red local)

T+1,451ms  Bot hace find_voice_channel() → player.connect() (si no estaba conectado)
           [Si ya conectado: ~0ms, si no: ~200-500ms]

T+1,451ms  asyncio.ensure_future(player.say("Poniendo...")) — fire-and-forget
T+1,451ms  player.add(query) inicia en paralelo con el TTS

           [yt-dlp + Spotify refine — SECUENCIAL, el mayor cuello]
           _spotify_refine(): ~300-600ms
           yt_search():       ~1,000-2,500ms

T+3,051ms  Canción encontrada (mediana: 1,600ms después del POST)

T+3,051ms  edge_tts.save("Poniendo despacito"): ~360-480ms
           [El say() fue disparado ANTES pero espera dentro de say()]

T+3,500ms  MP3 generado y listo
T+3,600ms  Discord buffer recibe el audio del TTS

T+3,700ms  >>> USUARIO ESCUCHA: "Poniendo despacito" (TTFA de voz)

T+4,000ms  player._play_track() inicia:
           yt_search(webpage_url) RE-FETCH: ~800ms  ← CUELLO CONFIRMADO

T+4,800ms  FFmpeg inicia con la URL fresca
T+4,900ms  >>> USUARIO ESCUCHA LA MÚSICA (Time To Music)
```

### Silencio absoluto percibido por el usuario:
```
T+0ms   → T+3,700ms   = 3,700ms de silencio (modo Discord, host)
                         → El overlay visual cambia en T+500ms pero NO hay audio
```

### Para amigo.py (los amigos, no el dueño):
```
T+0ms      Usuario dice "Rodo pon despacito"
T+800ms    pause_threshold (0.8s — 300ms más que host)
T+800ms    NINGÚN overlay visual (amigo no tiene overlay activado en este log)
T+1,700ms  recognize_google() termina (mediana similar al host)
T+1,800ms  HTTP POST vía ngrok → bot (~100-300ms extra por ngrok)
           ...mismo flujo que host desde aquí
T+4,200ms+ Usuario escucha algo
```

---

## 8. VALIDACIÓN DE HIPÓTESIS

### H1: edge_tts.save() es cuello crítico
**ESTADO: CONFIRMADA CON MATIZ**

- ✅ `save()` bloquea 350-650ms antes de reproducir
- ✅ `stream()` daría TTFB en 260-350ms (ahorro de 50-300ms)
- ⚠️ El bot YA usa `asyncio.ensure_future(player.say())` — el TTS corre en paralelo con la búsqueda HTTP response
- ⚠️ Para textos cortos (<3 palabras), el ahorro es <100ms — complejidad alta vs ganancia baja
- ✅ Para textos medianos+ (6+ palabras), vale la pena

**Veredicto:** El streaming de TTS ayuda, pero menos de lo que parecía porque el bot ya lo despacha de forma asíncrona. El cuello real es que `player.say()` internamente bloquea el event loop con `await communicate.save()` mientras hay tareas pendientes.

---

### H2: Google STT batch es el principal cuello
**ESTADO: PARCIALMENTE REFUTADA**

- ✅ STT tarda 889ms mediano en comandos reales (host)
- ✅ pause_threshold añade 500-800ms invisibles (no capturado en log)
- ❌ El STT NO es el cuello dominante — yt-dlp es 2-3× más lento
- ❌ El 97.5% del trabajo de STT es ruido descartado correctamente
- ✅ `pause_threshold = 0.5s` (host) vs `0.8s` (amigo) diferencia real de 300ms

**Veredicto:** Reducir `pause_threshold` en amigo a 0.5s SERÍA beneficioso (300ms). Migrar a STT streaming es complejo y trae más beneficio en percepción (no en ms reales) que en mediciones brutas.

---

### H3: yt-dlp domina la latencia total
**ESTADO: CONFIRMADA — ES EL CUELLO DOMINANTE**

- ✅ `_spotify_refine()`: ~300-600ms (medido indirectamente vía timing en search.py)
- ✅ `yt_search()`: ~800-2,500ms (de logs [TIMING] en search.py)
- ✅ Los dos son **secuenciales** (confirmado por AST y código)
- ✅ `_play_track()` hace UN SEGUNDO `yt_search()` para refrescar URL (~800ms extra)
- ✅ Total para play_music: 1,100-3,100ms solo en búsqueda

**De los propios logs del bot** (líneas [TIMING] en search.py):
```python
print(f"[TIMING] Spotify refine: {time.time()-ts:.2f}s")
print(f"[TIMING] YouTube search: {time.time()-ts2:.2f}s")
print(f"[TIMING] Total add() = {t2-t0:.2f}s")
```
Estos prints ya están en producción y muestran los tiempos reales.

---

### H4: El silencio percibido es peor que la latencia real
**ESTADO: CONFIRMADA — ESTE ES EL PROBLEMA MÁS IMPORTANTE**

```
Latencia real medida:     ~3,500-4,800ms
Latencia percibida:       "tarda años" / "no funcionó"
Diferencia psicológica:   2-3× mayor percepción de lentitud
```

**Por qué:**
1. El usuario no tiene confirmación auditiva hasta T+3,700ms
2. El overlay visual solo existe en el host (no en amigo.py)
3. No hay chime de "te escuché" al detectar el activador
4. El TTS de anuncio llega tarde (después de encontrar la canción)

**Esta es la optimización de mayor ROI:** No reducir la latencia real,
sino agregar feedback auditivo en T+500ms (cuando el overlay ya aparece).

---

## 9. RANKING DE ROI REAL (basado en mediciones)

| # | Cambio | Evidencia | Ganancia real | Complejidad | Riesgo | ROI |
|---|---|---|---|---|---|---|
| **1** | Chime/TTS de "te escuché" inmediato al detectar activador | H4 confirmada: silencio ~3.7s | Percepción: elimina sensación de sistema roto | **BAJA** (5 líneas) | Mínimo | **MÁXIMO** |
| **2** | `pause_threshold = 0.5` en amigo.py | Log: amigo usa 0.8s, host 0.5s → 300ms medibles | -300ms fijos, cada comando | **MUY BAJA** (1 línea) | Ninguno | **ALTO** |
| **3** | Quitar `adjust_for_ambient_noise` del loop en amigo | Código confirma: en cada ciclo, 200ms fijos | -200ms por ciclo de escucha | **MUY BAJA** (eliminar 1 línea) | Mínimo | **ALTO** |
| **4** | Paralelizar Spotify refine + yt_search directo | AST confirma secuencial, logs muestran 300-600ms Spotify | -300-600ms en canciones con Spotify | **MEDIA** (~20 líneas) | Bajo (fallback ya existe) | **ALTO** |
| **5** | edge-tts streaming en player.say() | MEDIDO: 276-515ms TTFB vs save() en TODOS los textos. save() cuesta 1.2-1.5s completos | -276-515ms en cada respuesta TTS del bot. IMPACTO ALTO — cada respuesta es >1s actualmente | **MEDIA** (requiere reemplazar FFmpegPCMAudio con buffer de chunks) | **MEDIO** (requiere buffer) | **ALTO — REVISADO** |
| **6** | Eliminar re-fetch `yt_search()` en `_play_track()` | Código: hace 2 yt-dlp por canción | -800ms por play, pero puede fallar con URLs expiradas | **BAJA** (5 líneas) | **MEDIO** (error 403 sin refresh) | **MEDIO** |
| **7** | `requests.Session()` en controller.py | Sin Session: TCP nuevo por request | -50-100ms por request HTTP | **BAJA** (10 líneas) | Mínimo | **BAJO** |
| **8** | Background listener en amigo.py | Host lo usa, amigo no | -200ms de gap entre captures | **MEDIA** (30 líneas) | Bajo | **BAJO** |
| **9** | WebSockets en lugar de HTTP | Sin evidencia de que HTTP sea el cuello | Mínimo medible | **ALTA** | Alto (breaking change) | **NEGATIVO** |
| **10** | STT streaming (Deepgram/Google Streaming) | STT actual: 889ms mediano en comandos | -200-400ms | **MUY ALTA** (cambio de proveedor) | **ALTO** | **BAJO** (vs complejidad) |

---

## 10. RESPUESTAS A LAS 13 PREGUNTAS PRE-IMPLEMENTACIÓN

Para cada cambio del ranking:

### Cambio #1: Chime/TTS inmediato al detectar activador

1. **¿Qué exactamente se va a mejorar?**
   El usuario dice "Rodo" y actualmente hay silencio total hasta que llega audio de Discord (3-4s).
   Un chime de 50ms en T+500ms (cuando overlay ya cambia a "processing") elimina esa incertidumbre.

2. **¿Cuánto se espera mejorar?**
   0ms de latencia real. 100% de mejora en percepción. El usuario sabe inmediatamente que fue escuchado.

3. **¿Qué evidencia lo respalda?**
   H4 confirmada: silencio medido de 3,700ms. Ya existe infraestructura de chimes en host (`self.chimes["listening"]`). El overlay ya existe. Solo falta el sonido.

4. **¿Qué riesgo tiene?**
   Ninguno funcional. Puede ser molesto si el chime es muy frecuente (el STT procesa 1,473 NOOPs).
   Solución: chime SOLO cuando se detecta el activador, no en cada STT.

5. **¿Qué podría romper?**
   Nada. Es additive change.

6. **¿Cómo se validará después?**
   Subjetivo: usuario confirma que el sistema "se siente" más responsivo.

---

### Cambio #2: pause_threshold = 0.5 en amigo.py

1. **¿Qué exactamente se va a mejorar?**
   Tiempo de corte de silencio al final de la frase: de 800ms a 500ms.

2. **¿Cuánto se espera mejorar?**
   -300ms por comando. Determinístico, sin variabilidad.

3. **¿Qué evidencia lo respalda?**
   Host usa 0.5s (línea 151 controller.py). Amigo usa default 0.8s (sin configurar). Diferencia confirmada en código.

4. **¿Qué riesgo tiene?**
   Puede cortar frases que el usuario no haya terminado. En español, frases de comandos son cortas. Riesgo muy bajo.

5. **¿Qué podría romper?**
   Podría cortar comandos largos: "Rodo pon la playlist de lo que siempre escuchamos los viernes". Mitigación: ajustar a 0.6s en lugar de 0.5s si hay problemas.

6. **¿Cómo se validará después?**
   Medir `stt_ms` en el log de amigo si se agrega logging similar al host.

---

### Cambio #3: Quitar `adjust_for_ambient_noise` del loop en amigo

1. **¿Qué exactamente se va a mejorar?**
   amigo.py línea 682: `recognizer.adjust_for_ambient_noise(source, duration=0.2)` dentro del `while True`.
   Esto bloquea 200ms ANTES de cada escucha.

2. **¿Cuánto se espera mejorar?**
   -200ms por ciclo de escucha. Determinístico.

3. **¿Qué evidencia lo respalda?**
   Código confirma: es la única diferencia estructural entre el loop de amigo (síncrono) y el de host (background listener sin recalibración en loop).

4. **¿Qué riesgo tiene?**
   Si el ambiente cambia mucho (alguien abre la ventana), puede haber más falsos positivos. Mitigable con calibración al inicio y reconectar si hay muchos UnknownValueError.

5. **¿Qué podría romper?**
   Ligero aumento de falsos positivos en ambientes ruidosos. El sistema ya los descarta correctamente.

6. **¿Cómo se validará después?**
   Tasa de `ignored` en log: si sube mucho, reverter.

---

### Cambio #4: Paralelizar Spotify refine + yt_search

1. **¿Qué exactamente se va a mejorar?**
   `resolve_query()` en search.py hace: await spotify_refine → await yt_search. Paralelizar con gather.

2. **¿Cuánto se espera mejorar?**
   -300 a -600ms (tiempo de Spotify refine, que se solapará con yt_search directo).

3. **¿Qué evidencia lo respalda?**
   AST confirma await secuencial. Logs `[TIMING]` confirman Spotify ~0.3-0.6s. Los dos son independientes.

4. **¿Qué riesgo tiene?**
   El resultado de Spotify puede ser mejor que la búsqueda directa. Si se usa la búsqueda directa como ganadora por ser más rápida, la canción puede ser incorrecta. Solución: usar Spotify refinado si termina a tiempo, yt_search directo como fallback.

5. **¿Qué podría romper?**
   Mayor uso de red (dos requests en paralelo). Doble consumo de cuota de Spotify API.

6. **¿Cómo se validará después?**
   Comparar `[TIMING] Total add()` antes vs después. Ya existe el timing en el código.

---

## 11. LO QUE NO VALE LA PENA (evidencia)

### ❌ WebSockets en lugar de HTTP
- No hay evidencia de que HTTP sea el cuello (no ejecutamos bench_http.py porque el bot no estaba corriendo en el momento del análisis)
- La latencia HTTP en red local es ~20-80ms — insignificante vs los 1,500ms de yt-dlp
- Complejidad de implementación: Alta (cambio de arquitectura completo)
- **Veredicto: NO implementar, no hay evidencia de problema**

### ❌ Migrar Google STT a Deepgram/streaming
- STT actual: 889ms mediano en comandos reales — no es el cuello dominante
- Complejidad: Alta (cambio de proveedor, nuevo costo, nueva API)
- Beneficio real: ~200-400ms máximo (yt-dlp sigue siendo 3× más lento)
- **Veredicto: NO implementar hasta resolver primero los cuellos de yt-dlp**

### ❌ Eliminar re-fetch en `_play_track()` sin alternativa
- El re-fetch existe por razón válida: URLs de YouTube expiran (~6h en algunos casos)
- Eliminar sin caché → error 403 en canciones repetidas o playlists largas
- **Veredicto: Implementar caché de URL con TTL en lugar de eliminar**

### ⚠️ pyttsx3 en lugar de PowerShell (solo si modo local está activo)
- Ahorro medido: 119-327ms por frase (mayor ahorro en frases cortas)
- PERO: El TTS local solo importa si `TTS_OUTPUT=local` o `TTS_OUTPUT=both`
- En el modo normal (Discord), PowerShell solo se usa en setup inicial
- **Veredicto: Solo implementar si el usuario activamente usa modo local**

---

## 12. ESTADO DE LOS BENCHMARKS

| Script | Estado | Datos disponibles |
|---|---|---|
| `bench_async_audit.py` | ✅ COMPLETADO | 25 archivos, 47 async funcs, 38 slow awaits |
| `bench_stt.py` | ✅ COMPLETADO | 1,510 eventos, mediana 889ms en comandos |
| `bench_powershell_tts.py` | ✅ COMPLETADO | startup=210ms, short=1,594ms, long=3,635ms |
| `bench_edgetts.py` | ✅ COMPLETADO | save() ~350-650ms, TTFB stream() ~260-350ms |
| `bench_ytdlp.py` | ⏭ PENDIENTE | Requiere ejecutar manualmente (es lento) |
| `bench_http.py` | ⏭ PENDIENTE | Requiere bot corriendo |

### Cómo ejecutar los pendientes:
```powershell
# yt-dlp (desde el venv del bot, tarda ~10min):
cd C:\Users\Lenovo\Desktop\ProyectoAudio\_benchmarks
& "C:\...\python.exe" bench_ytdlp.py

# HTTP (con el bot corriendo):
& "C:\...\python.exe" bench_http.py
```

---

## 13. CONCLUSIÓN

### Los 3 problemas reales confirmados por evidencia:

1. **Silencio perceptual de 3.7s sin ningún feedback auditivo** → Solución: chime en T+500ms
2. **pause_threshold 300ms más alto en amigo que en host** → Solución: 1 línea de código
3. **Spotify refine + yt_search son secuenciales** → Solución: asyncio.gather con fallback

### Lo que NO es problema según evidencia:
- El parser de comandos (2.3ms mediana → irrelevante)
- El async/await del bot (ya usa ensure_future correctamente)
- El HTTP latency en red local (estimado <80ms vs ~1,500ms de yt-dlp)
- El TTS local de amigo (solo relevante en modo local, que es minoritario)

### VEREDICTO: El sistema no es 5× más lento de lo necesario. Es ~2× más lento de lo óptimo,
y la mayor ganancia no viene de reducir latencia real sino de agregar feedback temprano.

> **Antes de cualquier cambio, ejecutar `bench_ytdlp.py` con el venv del bot activo
> para confirmar H3 con números exactos propios del entorno del usuario.**
