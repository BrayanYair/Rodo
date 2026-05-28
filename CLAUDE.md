# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Visión del producto

Rodo es un **asistente de voz unificado** que se instala en cualquier PC.
Detecta el contexto del usuario y enruta cada comando al módulo correcto,
sin que el usuario tenga que pensar en qué herramienta usar.

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

### Compilar Rodo.exe
```powershell
# Primero cerrar cualquier Rodo.exe abierto:
Get-Process Rodo -ErrorAction SilentlyContinue | Stop-Process -Force

cd rodolfo-amigo
pyinstaller rodo.spec --noconfirm
# Salida: dist\Rodo.exe (~66 MB, autocontenido, sin Python requerido)
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
# Ver qué está usando el puerto 5000:
netstat -ano | findstr :5000
Stop-Process -Id <PID> -Force
```

---

## Arquitectura del sistema

```
rodolfo-amigo/    ← cliente instalado en cada PC de usuario → Rodo.exe
rodolfo-bot/      ← servidor compartido (Discord bot + HTTP API)
rodolfo-host/     ← motor local en desarrollo (volumen, Spotify local)
```

### `rodolfo-amigo/` — El cliente

**Punto de entrada:** `amigo.py` — loop de escucha de micrófono.

Flujo interno por iteración:
1. `adjust_for_ambient_noise` (0.2s) → cap `energy_threshold` a 3500
2. `recognizer.listen(timeout=10, phrase_time_limit=7)`
3. Google STT → texto
4. Detecta activador "rodo" → si hay comando → `_speak_local_bg("lo tengo")` al confirmar envío; si solo "Rodo" solo → `_speak_local_bg("dime")`
5. `orchestrator.decide()` → `Action` con handler: `"discord"` | `"local"` | `"local_media"` | `"ask"` | `"oauth"` | `"ignore"`
6. Handler `"discord"` → `_send_command_full()` → `POST /command` al bot

Módulos en `rodolfo-amigo/`:
| Archivo | Rol |
|---|---|
| `amigo.py` | Entrada, loop STT, routing, TTS local |
| `orchestrator.py` | Singleton de estado de sesión + `decide()` |
| `command_parser.py` | **Copia** del parser del bot — debe mantenerse en sync con `rodolfo-bot/command_parser.py` |
| `overlay.py` | Ventana flotante de estado (tkinter) |
| `tray.py` | Ícono en bandeja del sistema (pystray) |
| `config_manager.py` | Lee/escribe `config.json` en `%LOCALAPPDATA%\Rodo\` |
| `setup_gui.py` | Setup de primera vez (URL del bot + token) |
| `updater.py` | Auto-update desde GitHub Releases |
| `version.py` / `version.json` | Versión actual + URL de descarga |

**⚠️ Hay DOS copias de `command_parser.py`:** una en `rodolfo-amigo/` (va al exe) y otra en `rodolfo-bot/` (usa el servidor). Cualquier cambio al parser **debe aplicarse en ambos archivos.**

**Extracción del exe:** `rodo.spec` usa `runtime_tmpdir="%LOCALAPPDATA%\Rodo"` — las carpetas `_MEI*` van ahí, no en `%TEMP%`. Esto es crítico para el updater.

### `rodolfo-bot/` — El servidor compartido

**Punto de entrada:** `bot.py` — inicializa discord.py + levanta el servidor aiohttp.

La API HTTP está en `api_runtime/` (separada en módulos desde la refactorización):
| Módulo | Endpoints |
|---|---|
| `api_runtime/server.py` | Composición, `app`, `auth_middleware` |
| `api_runtime/command.py` | `POST /command` — despacho principal |
| `api_runtime/music.py` | `/play`, `/stop`, `/skip`, `/pause`, `/resume`, `/status`, `/volume`, `/disconnect`, `/say`, `/clear_queue`, `/health` |
| `api_runtime/spotify.py` | `/spotify/login`, `/spotify/callback`, `/me/spotify_status` |
| `api_runtime/context.py` | `/context`, `/move`, `/discord_auth`, `/discord_refresh` |
| `api_runtime/admin.py` | `/admin/*` — gestión de usuarios/tokens |
| `api_runtime/dashboard.py` | `/dashboard` — panel web |

La lógica de música está en `modules/music/`:
| Archivo | Rol |
|---|---|
| `cog.py` | Cog de discord.py con los comandos del bot |
| `player.py` | Cola de reproducción por guild, yt-dlp, edge-tts |
| `search.py` | Búsqueda Spotify → YouTube. `_parse_artist_from_query` usa regex greedy para split `"track de artist"` |
| `sink.py` | AudioSink para captura de audio del canal de voz |
| `cache/` | SQLite cache de URLs de stream con scoring L1/L2/L3 |

**Config del bot:** variables de entorno en `rodolfo-bot/.env`. Claves importantes:
- `DISCORD_OWNER_USER_ID`, `DISCORD_GUILD_ID` — IDs del servidor
- `MUSIC_BOT_PORT` (default 5000), `MUSIC_BOT_HOST`
- `NGROK_DOMAIN` — dominio fijo de ngrok (no cambia al reiniciar)
- `TTS_VOICE` — voz de edge-tts (ej: `es-PE-AlexNeural`)
- `SPOTIFY_CLIENT_ID` + `SPOTIFY_CALLBACK_PORT/HOST`

**Tokens de usuario:** `tokens.json` — `{"<username>": {"token": "...", "name": "...", "active": true, "spotify": {...}}}`. Clave especial `"owner"` para el dueño del bot.

---

## Arquitectura de contexto (routing)

```
"Rodo pon flaca"
        │
        ▼
  [Orquestador] orchestrator.decide()
  ¿discord_mode es True / False / None?
        │
   True  ──────────────→ POST /command al bot Discord
   False ──────────────→ modo local (Spotify URI o YouTube)
   None  ──────────────→ Pregunta UNA VEZ: "¿Discord o local?"
```

**Reset automático:** salir de un canal de Discord → `discord_mode = False`; volver a entrar → `discord_mode = None` (vuelve a preguntar).

---

## Flujo de reproducción local

```
discord_mode is False
  → orchestrator.has_spotify?
      SÍ → search_personal_library() → URI de biblioteca personal (score ≥ 0.5)
      NO → POST /command?local=true → Spotify público → URI
  → Fallback: YouTube (abre en navegador)
```

---

## Flujo OAuth Spotify personal

```
"Rodo vincula mi Spotify"
  → amigo.py → abre /spotify/login?user_token=<token_rodo>
  → bot redirige a Spotify OAuth
  → callback /spotify/callback?state=<username_key>
  → guarda tokens en tokens.json bajo el usuario
  → amigo.py carga token vía /me/spotify_status
```

---

## Cómo agregar una nueva habilidad

1. **Detectar el intent** — en **ambas** copias de `command_parser.py` (`rodolfo-amigo/` y `rodolfo-bot/`):
   ```python
   if any(w in cmd for w in ["palabra_clave", "variante"]):
       return {"action": "nueva_accion", "param": ...}
   ```

2. **Endpoint en el bot** — en `rodolfo-bot/api_runtime/` (el módulo que corresponda):
   ```python
   async def http_nueva_accion(request):
       ...
   # y registrarlo en api_runtime/server.py
   ```

3. **Routing en el cliente** — `amigo.py` ya envía todo via `/command`. Si necesita lógica local (overlay, TTS, Spotify URI), agregarla antes del envío.

4. **Actualizar este archivo** con el pendiente correspondiente.

---

## Flujo de release

1. Hacer los cambios en el código.
2. **Pedir permiso** para subir versión (Regla 1).
3. Actualizar `rodolfo-amigo/version.py` y `rodolfo-amigo/version.json`.
4. Compilar: `pyinstaller rodo.spec --noconfirm` (en `rodolfo-amigo/`).
5. `git add <archivos específicos> && git commit && git push`
6. `.\actualizar_release.ps1 -Token "..." -Tag "vX.Y.Z" -Notes "..."`
7. Los usuarios reciben la actualización automáticamente al abrir Rodo.

---

## Reglas para Claude

1. **Nunca subir versiones sin permiso explícito.**
   - No cambiar `version.py` ni `version.json` sin que el usuario lo pida.
   - No crear releases ni ejecutar `actualizar_release.ps1` sin autorización.

2. **El activador de voz es solo "rodo".**
   - `ACTIVATOR_NAMES = ("rodo",)` — no agregar otros sin pedirlo.

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

---

## Stack técnico

| Componente | Stack |
|---|---|
| Cliente (`rodolfo-amigo`) | Python + SpeechRecognition + Google STT + pystray + tkinter + PyInstaller |
| Orquestador (`orchestrator.py`) | Python puro — sin dependencias externas; punto de extensión para Claude API |
| Servidor (`rodolfo-bot`) | Python + discord.py + yt-dlp + edge-tts + spotipy + aiohttp + ngrok |
| Motor local (`rodolfo-host`) | Python + pygame + nircmd + spotipy OAuth + edge-tts |
| STT | Google STT (principal) — Whisper local (futuro fallback) |
| Música | Spotify busca metadata → YouTube reproduce audio |
| Spotify personal | spotipy OAuth — playlists y álbumes del usuario |
| Tokens | `tokens.json` — un token por usuario, Spotify tokens embebidos |
| Extracción del exe | `%LOCALAPPDATA%\Rodo\` (estable entre actualizaciones, no `%TEMP%`) |

---

## Pendientes (en orden de prioridad)

### Arquitectura
- [x] Orquestador central (`orchestrator.py`) con estado de sesión y routing
- [x] Lógica de contexto en `rodolfo-amigo`: preguntar una vez, recordar por sesión
- [x] Reset de `discord_mode` al salir/entrar de canal de Discord
- [ ] Fusión de `rodolfo-host` en `rodolfo-amigo` (un solo exe con todas las capacidades)
- [ ] Integrar `orchestrator.decide()` con lógica LLM (Claude API) como reemplazo de reglas
- [ ] Eliminar la duplicación de `command_parser.py` (un solo módulo compartido)

### Spotify personal
- [x] OAuth flow completo: vinculación por voz ("Rodo vincula mi Spotify")
- [x] Búsqueda en biblioteca personal (playlists + álbumes guardados)
- [x] Soporte multi-usuario: cada amigo vincula su propio Spotify
- [ ] Cambio de dispositivo Spotify por voz ("Rodo cambia al celular")
- [ ] Listar dispositivos de salida por voz ("Rodo qué dispositivos tengo")

### UX y voz
- [x] Feedback por voz: "dime" al esperar comando, "lo tengo" al confirmar envío
- [x] "detente" / "stock" / "para" reconocidos como stop
- [x] Cap de energy_threshold (3500) para que música de fondo no tape la voz del usuario
- [ ] Control de volumen de Windows por voz
- [ ] Whisper local (STT sin internet)

### Música Discord
- [ ] Ver cola en Discord
- [ ] Letras de canciones

### Infraestructura
- [ ] Auto-restart del bot si se cae
- [ ] Hosting VPS 24/7
- [ ] Panel web de administración
- [ ] Certificado de código (para evitar aviso "desconocido" en Windows)
