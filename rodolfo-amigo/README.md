# 👥 Rodolfo Amigo

Cliente liviano para que **tus amigos** controlen a Rodolfo por voz desde sus propias PCs.

Solo necesita:
- 🎤 Un micrófono
- 🌐 Internet
- 🐍 Python 3.10+

**NO** necesita:
- Token de Discord
- Acceso al VPS
- Whisper local
- Nada pesado

## Cómo funciona

1. El amigo dice *"Rodolfo pon despacito"* en su mic.
2. `amigo.py` transcribe con Google STT.
3. Envía el texto a Discord vía **webhook**.
4. El bot en Hetzner detecta el mensaje y reproduce.

## Setup (para el amigo)

1. Recibe la carpeta `rodolfo-amigo` del dueño del bot.
2. **Doble clic** en `instalar.bat` (solo la primera vez).
3. Abre `.env` con bloc de notas y rellena:
   - `DISCORD_WEBHOOK_URL` → te lo da el dueño del bot
   - `NOMBRE` → cómo quieres que aparezca en Discord
4. **Doble clic** en `iniciar.bat` cuando quieras usar Rodolfo.

Eso es todo. Habla en el mic con *"Rodolfo X"* y reproducirá música en el canal de voz donde esté el bot.
