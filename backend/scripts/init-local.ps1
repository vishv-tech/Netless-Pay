$ErrorActionPreference = 'Stop'
$backendDirectory = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $backendDirectory '.env'
function New-LocalSecret([bool]$base64 = $false) {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    if ($base64) { return [Convert]::ToBase64String($bytes) }
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}
$values = [ordered]@{}
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in [IO.File]::ReadAllLines($envPath)) {
        if ($line -match '^([A-Z_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
    }
    # Preserve an existing Sprint 0/1 database owner and password for its volume.
    if (-not $values['DB_ADMIN_PASSWORD'] -and $values['DB_PASSWORD'] -and $values['DB_USER'] -ne 'wallet_runtime') {
        $values['DB_ADMIN_USER'] = $values['DB_USER']
        $values['DB_ADMIN_PASSWORD'] = $values['DB_PASSWORD']
        $values['DB_PASSWORD'] = New-LocalSecret
    }
}
foreach ($line in [IO.File]::ReadAllLines((Join-Path $backendDirectory '.env.example'))) {
    if ($line -match '^([A-Z_]+)=(.*)$' -and -not $values.Contains($matches[1])) { $values[$matches[1]] = $matches[2] }
}
$values['DB_USER'] = 'wallet_runtime'
foreach ($key in @('DB_PASSWORD', 'DB_ADMIN_PASSWORD', 'MIGRATION_DB_PASSWORD')) {
    if (-not $values[$key]) { $values[$key] = New-LocalSecret }
}
if (-not $values['DEVICE_MASTER_KEY']) { $values['DEVICE_MASTER_KEY'] = New-LocalSecret $true }
$content = "# Local development only. Do not share or commit.`n" + (($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n") + "`n"
[IO.File]::WriteAllText($envPath, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Output 'Local configuration ready. Existing master key preserved; no secrets printed.'
