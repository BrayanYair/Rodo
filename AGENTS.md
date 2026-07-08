# Reglas del Proyecto Byarox

---

## Visión del producto

Byarox es un **asistente de voz unificado** que se instala en cualquier PC.
La marca/app es **Byarox** y el asistente hablado se llama **Rodolfo**.
Detecta el contexto del usuario y enruta cada comando al módulo correcto,
sin que el usuario tenga que pensar en qué herramienta usar.

---

## Componentes del sistema

### `rodolfo-amigo/` — El cliente (Rodo.exe)
Lo que instala **cualquier usuario** (vos, amigos, clientes).
- Escucha el micrófono y detecta el activador "oye rodolfo"
- Transcribe con Google STT
- Consulta el contexto al bot (¿estoy en Discord?)
- Enruta el comando al módulo correcto via `orchestrator.py`
- Muestra overlay visual de estado
- Ícono en la bandeja del sistema
- Se compila con PyInstaller → `Rodo.exe`
- Se actualiza automáticamente desde GitHub Releases

#### `rodolfo-amigo/orchestrator.py` — Orquestador central
Singleton que centraliza estado de sesión y decisiones de routing.
- `OrchestratorState`: estado mutable (discord_mode, spotify_token, voice_channel, etc.)
  - Soporta acceso tipo dict (`state["discord_mode"]`) para retrocompatibilidad con `_session`
- `RodoOrchestrator.decide()`: reglas determinísticas de routing → `Action`
  - Punto de extensión para IA futura (reemplazar con `decide_ai()` que llame Codex API)
  - `state.as_dict()` ya preparado como contexto para el LLM
- `on_enter_voice()` / `on_exit_voice()`: resetean `discord_mode` automáticamente
- `search_personal_library()`: busca en playlists y álbumes guardados del usuario (OAuth)

### `rodolfo-bot/` — El servidor compartido
Corre en **una sola PC** (la tuya o un VPS). Sirve a todos los usuarios.
- Bot de Discord: reproduce música en canales de voz
- API interna (aiohttp): recibe comandos de todos los clientes
- Búsqueda: Spotify refina el texto → YouTube reproduce el audio
- TTS en el canal de voz de Discord
- Sistema de tokens por usuario (`tokens.py` + `tokens.json`)
- OAuth Spotify personal por usuario (tokens guardados en `tokens.json`)

### `rodolfo-host/` — El motor local (en desarrollo, fusión futura con amigo)
Capacidades avanzadas que corren **en la PC del usuario**:
- Control de audio de Windows (volumen, dispositivos de salida)
- Reproducción local vía Spotify Premium (Spotify API OAuth)
- TTS local por los parlantes del usuario
- Control de dispositivos Spotify (celular, parlantes, PC)

---

## Arquitectura de contexto

Cuando Byarox recibe un comando de música, decide a dónde enviarlo:

```
"Oye Rodolfo pon flaca"
        │
        ▼
  [Orquestador] orchestrator.decide()
  ¿discord_mode es True / False / None?
        │
   True  ──────────────→ bot Discord (reproduce en canal de voz)
   False ──────────────→ modo local (Spotify URI o YouTube)
   None  ──────────────→ Pregunta UNA VEZ: "¿Discord o local?"
                              SÍ Discord → bot entra, reproduce en Discord
                              NO → reproduce en local
```

### Reglas de contexto
- **Implícito**: Byarox detecta Discord (vía RPC o polling `/context`) y pregunta una vez.
- **Explícito**: Si el usuario especifica el destino, Rodolfo ejecuta directo.
  - *"Oye Rodolfo entra a Discord"* → `discord_mode = True`
  - *"Oye Rodolfo pon X en mis parlantes"* → `discord_mode = False`
  - *"Oye Rodolfo cambia al celular"* → Spotify transfiere al móvil
- **Memoria de sesión**: Una vez elegido el modo, Byarox lo recuerda hasta que el usuario cambie o se cierre.
- **Reset automático**: Si el usuario sale de un canal de Discord → `discord_mode = False`.  
  Si vuelve a entrar → `discord_mode = None` (vuelve a preguntar).

---

## Flujo de reproducción local

```
"Oye Rodolfo pon mi álbum 365"
        │
        ▼
  [amigo.py] discord_mode is False → modo local
        │
        ▼
  1. ¿Usuario tiene Spotify OAuth vinculado? (orchestrator.has_spotify)
     SÍ → search_personal_library("365", spotify_type="album")
          Busca en playlists + álbumes guardados del usuario
          Si score ≥ 0.5 → abre Spotify URI directamente ✓
     NO → continúa al paso 2
        │
        ▼
  2. Busca en Spotify público (api.py → /command?local=true)
     album/playlist → sp.search(type="album,playlist") con scoring
     artist → sp.search(type="artist")
     track → sp.search(type="track")
     Si URI encontrado → cliente abre URI en Spotify ✓
        │
        ▼
  3. Fallback: YouTube (abre en navegador)
```

---

## Flujo OAuth Spotify personal

```
"Oye Rodolfo vincula mi Spotify"
        │
        ▼
  [amigo.py] → detecta intent "link_spotify" → abre /spotify/login en bot
        │
        ▼
  [bot] GET /spotify/login?user_token=<token_rodo>
        → redirige a Spotify OAuth
        → callback en /spotify/callback?state=<username_key>
        → guarda {access_token, refresh_token, expires_at} en tokens.json bajo el usuario
        │
        ▼
  [bot] devuelve página HTML de confirmación
        │
        ▼
  [amigo.py] → carga token de la API (/me/spotify_status)
             → orchestrator.set_spotify_token(access_token)
             → TTS: "Spotify vinculado"
```

### Claves especiales en tokens.json
- Usuarios normales: `{"token": "...", "name": "...", "active": true, "spotify": {...}}`
- Dueño del bot (master token): clave `"owner"` — se crea automáticamente al vincular Spotify
  - `auth_user_key=None` en la API → se usa `"owner"` como clave de lookup

---

## Cómo agregar una nueva herramienta o habilidad

Cada nueva capacidad de Rodo sigue este patrón:

### 1. Definir el módulo
Crear (o usar) una carpeta en `rodolfo-bot/modules/` o una clase en `rodolfo-host/`:
```
rodolfo-bot/modules/
    music/      ← ya existe: búsqueda + reproducción Discord
    spotify/    ← próximo: control Spotify Premium local
    devices/    ← futuro: dispositivos de audio Windows
```

### 2. Exponer la acción en la API del bot
Agregar un endpoint en `rodolfo-bot/api.py`:
```python
@app.post("/nombre_accion")
async def nombre_accion(data: dict, ...):
    ...
```

### 3. Registrar el comando en el parser
Agregar la detección en `rodolfo-bot/command_parser.py`:
```python
if any(w in cmd for w in ["palabra_clave", "variante"]):
    return {"action": "nombre_accion", "param": ...}
```

### 4. Manejar la acción en el cliente
En `rodolfo-amigo/amigo.py`, el cliente ya envía todo al bot vía `/command`.
Si la acción requiere lógica local (overlay, TTS local, etc.), agregarla antes del envío.

### 5. Documentar aquí
Agregar la herramienta en la sección de componentes y en los pendientes.

---

## Reglas para Codex

1. **Nunca subir versiones sin permiso explícito.**
   - No cambiar `version.py` ni `version.json` sin que el usuario lo pida.
   - No crear releases ni ejecutar `actualizar_release.ps1` sin autorización.

2. **El activador de voz principal es "oye rodolfo".**
   - `ACTIVATOR_NAMES = ("oye rodolfo", "rodolfo")`.
   - No volver a `rodo` ni usar la marca `byarox` como activador sin pedirlo.

3. **No hacer commits automáticos.**
   - Solo commitear cuando el usuario lo pida explícitamente.

4. **Antes de cualquier cambio grande, confirmar el plan.**
   - Si el cambio toca más de 2 archivos o cambia comportamiento visible, describir qué se va a hacer antes de hacerlo.

5. **Mantener retrocompatibilidad.**
   - `config.json` ya está en las PCs de los amigos. No cambiar sus campos sin migración.

6. **Respetar el enrutamiento por contexto.**
   - Nunca hardcodear un destino (Discord o local). Siempre pasar por la lógica de contexto.

---

## Stack técnico

| Componente | Stack |
|---|---|
| Cliente (`rodolfo-amigo`) | Python + SpeechRecognition + Google STT + pystray + tkinter + PyInstaller |
| Orquestador (`orchestrator.py`) | Python puro — sin dependencias externas; listo para Codex API |
| Servidor (`rodolfo-bot`) | Python + discord.py + yt-dlp + edge-tts + spotipy + aiohttp + ngrok |
| Motor local (`rodolfo-host`) | Python + pygame + nircmd + spotipy OAuth + edge-tts |
| STT | Google STT (principal) — Whisper local (futuro fallback) |
| Música | Spotify busca metadata → YouTube reproduce audio |
| Spotify personal | spotipy OAuth — playlists y álbumes del usuario |
| Tokens | `tokens.json` — un token por usuario, Spotify tokens embebidos |
| Extracción del exe | `AppData\Local\Rodo\` (estable entre actualizaciones) |

---

## Flujo de una actualización

1. Hacer los cambios en el código.
2. Pedir permiso para subir versión.
3. Actualizar `version.py` y `version.json` con la nueva versión y changelog.
4. Compilar: `pyinstaller rodo.spec --noconfirm` (en `rodolfo-amigo/`).
5. Commit + push.
6. Ejecutar `actualizar_release.ps1 -Token "..." -Tag "vX.Y.Z" -Notes "..."`.
7. Los usuarios reciben la actualización automáticamente al abrir Rodo.

---

## Pendientes (en orden de prioridad)

### Arquitectura
- [x] Orquestador central (`orchestrator.py`) con estado de sesión y routing
- [x] Lógica de contexto en `rodolfo-amigo`: preguntar una vez, recordar por sesión
- [x] Reset de `discord_mode` al salir/entrar de canal de Discord
- [ ] Fusión de `rodolfo-host` en `rodolfo-amigo` (un solo exe con todas las capacidades)
- [ ] Integrar `orchestrator.decide()` con lógica LLM (Codex API) como reemplazo de reglas

### Spotify personal
- [x] OAuth flow completo: vinculación por voz ("Oye Rodolfo vincula mi Spotify")
- [x] Búsqueda en biblioteca personal (playlists + álbumes guardados)
- [x] Soporte multi-usuario: cada amigo vincula su propio Spotify
- [ ] Cambio de dispositivo Spotify por voz ("Oye Rodolfo cambia al celular")
- [ ] Listar dispositivos de salida por voz ("Oye Rodolfo qué dispositivos tengo")

### Música Discord
- [ ] Ver cola en Discord
- [ ] Letras de canciones

### Asistente
- [ ] Control de volumen de Windows por voz
- [ ] Whisper local (STT sin internet)

### Infraestructura
- [ ] Auto-restart del bot si se cae
- [ ] Hosting VPS 24/7
- [ ] Panel web de administración
- [ ] Certificado de código (para evitar aviso "desconocido" en Windows)
