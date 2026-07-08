# actualizar_release.ps1
# Crea un nuevo release en GitHub y sube Byarox.exe
#
# Requiere: GitHub Personal Access Token con permisos repo
# Para crearlo: https://github.com/settings/tokens -> New classic token -> marcar "repo"
#
# Uso: .\actualizar_release.ps1 -Token "ghp_xxxx"
#      .\actualizar_release.ps1 -Token "ghp_xxxx" -Tag "v1.0.2" -Notes "Descripcion del cambio"

param(
    [Parameter(Mandatory=$true)]
    [string]$Token,
    [string]$Tag   = "v1.0.12",
    [string]$Notes = "- Activador actualizado a Oye Rodolfo; respuesta mas rapida; pitido desactivado por defecto; menos falsos positivos."
)

$OWNER   = "BrayanYair"
$REPO    = "Rodo"
$EXE     = "C:\Users\Lenovo\Desktop\ProyectoAudio\rodolfo-amigo\dist\Byarox.exe"
$HEADERS = @{ Authorization = "token $Token"; Accept = "application/vnd.github.v3+json" }

if (-not (Test-Path $EXE)) {
    Write-Error "No se encontro Byarox.exe en $EXE"
    exit 1
}

Write-Host "=== Publicando Release $Tag en $OWNER/$REPO ===" -ForegroundColor Cyan

# 1. Verificar que no exista ya el tag
Write-Host "[1/4] Verificando si el release $Tag ya existe..."
try {
    $existing = Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/releases/tags/$Tag" `
        -Headers $HEADERS -Method Get -ErrorAction Stop
    # Si existe, eliminar asset viejo y re-subir
    Write-Host "      Release ya existe (ID: $($existing.id)), reemplazando Byarox.exe..."
    $oldAsset = $existing.assets | Where-Object { $_.name -eq "Byarox.exe" }
    if ($oldAsset) {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/releases/assets/$($oldAsset.id)" `
            -Headers $HEADERS -Method Delete | Out-Null
        Write-Host "      Asset anterior eliminado." -ForegroundColor Yellow
    }
    $releaseId = $existing.id
} catch {
    # No existe — crear release nuevo
    Write-Host "      Creando nuevo release $Tag..."
    $body = @{
        tag_name   = $Tag
        name       = "Byarox $Tag"
        body       = $Notes
        draft      = $false
        prerelease = $false
    } | ConvertTo-Json

    $release   = Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/releases" `
        -Headers $HEADERS -Method Post -Body $body -ContentType "application/json" -ErrorAction Stop
    $releaseId = $release.id
    Write-Host "      Release creado (ID: $releaseId)" -ForegroundColor Green
}

# 2. Subir Byarox.exe
Write-Host "[2/4] Subiendo Byarox.exe ($('{0:N1}' -f ((Get-Item $EXE).Length / 1MB)) MB)..."
$uploadUrl     = "https://uploads.github.com/repos/$OWNER/$REPO/releases/$releaseId/assets?name=Byarox.exe"
$uploadHeaders = $HEADERS + @{ "Content-Type" = "application/octet-stream" }
$bytes         = [System.IO.File]::ReadAllBytes($EXE)
$response      = Invoke-RestMethod -Uri $uploadUrl -Headers $uploadHeaders -Method Post -Body $bytes
Write-Host "      Subido OK" -ForegroundColor Green

# 3. Listo
Write-Host ""
Write-Host "[4/4] Listo!" -ForegroundColor Green
Write-Host ""
Write-Host "  Release : https://github.com/$OWNER/$REPO/releases/tag/$Tag"
Write-Host "  Descarga: $($response.browser_download_url)"
Write-Host ""
Write-Host "  Los usuarios con Rodo abierto recibiran la actualizacion automaticamente." -ForegroundColor Cyan
Write-Host ""
