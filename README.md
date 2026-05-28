# 🎙️ Rodolfo

Asistente de voz personal para controlar música en Discord, dispositivos de audio
y volumen del sistema. Tu PC + un bot 24/7 en la nube + amigos con cliente liviano.

## Arquitectura

```
                              ┌─────────────────────────┐
                              │   rodolfo-bot           │
                              │   (Hetzner Cloud)       │
                              │   ─────────────         │
                              │   Discord bot           │
                              │   HTTP API (con token)  │
                              │   Reproduce música      │
                              └────────┬────────────────┘
                                       │
                ┌──────────────────────┼──────────────────────┐
                │                      │                      │
                ▼                      ▼                      ▼
    ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
    │   rodolfo-host     │  │   rodolfo-amigo    │  │   rodolfo-amigo    │
    │   (tu PC)          │  │   (PC de Juan)     │  │   (PC de Ana)      │
    │   ────────────     │  │   ────────────     │  │   ────────────     │
    │   Voz + audio +    │  │   Solo voz         │  │   Solo voz         │
    │   volumen sistema  │  │   (via webhook)    │  │   (via webhook)    │
    └────────────────────┘  └────────────────────┘  └────────────────────┘
```

## Carpetas

| Carpeta | Dónde corre | Qué hace |
|---|---|---|
| **rodolfo-bot/** | Hetzner VPS (Docker) | Bot de Discord, reproduce música, expone API HTTP |
| **rodolfo-host/** | Tu PC (Windows) | Voz local + cambio dispositivos + volumen sistema |
| **rodolfo-amigo/** | PC de cada amigo | Cliente liviano que envía comandos al bot |

## Cómo empezar

1. **Crear el bot en Discord** (5 min) → ver instrucciones en `rodolfo-bot/.env.example`
2. **Deploy en Hetzner** → seguir paso a paso `rodolfo-bot/DEPLOY.md`
3. **Configurar tu PC** → ver `rodolfo-host/README.md`
4. **Compartir con amigos** → mandarles solo `rodolfo-amigo/` + webhook URL

## Stack

- **Bot:** Python 3.11 + py-cord + yt-dlp + edge-tts + Whisper + aiohttp + Docker
- **Host:** Python + Whisper local + Google STT + pygame + nircmd
- **Amigo:** Python + Google STT + requests (minimal)
- **Cloud:** Hetzner CX22 — €4.59/mes — 2 vCPU 4GB RAM
