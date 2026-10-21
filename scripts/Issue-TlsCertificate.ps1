param(
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"
$composeArgs = @("--file", $ComposeFile)

docker compose @composeArgs --profile production up --build -d nginx
if ($LASTEXITCODE -ne 0) { throw "Could not start the production Nginx bootstrap listener." }

docker compose @composeArgs --profile production --profile certificates run --rm certbot
if ($LASTEXITCODE -ne 0) { throw "Certificate issuance failed. Confirm DNS points to this server and port 80 is reachable." }

docker compose @composeArgs --profile production restart nginx
if ($LASTEXITCODE -ne 0) { throw "Certificate was issued, but Nginx could not be restarted into HTTPS mode." }
Write-Host "Certificate issued and Nginx restarted with HTTPS."
