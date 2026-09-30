param(
    [Parameter(Mandatory = $true)][string]$PublicUrl,
    [Parameter(Mandatory = $true)][string]$AdminEmail,
    [string]$OutputPath = ".env"
)

$parsedUrl = [Uri]$PublicUrl
if ($parsedUrl.Scheme -ne "https" -or -not $parsedUrl.Host) {
    throw "PublicUrl must be the HTTPS URL of the deployed application."
}
try {
    $normalizedEmail = ([System.Net.Mail.MailAddress]$AdminEmail).Address.ToLowerInvariant()
} catch {
    throw "AdminEmail must be a valid email address."
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "$OutputPath already exists; move it aside before generating new secrets."
}

$secretBytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
$appSecret = [Convert]::ToHexString($secretBytes).ToLowerInvariant()
$databaseBytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($databaseBytes)
$databasePassword = [Convert]::ToHexString($databaseBytes).ToLowerInvariant()
$origin = $parsedUrl.GetLeftPart([System.UriPartial]::Authority)
$redirect = "$origin/api/v1/auth/google/callback"
$contents = @(
    "APP_ENV=production",
    "APP_SECRET=$appSecret",
    "POSTGRES_PASSWORD=$databasePassword",
    "FRONTEND_URL=$origin",
    "FRONTEND_URLS=$origin",
    "GOOGLE_REDIRECT_URI=$redirect",
    "ADMIN_EMAIL_ALLOWLIST=$normalizedEmail",
    "INITIAL_ADMIN_EMAILS=$normalizedEmail"
) -join "`n"
[System.IO.File]::WriteAllText((Join-Path (Get-Location) $OutputPath), "$contents`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Created $OutputPath with unique application and database secrets for $origin."
Write-Host "Start PostgreSQL, Redis, backups, monitoring, and the app with: docker compose up --build -d"
Write-Host "Then provision the team password with: docker compose exec backend python -m app.cli set-password $normalizedEmail"
