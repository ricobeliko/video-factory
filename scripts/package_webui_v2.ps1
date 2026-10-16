<#
.SYNOPSIS
    Gera o pacote de distribuição autônomo da Web UI V2 para deploy sem Node.js em produção.
.DESCRIPTION
    Compila o frontend (opcional via -Rebuild), empacota o build estático (webui-v2/dist),
    gera o manifesto com hashes SHA-256 e guia de instalação, criando o arquivo ZIP
    em 'releases/' com validação automática de integridade.
#>

[CmdletBinding()]
param(
    [switch]$Rebuild,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

# 1. Resolução do Diretório Raiz
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Resolução do Git Commit SHA
$GitSha = (git -C $ProjectRoot rev-parse HEAD).Trim()
$ShortSha = (git -C $ProjectRoot rev-parse --short HEAD).Trim()
$GeneratedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Video Factory - Web UI V2 Release Packager" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Commit Git   : $GitSha ($ShortSha)"
Write-Host "Data/Hora    : $GeneratedAt"

# 3. Build do Frontend se Solicitado ou Ausente
$WebUiDir = Join-Path $ProjectRoot "webui-v2"
$DistDir = Join-Path $WebUiDir "dist"
$DistIndex = Join-Path $DistDir "index.html"

if ($Rebuild -or (-not (Test-Path $DistIndex))) {
    Write-Host "`n[1/5] Compilando frontend React/Vite (npm run build)..." -ForegroundColor Yellow
    Push-Location $WebUiDir
    try {
        npm run build
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $DistIndex)) {
            Write-Error "Falha ao compilar o frontend com npm run build."
            exit 1
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[1/5] Utilizando build existente em '$DistDir'." -ForegroundColor Green
}

# 4. Preparação do Diretório de Saída e Staging
if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot "releases"
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$TempStage = Join-Path $OutputDir "stage_webui_v2_$ShortSha"
if (Test-Path $TempStage) {
    Remove-Item -Path $TempStage -Recurse -Force
}
New-Item -ItemType Directory -Path $TempStage -Force | Out-Null

$StageDist = Join-Path $TempStage "dist"
Copy-Item -Path $DistDir -Destination $StageDist -Recurse -Force

# 5. Cálculo dos Hashes e Geração do Manifesto
Write-Host "[2/5] Calculando hashes SHA-256 dos artefatos compilados..." -ForegroundColor Yellow

$DistFiles = Get-ChildItem -Path $StageDist -Recurse -File
$ManifestFiles = [ordered]@{}

foreach ($File in $DistFiles) {
    $RelativePath = "dist/" + ($File.FullName.Substring($StageDist.Length).TrimStart('\', '/')).Replace('\', '/')
    $Hash = (Get-FileHash -Path $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $ManifestFiles[$RelativePath] = [ordered]@{
        "size_bytes" = $File.Length
        "sha256" = $Hash
    }
}

$Manifest = [ordered]@{
    "package" = "webui-v2-dist"
    "git_commit" = $GitSha
    "git_short_sha" = $ShortSha
    "generated_at" = $GeneratedAt
    "file_count" = $DistFiles.Count
    "files" = $ManifestFiles
}

$ManifestPath = Join-Path $TempStage "manifest.json"
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.Encoding]::UTF8)

# 6. Geração do INSTALL.md no Pacote
Write-Host "[3/5] Gerando instruções de instalação (INSTALL.md)..." -ForegroundColor Yellow

$InstallDoc = @"
# Web UI V2 — Pacote de Instalação Sem Node.js (PC Forte)

- **Commit de Origem:** $GitSha ($ShortSha)
- **Gerado em:** $GeneratedAt
- **Destino no PC Forte:** C:\Projetos\MoneyPrinterTurbo\webui-v2\dist

---

## 1. Pré-Requisitos no PC Forte
- Repositório sincronizado via fast-forward:
  ````powershell
  cd C:\Projetos\MoneyPrinterTurbo
  git pull --ff-only origin main
  ````

## 2. Instalação dos Arquivos Compilados
Copie este arquivo ZIP para o PC Forte e execute no PowerShell:

````powershell
# 1. Definir o caminho raiz do projeto
`$ProjectRoot = "C:\Projetos\MoneyPrinterTurbo"
`$WebUiDist = Join-Path `$ProjectRoot "webui-v2\dist"

# 2. Criar ou limpar o diretório de destino
if (Test-Path `$WebUiDist) {
    Remove-Item -Path `$WebUiDist -Recurse -Force
}
New-Item -ItemType Directory -Path `$WebUiDist -Force | Out-Null

# 3. Descompactar os arquivos da pasta 'dist' do ZIP
# (Substitua .\webui-v2-dist-$ShortSha.zip pelo caminho do ZIP no PC Forte)
Expand-Archive -Path ".\webui-v2-dist-$ShortSha.zip" -DestinationPath `$ProjectRoot\webui-v2\temp_extract -Force
Copy-Item -Path `$ProjectRoot\webui-v2\temp_extract\dist\* -Destination `$WebUiDist -Recurse -Force
Remove-Item -Path `$ProjectRoot\webui-v2\temp_extract -Recurse -Force

# 4. Validar que index.html está no local correto
Test-Path (Join-Path `$WebUiDist "index.html")
````

## 3. Iniciar o Servidor Web UI V2 (Porta 8080)
````powershell
cd C:\Projetos\MoneyPrinterTurbo
.\scripts\start_webui_v2.ps1
````

## 4. Validar a Operação
````powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
````

## 5. Rollback Operacional Imediato
Caso necessário desativar a Web UI V2:
- Encerre o processo do Uvicorn na porta 8080 (CTRL+C ou encerre o PID registrado no log).
- O Streamlit na porta 8501 permanece inalterado e operacional.
- NÃO execute git checkout ou git switch --detach.
"@

$InstallDocPath = Join-Path $TempStage "INSTALL.md"
[System.IO.File]::WriteAllText($InstallDocPath, $InstallDoc, [System.Text.Encoding]::UTF8)

# 7. Compactação em Arquivo ZIP
Write-Host "[4/5] Criando arquivo ZIP..." -ForegroundColor Yellow
$ZipName = "webui-v2-dist-$ShortSha.zip"
$ZipPath = Join-Path $OutputDir $ZipName

if (Test-Path $ZipPath) {
    Remove-Item -Path $ZipPath -Force
}

Compress-Archive -Path (Join-Path $TempStage "*") -DestinationPath $ZipPath -CompressionLevel Optimal

# 8. Hash do Pacote ZIP Final
$ZipHash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ZipSize = (Get-Item $ZipPath).Length
$ZipChecksumPath = "$ZipPath.sha256"
[System.IO.File]::WriteAllText($ZipChecksumPath, "$ZipHash  $ZipName`n", [System.Text.Encoding]::UTF8)

# 9. Limpeza e Validação de Integridade do Pacote
Write-Host "[5/5] Validando integridade do pacote gerado..." -ForegroundColor Yellow
Remove-Item -Path $TempStage -Recurse -Force

$ValidateDir = Join-Path $OutputDir "validate_$ShortSha"
if (Test-Path $ValidateDir) {
    Remove-Item -Path $ValidateDir -Recurse -Force
}

Expand-Archive -Path $ZipPath -DestinationPath $ValidateDir -Force

$ValidatedIndex = Join-Path $ValidateDir "dist\index.html"
$ValidatedManifest = Join-Path $ValidateDir "manifest.json"
$ValidatedInstall = Join-Path $ValidateDir "INSTALL.md"

if (-not (Test-Path $ValidatedIndex) -or -not (Test-Path $ValidatedManifest) -or -not (Test-Path $ValidatedInstall)) {
    Remove-Item -Path $ValidateDir -Recurse -Force
    Write-Error "Falha na validação do pacote ZIP: estrutura interna incompleta."
    exit 1
}

# Conferência cruzada de hashes dos arquivos extraídos
$ExtractedManifest = Get-Content $ValidatedManifest -Raw | ConvertFrom-Json
$IntegrityPass = $true

foreach ($Entry in $ExtractedManifest.files.PSObject.Properties) {
    $FilePathRel = $Entry.Name.Replace('/', '\')
    $ExpectedHash = $Entry.Value.sha256
    $ExtractedFilePath = Join-Path $ValidateDir $FilePathRel
    
    if (-not (Test-Path $ExtractedFilePath)) {
        Write-Error "Arquivo esperado ausente no ZIP: $FilePathRel"
        $IntegrityPass = $false
        break
    }
    
    $ActualHash = (Get-FileHash -Path $ExtractedFilePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne $ExpectedHash) {
        Write-Error "Hash divergente para ${FilePathRel}: esperado $ExpectedHash, obtido $ActualHash"
        $IntegrityPass = $false
        break
    }
}

Remove-Item -Path $ValidateDir -Recurse -Force

if (-not $IntegrityPass) {
    Write-Error "Validação de integridade do pacote FALHOU."
    exit 1
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " PACOTE GERADO E VALIDADO COM SUCESSO (PASS)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Arquivo     : $ZipPath"
Write-Host "Tamanho     : $([math]::Round($ZipSize / 1KB, 2)) KB ($ZipSize bytes)"
Write-Host "SHA-256     : $ZipHash"
Write-Host "Checksum    : $ZipChecksumPath"
Write-Host "Arquivos    : $($Manifest.file_count) arquivos estáticos em dist/"
Write-Host "Integridade : 100% VERIFICADO E APROVADO"
Write-Host "==========================================================`n" -ForegroundColor Green

return [ordered]@{
    "status" = "PASS"
    "package_path" = $ZipPath
    "package_size" = $ZipSize
    "package_sha256" = $ZipHash
    "git_commit" = $GitSha
    "git_short_sha" = $ShortSha
}
