<#
.SYNOPSIS
    Script de Inicialização do Servidor de IA Local (Fase V1.4C).
.DESCRIPTION
    Inicia o servidor de inferência local (llama-server) compatível com OpenAI
    para atuar como Local Brain (Qwen3-8B) no PC Forte.
    - Operação estritamente em localhost (127.0.0.1)
    - Proibido qualquer bind em 0.0.0.0
    - Suporte acelerado via GPU Vulkan (Radeon RX 580)
    - Totalmente parametrizável e portável
#>

[CmdletBinding()]
param(
    [string]$ModelPath = "",
    [string]$LlamaServerExe = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8089,
    [int]$ContextSize = 4096,
    [int]$GpuLayers = 99,
    [string]$Device = "Vulkan0",
    [int]$Threads = 4
)

$ErrorActionPreference = "Stop"

# 1. Validação de Segurança Estrita: Apenas Localhost
if ($HostAddress -eq "0.0.0.0" -or $HostAddress -eq "::") {
    Write-Error "[SEGURANÇA] Bind em 0.0.0.0 é estritamente proibido por política da Video Factory. Use apenas 127.0.0.1."
    exit 1
}

# 2. Resolução do Diretório Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 3. Resolução do Caminho do Modelo GGUF
if ([string]::IsNullOrWhiteSpace($ModelPath)) {
    if ($env:LOCAL_AI_MODEL_PATH) {
        $ModelPath = $env:LOCAL_AI_MODEL_PATH
    } else {
        # Caminho padrão no armazenamento local
        $ModelPath = Join-Path $ProjectRoot "storage\models\Qwen3-8B-Q4_K_M.gguf"
    }
}

# 4. Resolução do Executável do llama-server
if ([string]::IsNullOrWhiteSpace($LlamaServerExe)) {
    $Candidates = @(
        (Join-Path $ProjectRoot "tools\llama.cpp\llama-server.exe"),
        (Join-Path $ProjectRoot "llama.cpp\llama-server.exe"),
        (Join-Path $ProjectRoot "llama-b11476-bin-win-vulkan-x64\llama-server.exe"),
        (Join-Path $ProjectRoot "llama-b11476-bin-win-cpu-x64\llama-server.exe")
    )
    foreach ($cand in $Candidates) {
        if (Test-Path $cand) {
            $LlamaServerExe = $cand
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($LlamaServerExe)) {
        $fromPath = Get-Command "llama-server.exe" -ErrorAction SilentlyContinue
        if ($fromPath) {
            $LlamaServerExe = $fromPath.Source
        }
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " VIDEO FACTORY — LOCAL AI SERVER INITIALIZER (V1.4C)      " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Host:        $HostAddress"
Write-Host "Porta:       $Port"
Write-Host "Contexto:    $ContextSize tokens"
Write-Host "GPU Layers:  $GpuLayers ($Device)"
Write-Host "Threads:     $Threads"
Write-Host "Modelo:      $ModelPath"
Write-Host "Executável:  $LlamaServerExe"
Write-Host "==========================================================" -ForegroundColor Cyan

# Verificações de Pré-Requisitos
if (-not (Test-Path $ModelPath)) {
    Write-Warning "[AVISO] Arquivo do modelo não encontrado em: $ModelPath"
    Write-Warning "Por favor, baixe ou copie o modelo Qwen3-8B-Q4_K_M.gguf para esse local ou especifique -ModelPath."
    exit 2
}

if (-not $LlamaServerExe -or -not (Test-Path $LlamaServerExe)) {
    Write-Warning "[AVISO] llama-server.exe não localizado."
    Write-Warning "Especifique o caminho do executável com o parâmetro -LlamaServerExe."
    exit 3
}

$Arguments = @(
    "--model", "`"$ModelPath`"",
    "--host", $HostAddress,
    "--port", $Port,
    "-c", $ContextSize,
    "-ngl", $GpuLayers,
    "-t", $Threads
)

if (-not [string]::IsNullOrWhiteSpace($Device)) {
    $Arguments += @("--device", $Device)
}

Write-Host "[INICIANDO] Executando llama-server em http://$HostAddress:$Port/v1 ..." -ForegroundColor Green
& $LlamaServerExe @Arguments
