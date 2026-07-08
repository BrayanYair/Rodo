# 🏠 Rodolfo Host

El controlador que corre en **tu PC** (Windows). Maneja:
- Mic local + transcripción
- Cambio de dispositivos de audio del sistema
- Volumen del sistema
- Se conecta al `rodolfo-bot` que corre en Hetzner

## Setup rápido

1. Asegúrate de tener Python 3.11+ y ffmpeg en el PATH.
2. Instala dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
3. Copia `.env.example` a `.env` y rellena:
   - `MUSIC_BOT_URL` → IP de tu VPS de Hetzner (ej: `http://203.0.113.45:5000`)
   - `API_TOKEN` → el mismo token que pusiste en `rodolfo-bot/.env`
4. Arranca:
   ```
   doble clic en start.bat
   ```

## Comandos de voz

| Categoría | Ejemplos |
|---|---|
| Música | *"Oye Rodolfo pon despacito"*, *"Oye Rodolfo siguiente"*, *"Oye Rodolfo pausa"* |
| Volumen | *"Oye Rodolfo sube el volumen"*, *"Oye Rodolfo silencio"* |
| Dispositivos | *"Oye Rodolfo mostrar dispositivos"*, *"Oye Rodolfo cambia a auriculares"* |
| Cola | *"Oye Rodolfo después pon X"*, *"Oye Rodolfo limpia la cola"* |
| Info | *"Oye Rodolfo qué está sonando"* |
