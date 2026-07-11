# Byarox

Byarox es un asistente de voz personal para controlar musica en Discord, YouTube/Spotify y, mas adelante, dispositivos del hogar.

- Marca/app: **Byarox**
- Asistente hablado: **Rodolfo**
- Activador principal: **"Oye Rodo"**

Ejemplo:

```text
Oye Rodo, pon despacito
```

## Arquitectura

| Carpeta | Donde corre | Que hace |
|---|---|---|
| **rodolfo-bot/** | VPS o PC servidor | Bot de Discord, reproduce musica y expone API HTTP |
| **rodolfo-amigo/** | PC de cada usuario | Cliente de voz, overlay, contexto Discord/local y envio de comandos |
| **rodolfo-host/** | PC del usuario | Motor local experimental para volumen, dispositivos y Spotify local |

## Como empezar

1. Crear/configurar el bot de Discord en `rodolfo-bot/`.
2. Configurar el cliente en `rodolfo-amigo/`.
3. Probar comandos con `Oye Rodo`.
4. Vincular Spotify diciendo: `Oye Rodo, vincula mi Spotify`.

## Nota de nombres

Las carpetas siguen llamandose `rodolfo-*` por compatibilidad historica. El producto para usuarios es **Byarox** y la voz/persona del asistente es **Rodolfo**.
