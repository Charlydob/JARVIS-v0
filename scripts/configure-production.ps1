param(
    [string]$ServerHost = "46.224.61.193",
    [string]$ServerUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\hetzner_ed25519",
    [string]$Domain = "jarvis.charlydob.com"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$localEnv = Join-Path $repoRoot ".env"
$temporaryEnv = Join-Path ([IO.Path]::GetTempPath()) ("jarvis-env-" + [guid]::NewGuid().ToString("N"))
$remoteTemporaryEnv = "/opt/jarvis/.env.new"

if (Test-Path -LiteralPath $localEnv) {
    throw "Refusing to overwrite the existing local .env"
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "SSH identity not found: $IdentityFile"
}

$secretBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
$token = [Convert]::ToHexString($secretBytes).ToLowerInvariant()
$dataDir = (Join-Path $env:USERPROFILE ".jarvis").Replace("\", "/")
$contents = @(
    "JARVIS_CORE_TOKEN=$token"
    "JARVIS_CORS_ORIGINS=https://$Domain"
    "JARVIS_CORE_TIMEOUT_SECONDS=180"
    "JARVIS_MAX_AUDIO_BYTES=26214400"
    "JARVIS_GATEWAY_WS_URL=wss://$Domain/internal/core/ws"
    "JARVIS_OLLAMA_URL=http://127.0.0.1:11434"
    "JARVIS_OLLAMA_MODEL=llama3.1:8b"
    "JARVIS_WHISPER_MODEL=small"
    "JARVIS_WHISPER_DEVICE=cpu"
    "JARVIS_WHISPER_COMPUTE_TYPE=int8"
    "JARVIS_TTS_VOICE=es-ES-AlvaroNeural"
    "JARVIS_DATA_DIR=$dataDir"
    "JARVIS_LOG_LEVEL=INFO"
) -join "`n"
$contents += "`n"

try {
    [IO.File]::WriteAllText($localEnv, $contents, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText($temporaryEnv, $contents, [Text.UTF8Encoding]::new($false))
    & scp -q -i $IdentityFile -o BatchMode=yes -o StrictHostKeyChecking=yes $temporaryEnv "${ServerUser}@${ServerHost}:$remoteTemporaryEnv"
    if ($LASTEXITCODE -ne 0) { throw "Could not upload the server environment" }
    & ssh -i $IdentityFile -o BatchMode=yes -o StrictHostKeyChecking=yes "${ServerUser}@${ServerHost}" "chmod 600 '$remoteTemporaryEnv' && chown root:root '$remoteTemporaryEnv' && mv '$remoteTemporaryEnv' /opt/jarvis/.env"
    if ($LASTEXITCODE -ne 0) { throw "Could not activate the server environment" }
    Write-Host "Created matching local and server JARVIS environments without displaying the token."
}
finally {
    if (Test-Path -LiteralPath $temporaryEnv) {
        Remove-Item -LiteralPath $temporaryEnv -Force
    }
}
