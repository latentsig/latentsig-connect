param(
    [Parameter(Mandatory = $true)][string]$PublicUrl,
    [Parameter(Mandatory = $true)][string]$AdminEmail,
    [string[]]$AdditionalAdminEmails = @(),
    [string]$OutputPath = ".env"
)

$ErrorActionPreference = "Stop"

$parsedUrl = [Uri]$PublicUrl
if ($parsedUrl.Scheme -ne "https" -or -not $parsedUrl.Host) {
    throw "PublicUrl must be the HTTPS URL of the deployed application."
}
if ($parsedUrl.AbsolutePath -ne "/" -or $parsedUrl.Query -or $parsedUrl.Fragment) {
    throw "PublicUrl must be the HTTPS origin without a path, query, or fragment."
}
try {
    $normalizedEmail = ([System.Net.Mail.MailAddress]$AdminEmail).Address.ToLowerInvariant()
} catch {
    throw "AdminEmail must be a valid email address."
}
$adminEmails = @($normalizedEmail)
foreach ($email in $AdditionalAdminEmails) {
    try {
        $normalizedAdditionalEmail = ([System.Net.Mail.MailAddress]$email).Address.ToLowerInvariant()
    } catch {
        throw "Additional admin email '$email' is not valid."
    }
    if ($normalizedAdditionalEmail -notin $adminEmails) {
        $adminEmails += $normalizedAdditionalEmail
    }
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
$domain = $parsedUrl.DnsSafeHost.ToLowerInvariant()
$redirect = "$origin/api/v1/auth/google/callback"
$contents = @(
    "APP_ENV=production",
    "APP_SECRET=$appSecret",
    "POSTGRES_PASSWORD=$databasePassword",
    "PUBLIC_DOMAIN=$domain",
    "CERTBOT_EMAIL=$normalizedEmail",
    "FRONTEND_URL=$origin",
    "FRONTEND_URLS=$origin",
    "GOOGLE_REDIRECT_URI=$redirect",
    "ADMIN_EMAIL_ALLOWLIST=$($adminEmails -join ',')",
    "INITIAL_ADMIN_EMAILS=$normalizedEmail",
    "OCR_ENABLED=false",
    "OPENROUTER_API_KEY="
) -join "`n"
$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
[System.IO.File]::WriteAllText($outputFullPath, "$contents`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Created $OutputPath with unique application and database secrets for $origin."
Write-Host "The generated environment disables OCR until an OpenRouter key is configured securely."
Write-Host "Start the app stack with: docker compose --profile production up --build -d"
Write-Host "Then provision the team password with: docker compose exec backend python -m app.cli set-password $normalizedEmail"
