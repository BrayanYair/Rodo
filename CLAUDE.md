# Reglas del Proyecto Rodo

## Estructura del proyecto

| Carpeta | Qué es |
|---|---|
| `rodolfo-amigo/` | El **cliente** — el `.exe` que corre en la PC de cada amigo. Escucha el micrófono, detecta "Rodo", y manda el comando al servidor. |
| `rodolfo-bot/` | El **servidor** — el bot de Discord que corre en tu PC (o VPS). Recibe comandos, busca música, reproduce en el canal de voz. |

## Reglas para Claude

1. **Nunca subir versiones sin permiso explícito.**
   - No cambiar `version.py` ni `version.json` sin que el usuario lo pida.
   - No crear releases ni ejecutar `actualizar_release.ps1` sin autorización.

2. **El activador de voz es solo "rodo".**
   - `ACTIVATOR_NAMES = ("rodo",)` — no agregar "rodolfo", "jarvis", "asistente", "bot" ni ningún otro sin pedirlo.

3. **No hacer commits automáticos.**
   - Solo commitear cuando el usuario lo pida explícitamente.

4. **Antes de cualquier cambio grande, confirmar el plan.**
   - Si el cambio toca más de 2 archivos o cambia comportamiento visible, describir qué se va a hacer antes de hacerlo.

5. **Mantener retrocompatibilidad.**
   - `config.json` ya está en las PCs de los amigos. No cambiar sus campos sin migración.

## Stack técnico

- **Cliente (`rodolfo-amigo`)**: Python + SpeechRecognition + Google STT + pystray + tkinter. Se compila con PyInstaller (`rodo.spec`). Extrae a `AppData\Local\Rodo\`.
- **Servidor (`rodolfo-bot`)**: Python + discord.py + yt-dlp + edge-tts + spotipy + FastAPI (API interna). Corre con `lanzar.py` que levanta ngrok.
- **Voz**: activador "rodo" → Google STT → API del bot → yt-dlp busca en YouTube.
- **Música**: Spotify refina el texto → YouTube reproduce el audio.

## Flujo de una actualización

1. Hacer los cambios en el código.
2. Pedir permiso para subir versión.
3. Actualizar `version.py` y `version.json` con la nueva versión y changelog.
4. Compilar: `pyinstaller rodo.spec --noconfirm` (en `rodolfo-amigo/`).
5. Commit + push.
6. Ejecutar `actualizar_release.ps1 -Token "..." -Tag "vX.Y.Z" -Notes "..."`.
7. Los usuarios reciben la actualización automáticamente al abrir Rodo.

## Pendientes (en orden de prioridad)

- [ ] Reproducción local desde Spotify Premium (control de la app de Spotify vía OAuth)
- [ ] Auto-restart del bot si se cae
- [ ] Control de volumen por voz
- [ ] Ver cola en Discord
- [ ] Whisper local (STT sin internet)
- [ ] Panel web de administración
- [ ] Hosting VPS 24/7
- [ ] Certificado de código (para evitar aviso "desconocido" en Windows)
