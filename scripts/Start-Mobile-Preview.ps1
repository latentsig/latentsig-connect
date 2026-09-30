param(
    [string]$LanAddress
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not $LanAddress) {
    $routeProbe = [System.Net.Sockets.UdpClient]::new()
    try {
        $routeProbe.Connect('8.8.8.8', 53)
        $LanAddress = $routeProbe.Client.LocalEndPoint.Address.IPAddressToString
    } finally {
        $routeProbe.Dispose()
    }
}

$parsedAddress = [System.Net.IPAddress]::Parse($LanAddress)
if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or $parsedAddress.ToString().StartsWith('127.')) {
    throw 'LanAddress must be this computer’s Wi-Fi or Ethernet IPv4 address.'
}

foreach ($port in @(5173, 8000)) {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try {
        $probe.Connect('127.0.0.1', $port)
        throw "Port $port is already in use. Stop the existing LatentSig service before starting mobile preview."
    } catch [System.Net.Sockets.SocketException] {
        # The expected result is that no process is listening yet.
    } finally {
        $probe.Dispose()
    }
}

$python = (Get-Command python.exe).Source
$node = (Get-Command node.exe).Source
$apiUrl = "http://${LanAddress}:8000"
$siteUrl = "http://${LanAddress}:5173"
$frontendOrigins = "http://${LanAddress}:5173,http://localhost:5173,http://127.0.0.1:5173"

$apiStart = [System.Diagnostics.ProcessStartInfo]::new()
$apiStart.FileName = $python
$apiStart.Arguments = '-m uvicorn app.main:app --host 0.0.0.0 --port 8000'
$apiStart.WorkingDirectory = Join-Path $repoRoot 'backend'
$apiStart.UseShellExecute = $false
$apiStart.CreateNoWindow = $true
$apiStart.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$env:FRONTEND_URL = $siteUrl
$env:FRONTEND_URLS = $frontendOrigins
$apiProcess = [System.Diagnostics.Process]::Start($apiStart)

$webStart = [System.Diagnostics.ProcessStartInfo]::new()
$webStart.FileName = $node
$webStart.Arguments = 'node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173'
$webStart.WorkingDirectory = Join-Path $repoRoot 'frontend'
$webStart.UseShellExecute = $false
$webStart.CreateNoWindow = $true
$webStart.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$env:VITE_API_BASE_URL = '__LATENTSIG_LOCAL_API__'
$env:VITE_PUBLIC_SITE_URL = $siteUrl
$webProcess = [System.Diagnostics.Process]::Start($webStart)

Write-Host "Mobile preview is starting for $LanAddress."
Write-Host "Admin: $siteUrl/admin/login"
Write-Host "Capture: $siteUrl/connect"
Write-Host "API readiness: $apiUrl/health/ready"
Write-Host "Processes: API $($apiProcess.Id), web $($webProcess.Id)"
Write-Host 'Connect the phone to the same Wi-Fi, open Admin > Settings, and scan the event QR code.'
Write-Host 'On the phone, use the business-card Take Photo button to open the rear camera.'
