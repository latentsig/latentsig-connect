param(
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"
$composeArgs = @("--file", $ComposeFile)

docker compose @composeArgs --profile production --profile certificates run --rm certbot renew --webroot -w /var/www/certbot --quiet
if ($LASTEXITCODE -ne 0) { throw "Certificate renewal failed." }

docker compose @composeArgs --profile production exec -T nginx nginx -s reload
if ($LASTEXITCODE -ne 0) { throw "Certificate renewal completed, but Nginx could not reload." }
Write-Host "Certificate renewal check completed and Nginx reloaded."
