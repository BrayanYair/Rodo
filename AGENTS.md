# Reglas del Proyecto Byarox

---

## VisiÃ³n del producto

Byarox es un **asistente de voz unificado** que se instala en cualquier PC.
La marca/app es **Byarox** y el asistente hablado se llama **Rodolfo**.
Detecta el contexto del usuario y enruta cada comando al mÃ³dulo correcto,
sin que el usuario tenga que pensar en quÃ© herramienta usar.

---

## Componentes del sistema

### `rodolfo-amigo/` â€” El cliente (Rodo.exe)
Lo que instala **cualquier usuario** (vos, amigos, clientes).
- Escucha el micrÃ³fono y detecta el activador "oye rodo"
- Transcribe con Google STT
- Consulta el contexto al bot (Â¿estoy en Discord?)
- Enruta el comando al mÃ³dulo correcto via `orchestrator.py`
- Muestra overlay visual de estado
- Ãcono en la bandeja del sistema
- Se compila con PyInstaller â†’ `Rodo.exe`
- Se actualiza automÃ¡ticamente desde GitHub Releases

#### `rodolfo-amigo/orchestrator.py` â€” Orquestador central
Singleton que centraliza estado de sesiÃ³n y decisiones de routing.
- `OrchestratorState`: estado mutable (discord_mode, spotify_token, voice_channel, etc.)
  - Soporta acceso tipo dict (`state["discord_mode"]`) para retrocompatibilidad con `_session`
- `RodoOrchestrator.decide()`: reglas determinÃ­sticas de routing â†’ `Action`
  - Punto de extensiÃ³n para IA futura (reemplazar con `decide_ai()` que llame Codex API)
  - `state.as_dict()` ya preparado como contexto para el LLM
- `on_enter_voice()` / `on_exit_voice()`: resetean `discord_mode` automÃ¡ticamente
- `search_personal_library()`: busca en playlists y Ã¡lbumes guardados del usuario (OAuth)

### `rodolfo-bot/` â€” El servidor compartido
Corre en **una sola PC** (la tuya o un VPS). Sirve a todos los usuarios.
- Bot de Discord: reproduce mÃºsica en canales de voz
- API interna (aiohttp): recibe comandos de todos los clientes
- BÃºsqueda: Spotify refina el texto â†’ YouTube reproduce el audio
- TTS en el canal de voz de Discord
- Sistema de tokens por usuario (`tokens.py` + `tokens.json`)
- OAuth Spotify personal por usuario (tokens guardados en `tokens.json`)

### `rodolfo-host/` â€” El motor local (en desarrollo, fusiÃ³n futura con amigo)
Capacidades avanzadas que corren **en la PC del usuario**:
- Control de audio de Windows (volumen, dispositivos de salida)
- ReproducciÃ³n local vÃ­a Spotify Premium (Spotify API OAuth)
- TTS local por los parlantes del usuario
- Control de dispositivos Spotify (celular, parlantes, PC)

---

## Arquitectura de contexto

Cuando Byarox recibe un comando de mÃºsica, decide a dÃ³nde enviarlo:

```
"Oye Rodo pon flaca"
        â”‚
        â–¼
  [Orquestador] orchestrator.decide()
  Â¿discord_mode es True / False / None?
        â”‚
   True  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â†’ bot Discord (reproduce en canal de voz)
   False â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â†’ modo local (Spotify URI o YouTube)
   None  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â†’ Pregunta UNA VEZ: "Â¿Discord o local?"
                              SÃ Discord â†’ bot entra, reproduce en Discord
                              NO â†’ reproduce en local
```

### Reglas de contexto
- **ImplÃ­cito**: Byarox detecta Discord (vÃ­a RPC o polling `/context`) y pregunta una vez.
- **ExplÃ­cito**: Si el usuario especifica el destino, Rodolfo ejecuta directo.
  - *"Oye Rodo entra a Discord"* â†’ `discord_mode = True`
  - *"Oye Rodo pon X en mis parlantes"* â†’ `discord_mode = False`
  - *"Oye Rodo cambia al celular"* â†’ Spotify transfiere al mÃ³vil
- **Memoria de sesiÃ³n**: Una vez elegido el modo, Byarox lo recuerda hasta que el usuario cambie o se cierre.
- **Reset automÃ¡tico**: Si el usuario sale de un canal de Discord â†’ `discord_mode = False`.  
  Si vuelve a entrar â†’ `discord_mode = None` (vuelve a preguntar).

---

## Flujo de reproducciÃ³n local

```
"Oye Rodo pon mi Ã¡lbum 365"
        â”‚
        â–¼
  [amigo.py] discord_mode is False â†’ modo local
        â”‚
        â–¼
  1. Â¿Usuario tiene Spotify OAuth vinculado? (orchestrator.has_spotify)
     SÃ â†’ search_personal_library("365", spotify_type="album")
          Busca en playlists + Ã¡lbumes guardados del usuario
          Si score â‰¥ 0.5 â†’ abre Spotify URI directamente âœ“
     NO â†’ continÃºa al paso 2
        â”‚
        â–¼
  2. Busca en Spotify pÃºblico (api.py â†’ /command?local=true)
     album/playlist â†’ sp.search(type="album,playlist") con scoring
     artist â†’ sp.search(type="artist")
     track â†’ sp.search(type="track")
     Si URI encontrado â†’ cliente abre URI en Spotify âœ“
        â”‚
        â–¼
  3. Fallback: YouTube (abre en navegador)
```

---

## Flujo OAuth Spotify personal

```
"Oye Rodo vincula mi Spotify"
        â”‚
        â–¼
  [amigo.py] â†’ detecta intent "link_spotify" â†’ abre /spotify/login en bot
        â”‚
        â–¼
  [bot] GET /spotify/login?user_token=<token_rodo>
        â†’ redirige a Spotify OAuth
        â†’ callback en /spotify/callback?state=<username_key>
        â†’ guarda {access_token, refresh_token, expires_at} en tokens.json bajo el usuario
        â”‚
        â–¼
  [bot] devuelve pÃ¡gina HTML de confirmaciÃ³n
        â”‚
        â–¼
  [amigo.py] â†’ carga token de la API (/me/spotify_status)
             â†’ orchestrator.set_spotify_token(access_token)
             â†’ TTS: "Spotify vinculado"
```

### Claves especiales en tokens.json
- Usuarios normales: `{"token": "...", "name": "...", "active": true, "spotify": {...}}`
- DueÃ±o del bot (master token): clave `"owner"` â€” se crea automÃ¡ticamente al vincular Spotify
  - `auth_user_key=None` en la API â†’ se usa `"owner"` como clave de lookup

---

## CÃ³mo agregar una nueva herramienta o habilidad

Cada nueva capacidad de Rodo sigue este patrÃ³n:

### 1. Definir el mÃ³dulo
Crear (o usar) una carpeta en `rodolfo-bot/modules/` o una clase en `rodolfo-host/`:
```
rodolfo-bot/modules/
    music/      â† ya existe: bÃºsqueda + reproducciÃ³n Discord
    spotify/    â† prÃ³ximo: control Spotify Premium local
    devices/    â† futuro: dispositivos de audio Windows
```

### 2. Exponer la acciÃ³n en la API del bot
Agregar un endpoint en `rodolfo-bot/api.py`:
```python
@app.post("/nombre_accion")
async def nombre_accion(data: dict, ...):
    ...
```

### 3. Registrar el comando en el parser
Agregar la detecciÃ³n en `rodolfo-bot/command_parser.py`:
```python
if any(w in cmd for w in ["palabra_clave", "variante"]):
    return {"action": "nombre_accion", "param": ...}
```

### 4. Manejar la acciÃ³n en el cliente
En `rodolfo-amigo/amigo.py`, el cliente ya envÃ­a todo al bot vÃ­a `/command`.
Si la acciÃ³n requiere lÃ³gica local (overlay, TTS local, etc.), agregarla antes del envÃ­o.

### 5. Documentar aquÃ­
Agregar la herramienta en la secciÃ³n de componentes y en los pendientes.

---

## Reglas para Codex

1. **Nunca subir versiones sin permiso explÃ­cito.**
   - No cambiar `version.py` ni `version.json` sin que el usuario lo pida.
   - No crear releases ni ejecutar `actualizar_release.ps1` sin autorizaciÃ³n.

2. **El activador de voz principal es "oye rodo".**
   - `ACTIVATOR_NAMES = ("oye rodo", "rodo", "oye rodolfo", "rodolfo")`.
   - No volver a `rodo` ni usar la marca `byarox` como activador sin pedirlo.

3. **No hacer commits automÃ¡ticos.**
   - Solo commitear cuando el usuario lo pida explÃ­citamente.

4. **Antes de cualquier cambio grande, confirmar el plan.**
   - Si el cambio toca mÃ¡s de 2 archivos o cambia comportamiento visible, describir quÃ© se va a hacer antes de hacerlo.

5. **Mantener retrocompatibilidad.**
   - `config.json` ya estÃ¡ en las PCs de los amigos. No cambiar sus campos sin migraciÃ³n.

6. **Respetar el enrutamiento por contexto.**
   - Nunca hardcodear un destino (Discord o local). Siempre pasar por la lÃ³gica de contexto.

---

## Stack tÃ©cnico

| Componente | Stack |
|---|---|
| Cliente (`rodolfo-amigo`) | Python + SpeechRecognition + Google STT + pystray + tkinter + PyInstaller |
| Orquestador (`orchestrator.py`) | Python puro â€” sin dependencias externas; listo para Codex API |
| Servidor (`rodolfo-bot`) | Python + discord.py + yt-dlp + edge-tts + spotipy + aiohttp + ngrok |
| Motor local (`rodolfo-host`) | Python + pygame + nircmd + spotipy OAuth + edge-tts |
| STT | Google STT (principal) â€” Whisper local (futuro fallback) |
| MÃºsica | Spotify busca metadata â†’ YouTube reproduce audio |
| Spotify personal | spotipy OAuth â€” playlists y Ã¡lbumes del usuario |
| Tokens | `tokens.json` â€” un token por usuario, Spotify tokens embebidos |
| ExtracciÃ³n del exe | `AppData\Local\Rodo\` (estable entre actualizaciones) |

---

## Flujo de una actualizaciÃ³n

1. Hacer los cambios en el cÃ³digo.
2. Pedir permiso para subir versiÃ³n.
3. Actualizar `version.py` y `version.json` con la nueva versiÃ³n y changelog.
4. Compilar: `pyinstaller rodo.spec --noconfirm` (en `rodolfo-amigo/`).
5. Commit + push.
6. Ejecutar `actualizar_release.ps1 -Token "..." -Tag "vX.Y.Z" -Notes "..."`.
7. Los usuarios reciben la actualizaciÃ³n automÃ¡ticamente al abrir Rodo.

---

## Pendientes (en orden de prioridad)

### Arquitectura
- [x] Orquestador central (`orchestrator.py`) con estado de sesiÃ³n y routing
- [x] LÃ³gica de contexto en `rodolfo-amigo`: preguntar una vez, recordar por sesiÃ³n
- [x] Reset de `discord_mode` al salir/entrar de canal de Discord
- [ ] FusiÃ³n de `rodolfo-host` en `rodolfo-amigo` (un solo exe con todas las capacidades)
- [ ] Integrar `orchestrator.decide()` con lÃ³gica LLM (Codex API) como reemplazo de reglas

### Spotify personal
- [x] OAuth flow completo: vinculaciÃ³n por voz ("Oye Rodo vincula mi Spotify")
- [x] BÃºsqueda en biblioteca personal (playlists + Ã¡lbumes guardados)
- [x] Soporte multi-usuario: cada amigo vincula su propio Spotify
- [ ] Cambio de dispositivo Spotify por voz ("Oye Rodo cambia al celular")
- [ ] Listar dispositivos de salida por voz ("Oye Rodo quÃ© dispositivos tengo")

### MÃºsica Discord
- [ ] Ver cola en Discord
- [ ] Letras de canciones

### Asistente
- [ ] Control de volumen de Windows por voz
- [ ] Whisper local (STT sin internet)

### Infraestructura
- [ ] Auto-restart del bot si se cae
- [ ] Hosting VPS 24/7
- [ ] Panel web de administraciÃ³n
- [ ] Certificado de cÃ³digo (para evitar aviso "desconocido" en Windows)
