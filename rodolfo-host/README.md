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
| Música | *"Oye Rodo pon despacito"*, *"Oye Rodo siguiente"*, *"Oye Rodo pausa"* |
| Volumen | *"Oye Rodo sube el volumen"*, *"Oye Rodo silencio"* |
| Dispositivos | *"Oye Rodo mostrar dispositivos"*, *"Oye Rodo cambia a auriculares"* |
| Cola | *"Oye Rodo después pon X"*, *"Oye Rodo limpia la cola"* |
| Info | *"Oye Rodo qué está sonando"* |
