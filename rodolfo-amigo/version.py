# version.py — Versión actual de Rodo
#
# Para lanzar una actualización:
#   1. Sube el número aquí  (ej: "1.0.0" → "1.0.1")
#   2. Actualiza version.json en el repo con la misma versión + URL de descarga
#   3. Sube el Rodo.exe nuevo a GitHub Releases
#   4. Haz git push → los usuarios lo reciben automáticamente al abrir Rodo

VERSION = "1.0.8"

# URL del archivo que tiene la versión más reciente (GitHub raw — siempre actualizado)
UPDATE_CHECK_URL = (
    "https://raw.githubusercontent.com/BrayanYair/Rodo/main"
    "/rodolfo-amigo/version.json"
)
