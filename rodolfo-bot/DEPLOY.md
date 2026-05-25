# 🚀 Deploy de Rodolfo en Hetzner Cloud

Guía paso a paso para tener tu bot corriendo 24/7 en un VPS de Hetzner por ~€4/mes.

---

## 1. Crear el servidor en Hetzner

1. Crea cuenta en https://www.hetzner.com/cloud
2. Verifica con tarjeta (no te cobran hasta crear servidor)
3. Crea un nuevo proyecto → **Add Server**
4. Configuración:
   - **Location:** Falkenstein, Nuremberg o Helsinki (cualquiera, igual de rápido)
   - **Image:** `Ubuntu 22.04` o `Ubuntu 24.04`
   - **Type:** `CX22` (€4.59/mes, 2 vCPU 4GB RAM — recomendado)
     - Alternativa más barata: `CX11` (€3.79/mes, 1 vCPU 2GB) — funciona pero sin margen
   - **Networking:** IPv4 + IPv6 (default)
   - **SSH Key:** crea una nueva o sube la tuya (recomendado)
     - Si no sabes qué es: marca "Use a Password" y guárdalo
   - **Name:** `rodolfo-bot`
5. Clic en **Create & Buy now**
6. **Anota la IP pública** que te aparece (ej: `203.0.113.45`)

---

## 2. Conectarte al servidor

### Desde Windows (PowerShell):
```powershell
ssh root@TU_IP_AQUI
```

Si te pide contraseña, usa la que configuraste. Si configuraste SSH key, conecta directo.

---

## 3. Instalar Docker en el servidor

Una vez dentro, ejecuta:
```bash
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin git
```

Verifica:
```bash
docker --version
docker compose version
```

---

## 4. Subir el proyecto al servidor

### Opción A: via Git (recomendado, fácil de actualizar)
Si subes el proyecto a GitHub primero:
```bash
cd /opt
git clone https://github.com/TU_USUARIO/rodolfo.git
cd rodolfo/rodolfo-bot
```

### Opción B: via SCP (sin Git)
Desde tu PC Windows, en PowerShell:
```powershell
cd C:\Users\Lenovo\Desktop\ProyectoAudio
scp -r rodolfo-bot root@TU_IP:/opt/
```

Después en el servidor:
```bash
cd /opt/rodolfo-bot
```

---

## 5. Configurar `.env`

```bash
cp .env.example .env
nano .env
```

Rellena:
- `DISCORD_BOT_TOKEN` → token del bot
- `DISCORD_OWNER_USER_ID` → tu ID en Discord
- `DISCORD_GUILD_ID` → ID del servidor
- `DISCORD_WEBHOOK_URL` → webhook para los amigos
- `SPOTIFY_CLIENT_ID` / `SECRET` → si quieres Spotify
- `API_TOKEN` → genera uno aleatorio con:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  Cópialo. Lo necesitarás también en `rodolfo-host/.env`.

Guarda con `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## 6. Abrir el puerto 5000 (firewall de Hetzner)

En el panel de Hetzner → tu servidor → **Firewalls** → Create Firewall:
- Rule 1: SSH (port 22) — Source: tu IP (más seguro)
- Rule 2: Custom (port 5000) — Source: tu IP (solo tu PC se conecta al bot)

Aplica el firewall a `rodolfo-bot`.

> 💡 Si tu IP cambia (móvil/wifi diferente), puedes usar "Any IPv4/v6" pero **el token API es obligatorio**.

---

## 7. Arrancar el bot

```bash
docker compose up -d --build
```

La primera vez tarda 3-5 minutos (descarga Python, instala deps, baja Whisper).

Verifica que está corriendo:
```bash
docker compose logs -f
```

Deberías ver:
```
[BOT] Conectado como Rodolfo#2508
[BOT] Servidores: ['TU_SERVER']
[HTTP] API en 0.0.0.0:5000 (público, con auth)
```

Ctrl+C para salir de los logs (el bot sigue corriendo en background).

---

## 8. Conectar tu PC (rodolfo-host) al bot remoto

En tu PC, edita `rodolfo-host/.env`:
```env
MUSIC_BOT_URL=http://TU_IP_HETZNER:5000
API_TOKEN=el_mismo_token_que_pusiste_en_el_bot
```

Arranca `rodolfo-host/start.bat` y prueba.

---

## 9. Compartir con tus amigos

Mándales solo la carpeta `rodolfo-amigo` y el **webhook URL**. Ellos rellenan el `.env`, corren `instalar.bat` una vez, y luego `iniciar.bat` cuando quieran usar Rodolfo.

---

## 🛠 Comandos útiles del servidor

```bash
# Ver logs en tiempo real
docker compose logs -f

# Reiniciar el bot
docker compose restart

# Detener el bot
docker compose down

# Arrancar de nuevo
docker compose up -d

# Actualizar el código (si usas git)
cd /opt/rodolfo/rodolfo-bot
git pull
docker compose up -d --build
```

---

## 🔒 Seguridad

- **API_TOKEN**: nunca lo compartas. Cámbialo si crees que se filtró.
- **Firewall**: limita el puerto 5000 solo a tu IP si puedes.
- **Discord token**: tampoco lo compartas. Si se filtra, resetea en Discord Developer Portal.
- **Updates**: `apt update && apt upgrade` cada mes en el servidor.

---

## 💰 Costos esperados

| Concepto | Precio |
|---|---|
| Hetzner CX22 | €4.59 / mes |
| Tráfico | gratis hasta 20 TB/mes |
| **Total** | **~€4.59 ≈ $5 USD ≈ 18 soles** |

Eso es lo único que pagas. Discord, YouTube, Spotify, todo es gratis.
