# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Visión del producto

**Byarox** es un asistente de voz unificado que se instala en cualquier PC.
Detecta el contexto del usuario y enruta cada comando al módulo correcto,
sin que el usuario tenga que pensar en qué herramienta usar.
El activador de voz es la palabra **"Byarox"** (nombre del proyecto + del wake word).

---

## Comandos de desarrollo

### Levantar el servidor (bot + ngrok)
```bash
cd rodolfo-bot
python lanzar.py          # bot + túnel ngrok en una sola terminal
# Alternativa sin ngrok (solo el bot HTTP):
python bot.py
```

### Levantar bot + host juntos (dev local)
```bash
python dev-local.py       # o doble clic en dev-local.bat
# Lanza rodolfo-bot/bot.py y rodolfo-host/controller.py con output coloreado
```

### Correr el cliente desde fuente (sin compilar)
```bash
cd rodolfo-amigo
python amigo.py
```

### Entrenar el clasificador de wake word
```bash
cd rodolfo-amigo
python -m modules.wakeword.train_byarox
# Genera: modules/wakeword/byarox_verifier.pkl
# Requiere: edge-tts, ffmpeg, openwakeword, sklearn
```

### Correr tests de los nuevos módulos
```bash
cd rodolfo-amigo
python tests/test_vad.py       # 6 tests — SileroVAD + SpeechSegmenter
python tests/test_ducking.py   # 5 tests — DuckingManager
python tests/test_wakeword.py  # 7 tests — WakeWordEngine + verifier pkl
```

### Compilar Byarox.exe
```powershell
# Primero cerrar cualquier Byarox.exe abierto:
Get-Process Byarox -ErrorAction SilentlyContinue | Stop-Process -Force

cd rodolfo-amigo
pyinstaller rodo.spec --noconfirm
# Salida: dist\Byarox.exe (autocontenido, sin Python requerido)
```

### Publicar una release (requiere permiso explícito)
```powershell
# 1. Bumpar version.py y version.json a vX.Y.Z
# 2. Compilar (ver arriba)
# 3. Commit + push
# 4. Publicar en GitHub:
.\actualizar_release.ps1 -Token "ghp_..." -Tag "vX.Y.Z" -Notes "changelog"
```

### Ver logs del cliente en tiempo real
```powershell
Get-Content "$env:LOCALAPPDATA\Rodo\rodo_voice.log" -Wait -Tail 50
```

### Matar procesos del bot si se cuelga
```powershell
netstat -ano | findstr :5000
Stop-Process -Id <PID> -Force
```

---

## Arquitectura del sistema

```
rodolfo-amigo/    ← cliente instalado en cada PC → Byarox.exe
rodolfo-bot/      ← servidor compartido (Discord bot + HTTP API)
rodolfo-host/     ← motor local en desarrollo (volumen, Spotify local)
```

### `rodolfo-amigo/` — El cliente

**Punto de entrada:** `amigo.py` — loop principal de escucha.

#### Flujo interno (arquitectura actual — v1.0.11)

```
[Hilo daemon] WakeWordEngine
  PyAudio 16kHz → openwakeword embeddings → byarox_verifier.pkl
  → score ≥ 0.5 → loguea detección offline
  → _is_speaking activo → ignorar (anti-feedback TTS)

[Loop principal] amigo.py
  adjust_for_ambient_noise (0.2s) → cap energy_threshold=3500
  recognizer.listen(timeout=10, phrase_time_limit=7)
  → Google STT → texto
  → STT corrections (biarox/biharox/yarox → byarox)
  → has_activator("byarox") → extraer comando
  → solo "Byarox" → _speak_local_bg("dime") + ventana 6s
  → "Byarox + comando" → orchestrator.decide()
      → handler "discord"     → POST /command al bot → "lo tengo"
      → handler "local"       → Spotify URI / YouTube
      → handler "local_media" → tecla multimedia
      → handler "oauth"       → flujo OAuth Spotify
      → handler "ask"         → preguntar Discord o local
      → handler "ignore"      → nada

[Al detectar activador]
  _mute_system():
    → _duck_mgr.duck()  (pycaw: Spotify/Chrome/etc. → 15%)
    → fallback nircmd si pycaw no disponible
    → _spotify_pause() via API (Spotify Connect remoto)

[Al terminar de procesar]
  _unmute_system():
    → _duck_mgr.restore()  (fade-in a volumen original)
    → _spotify_resume() si corresponde
```

#### Módulos principales en `rodolfo-amigo/`

| Archivo | Rol |
|---|---|
| `amigo.py` | Entrada, loop STT, routing, TTS local |
| `orchestrator.py` | Singleton de estado de sesión + `decide()` |
| `command_parser.py` | **Copia** del parser del bot — sincronizar siempre |
| `overlay.py` | Ventana flotante de estado (tkinter) |
| `tray.py` | Ícono en bandeja del sistema (pystray) |
| `config_manager.py` | Lee/escribe `config.json` en `%LOCALAPPDATA%\Rodo\` |
| `setup_gui.py` | Setup de primera vez |
| `updater.py` | Auto-update desde GitHub Releases |
| `version.py` / `version.json` | Versión actual + URL de descarga |

#### Nuevos módulos de voz (`rodolfo-amigo/modules/`)

| Módulo | Archivo | Rol |
|---|---|---|
| **parser** | `modules/parser/` | Normalizador, correcciones STT, fuzzy, parser de intents |
| **wakeword** | `modules/wakeword/wakeword_engine.py` | Detector siempre-activo: PyAudio 16kHz → openwakeword embeddings → sklearn pkl |
| **wakeword** | `modules/wakeword/train_byarox.py` | Entrena `byarox_verifier.pkl` con edge-tts + ffmpeg + LogisticRegression |
| **wakeword** | `modules/wakeword/byarox_verifier.pkl` | Clasificador entrenado (4 voces, acc=100%, P(byarox\|pos)=0.997) |
| **vad** | `modules/vad/vad_engine.py` | Silero VAD (ONNX 16kHz, 512 samples, stateful h/c) + SpeechSegmenter |
| **ducking** | `modules/ducking/ducking_manager.py` | pycaw: fade Spotify/Chrome/Firefox/Edge a 15% al escuchar, restaurar al terminar |
| **metrics** | `modules/metrics/voice_metrics.py` | Mide latencias: wakeword_ms, ducking_ms, stt_ms, ttfa_ms |

#### Tests (`rodolfo-amigo/tests/`)

| Archivo | Tests | Estado |
|---|---|---|
| `test_vad.py` | 6 | ✅ todos pasan |
| `test_ducking.py` | 5 | ✅ todos pasan |
| `test_wakeword.py` | 7 | ✅ todos pasan |

**⚠️ Hay DOS copias de `command_parser.py`:** una en `rodolfo-amigo/` (va al exe) y otra en `rodolfo-bot/` (usa el servidor). Cualquier cambio al parser **debe aplicarse en ambos archivos.**

**Extracción del exe:** `rodo.spec` usa `runtime_tmpdir="%LOCALAPPDATA%\Rodo"` — las carpetas `_MEI*` van ahí. Crítico para el updater.

---

### `rodolfo-bot/` — El servidor compartido

**Punto de entrada:** `bot.py` — inicializa discord.py + levanta el servidor aiohttp.

La API HTTP está en `api_runtime/`:
| Módulo | Endpoints |
|---|---|
| `api_runtime/server.py` | Composición, `app`, `auth_middleware` |
| `api_runtime/command.py` | `POST /command` — despacho principal |
| `api_runtime/music.py` | `/play`, `/stop`, `/skip`, `/pause`, `/resume`, `/status`, `/volume`, `/disconnect`, `/say`, `/clear_queue`, `/health` |
| `api_runtime/spotify.py` | `/spotify/login`, `/spotify/callback`, `/me/spotify_status` |
| `api_runtime/context.py` | `/context`, `/move`, `/discord_auth`, `/discord_refresh` |
| `api_runtime/admin.py` | `/admin/*` — gestión de usuarios/tokens |
| `api_runtime/dashboard.py` | `/dashboard` — panel web |

La lógica de música en `modules/music/`:
| Archivo | Rol |
|---|---|
| `cog.py` | Cog de discord.py con los comandos del bot |
| `player.py` | Cola de reproducción por guild, yt-dlp, edge-tts |
| `search.py` | Búsqueda Spotify → YouTube |
| `sink.py` | AudioSink para captura de audio del canal de voz |
| `cache/` | SQLite cache de URLs de stream con scoring L1/L2/L3 |

**Config del bot:** variables en `rodolfo-bot/.env`:
- `DISCORD_OWNER_USER_ID`, `DISCORD_GUILD_ID`
- `MUSIC_BOT_PORT` (default 5000), `MUSIC_BOT_HOST`
- `NGROK_DOMAIN` — dominio fijo de ngrok
- `TTS_VOICE` — voz de edge-tts (ej: `es-PE-AlexNeural`)
- `SPOTIFY_CLIENT_ID` + `SPOTIFY_CALLBACK_PORT/HOST`

**Tokens de usuario:** `tokens.json` — `{"<username>": {"token": "...", "name": "...", "active": true, "spotify": {...}}}`.

---

## Arquitectura de contexto (routing)

```
"Byarox pon flaca"
        │
        ▼
  [Orquestador] orchestrator.decide()
  ¿discord_mode es True / False / None?
        │
   True  ──────────────→ POST /command al bot Discord
   False ──────────────→ modo local (Spotify URI o YouTube)
   None  ──────────────→ Pregunta UNA VEZ: "¿Discord o local?"
```

**Reset automático:** salir de canal de voz → `discord_mode = False`; volver a entrar → `discord_mode = None`.

---

## Flujo de reproducción local

```
discord_mode is False
  → orchestrator.has_spotify?
      SÍ → búsqueda en biblioteca personal (score ≥ 0.5)
      NO → POST /command?local=true → Spotify público → URI
  → Fallback: YouTube (abre en navegador)
```

---

## Flujo OAuth Spotify personal

```
"Byarox vincula mi Spotify"
  → abre /spotify/login en el bot
  → Spotify OAuth → callback local
  → guarda tokens en tokens.json
  → amigo.py carga token vía /me/spotify_status
```

---

## Detalles técnicos de los módulos nuevos

### WakeWordEngine (`modules/wakeword/`)

**Dos modos:**
- **Verifier** (si existe `byarox_verifier.pkl`): `audio → oww_model.predict() → preprocessor.get_features(16) → shape(1,16,96) → flatten(1,1536) → LogisticRegression → proba clase 1`
- **Fallback** (sin pkl): usa score nativo de `hey_jarvis_v0.1` con threshold 0.3

**Entrenamiento del pkl:**
- 40 positivos: edge-tts (4 voces × 3 velocidades × frases con "byarox") → mp3 → ffmpeg → WAV 16kHz
- 40 negativos: silencio puro + ruido gaussiano
- Pipeline: `StandardScaler + LogisticRegression(C=1, balanced)`
- Resultado: acc=100%, P(byarox|pos)=0.997, P(byarox|neg)=0.002

**Integración en amigo.py:**
- Corre en hilo daemon desde el inicio de `main()`
- Callback `_on_wakeword` loguea la detección y actualiza `_ww_last_fire`
- Si `_is_speaking` está activo (TTS hablando) → ignora la detección (anti-feedback)
- Si falla (sin openwakeword, conflicto de mic) → falla silenciosamente

### DuckingManager (`modules/ducking/`)

- Busca sesiones de audio de Spotify/Chrome/Firefox/Edge via `pycaw.AudioUtilities`
- `duck()`: fade-out a 15% en ~120ms (hilo daemon)
- `restore()`: fade-in a volumen original en ~300ms
- Fallback: volumen maestro si no hay sesiones multimedia
- En amigo.py: reemplaza `nircmd mutesysvolume` en `_mute_system()` / `_unmute_system()`

### SileroVAD (`modules/vad/`)

- Modelo ONNX (`silero_vad.onnx`, ~2 MB, se descarga automáticamente)
- Inputs: `input[1,512]`, `sr`, `h[2,1,64]`, `c[2,1,64]` (stateful)
- `SpeechSegmenter`: acumula chunks de 512 samples, retorna segmento completo tras 1200ms de silencio o 7s máximo

### Anti-feedback TTS

`_is_speaking = threading.Event()` — activo mientras `_speak_local` reproduce. Evita que el WakeWordEngine o el STT detecten la propia voz del asistente como un nuevo comando.

---

## Cómo agregar una nueva habilidad

1. **Detectar el intent** — en **ambas** copias de `command_parser.py`:
   ```python
   if any(w in cmd for w in ["palabra_clave", "variante"]):
       return {"action": "nueva_accion", "param": ...}
   ```

2. **Endpoint en el bot** — en `rodolfo-bot/api_runtime/`:
   ```python
   async def http_nueva_accion(request): ...
   # Registrar en api_runtime/server.py
   ```

3. **Routing en el cliente** — `amigo.py` envía todo via `/command`. Lógica local antes del envío si hace falta.

4. **Actualizar este archivo.**

---

## Flujo de release

1. Hacer los cambios.
2. **Pedir permiso** para subir versión (Regla 1).
3. Actualizar `rodolfo-amigo/version.py` y `rodolfo-amigo/version.json`.
4. Compilar: `pyinstaller rodo.spec --noconfirm` (en `rodolfo-amigo/`).
5. `git add <archivos específicos> && git commit && git push`
6. `.\actualizar_release.ps1 -Token "..." -Tag "vX.Y.Z" -Notes "..."`
7. Los usuarios reciben la actualización al abrir Byarox.

---

## Reglas para Claude

1. **Nunca subir versiones sin permiso explícito.**
   - No cambiar `version.py` ni `version.json` sin que el usuario lo pida.
   - No crear releases ni ejecutar `actualizar_release.ps1` sin autorización.

2. **El activador de voz es "Rodolfo" (nombre hablado del asistente), no "Byarox".**
   - Byarox es la marca/app; al asistente se le habla como Rodolfo.
   - `ACTIVATOR_NAMES = ("oye rodolfo", "rodolfo")` en `amigo.py` y en `modules/parser/normalizer.py` — no agregar otros sin pedirlo.

3. **No hacer commits automáticos.**
   - Solo commitear cuando el usuario lo pida explícitamente.

4. **Antes de cualquier cambio grande, confirmar el plan.**
   - Si el cambio toca más de 2 archivos o cambia comportamiento visible, describir qué se va a hacer antes de hacerlo.

5. **Mantener retrocompatibilidad.**
   - `config.json` ya está en las PCs de los amigos. No cambiar sus campos sin migración.

6. **Respetar el enrutamiento por contexto.**
   - Nunca hardcodear un destino (Discord o local). Siempre pasar por `orchestrator.decide()`.

7. **Sincronizar ambas copias del parser.**
   - Cualquier cambio en `command_parser.py` debe aplicarse tanto en `rodolfo-amigo/` como en `rodolfo-bot/`.

8. **Los módulos nuevos son opcionales.**
   - `wakeword`, `vad`, `ducking`, `metrics` deben fallar silenciosamente si faltan deps.
   - Nunca romper el flujo STT principal por culpa de un módulo opcional.

---

## Stack técnico

| Componente | Stack |
|---|---|
| Cliente (`rodolfo-amigo`) | Python + SpeechRecognition + Google STT + pystray + tkinter + PyInstaller |
| Wake word | openwakeword (ONNX) + sklearn LogisticRegression + `byarox_verifier.pkl` |
| VAD | Silero VAD (ONNX, 16kHz, stateful) |
| Audio ducking | pycaw (Windows Core Audio) → fade per-app; fallback nircmd |
| Métricas | `VoiceMetrics` — latencias en ms (wakeword, ducking, stt, ttfa) |
| Orquestador | `orchestrator.py` — Python puro, estado de sesión |
| Servidor | Python + discord.py + yt-dlp + edge-tts + spotipy + aiohttp + ngrok |
| Motor local | Python + pygame + nircmd + spotipy OAuth + edge-tts |
| STT | Google STT (principal) — Whisper local (futuro) |
| Música | Spotify metadata → YouTube audio |
| Spotify personal | spotipy OAuth — playlists y álbumes del usuario |
| Tokens | `tokens.json` — un token por usuario, Spotify embebido |
| Extracción exe | `%LOCALAPPDATA%\Rodo\` (estable entre updates) |

---

## Estado actual (v1.0.11)

### ✅ Completado

**Arquitectura base**
- Orquestador central con estado de sesión y routing
- Contexto Discord/local: pregunta una vez, recuerda por sesión
- Reset de `discord_mode` al salir/entrar de canal

**Nombre y activador**
- Marca/app renombrada: Rodo → Byarox (exe, logos, shortcuts). El asistente se sigue llamando Rodolfo al hablarle.
- Activador: `ACTIVATOR_NAMES = ("oye rodolfo", "rodolfo")`

**UX de voz**
- "dime" al esperar comando (solo dijo "Byarox")
- "lo tengo" al confirmar envío al bot
- Cap de `energy_threshold` a 3500 (evita que música tape la voz)
- "detente" reconocido como stop

**Módulos de voz (implementados y testeados)**
- `WakeWordEngine`: detector local siempre activo, dos modos (verifier pkl / fallback)
- `train_byarox.py`: entrena el clasificador con edge-tts + openwakeword
- `byarox_verifier.pkl`: entrenado (acc=100%, P(byarox|pos)=0.997)
- `SileroVAD` + `SpeechSegmenter`: VAD local ONNX
- `DuckingManager`: fade per-app con pycaw
- `VoiceMetrics`: métricas de latencia
- 18 tests (6+5+7) todos en verde

**Integración en amigo.py**
- `DuckingManager` reemplaza nircmd en `_mute_system`/`_unmute_system`
- `_is_speaking` flag anti-feedback en `_speak_local_bg`
- `WakeWordEngine` corre como hilo daemon (opcional, falla silenciosamente)

**Spotify personal**
- OAuth flow completo por voz
- Búsqueda en biblioteca personal
- Soporte multi-usuario

---

## Pendientes (en orden de prioridad)

### Próximo paso inmediato
- [ ] **Compilar y publicar v1.0.11** (Byarox.exe — primer release con nuevo nombre + módulos de voz)
  - `pyinstaller rodo.spec --noconfirm` → verificar que Byarox.exe carga `byarox_verifier.pkl` y pycaw
  - Puede requerir ajuste de `rodo.spec` (hiddenimports de pycaw/comtypes son complejos)

### Arquitectura de voz — siguiente evolución
- [ ] **Loop full-duplex real**: reemplazar `recognizer.listen()` por VAD+WakeWordEngine como fuente primaria
  - WakeWordEngine detecta "byarox" → VAD captura el segmento de comando → Google STT solo para el comando
  - Elimina el gap de 0.2s de `adjust_for_ambient_noise` en cada iteración
- [ ] **STT local** con Whisper (sin internet, más privado)
  - Integrar `faster-whisper` o `whisper.cpp` como fallback de Google STT
- [ ] **Usar `_ww_last_fire`** para correlación: si WakeWordEngine disparó hace <2s, reducir umbral de confianza del STT

### Arquitectura general
- [ ] Fusión de `rodolfo-host` en `rodolfo-amigo` (un solo exe)
- [ ] Integrar `orchestrator.decide()` con LLM (Claude API) como reemplazo de reglas rígidas
- [ ] Eliminar duplicación de `command_parser.py` (un solo módulo compartido)

### Spotify personal
- [ ] Cambio de dispositivo Spotify por voz ("Byarox cambia al celular")
- [ ] Listar dispositivos por voz ("Byarox qué dispositivos tengo")

### UX y voz
- [ ] Control de volumen de Windows por voz
- [ ] Usar `VoiceMetrics.log_report()` al final de cada comando (telemetría de latencia)

### Música Discord
- [ ] Ver cola en Discord
- [ ] Letras de canciones

### Infraestructura
- [ ] Auto-restart del bot si se cae
- [ ] Hosting VPS 24/7
- [ ] Panel web de administración
- [ ] Certificado de código (evitar aviso "desconocido" en Windows)
