# Byarox Amigo

Cliente liviano para que cualquier usuario controle Byarox por voz desde su PC.

El usuario le habla al asistente como **Rodolfo**:

```text
Oye Rodo, pon despacito
```

## Como funciona

1. El usuario dice `Oye Rodo` mas el comando.
2. `amigo.py` transcribe con Google STT.
3. El orquestador decide si el comando va a Discord o al modo local.
4. El bot/cliente reproduce la musica donde corresponda.

## Setup

1. Ejecutar `instalar.bat` o `instalar.pyw` la primera vez.
2. Completar la configuracion del servidor y nombre de usuario.
3. Abrir `Rodo.bat` o el ejecutable generado.
4. Probar: `Oye Rodo, pon una cancion`.

## Nota

La carpeta y algunos scripts conservan el nombre `Rodo` por compatibilidad. La marca/app es **Byarox**.
