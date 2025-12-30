Write-Host 'BuddAI Local Launcher' -ForegroundColor Cyan

# Ensure execution happens in the script's directory
Set-Location $PSScriptRoot

# 1. Stop Docker if it's running to free up port 8000
if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
    Write-Host 'Ensuring Docker is stopped...' -ForegroundColor Yellow
    docker-compose down 2>$null
}

# 2. Check Ollama Status
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    if (-not (Get-Process ollama* -ErrorAction SilentlyContinue)) {
        Write-Host 'Ollama is not running. Starting...' -ForegroundColor Yellow
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    } else {
        Write-Host 'Ollama is running.' -ForegroundColor Green
    }
}

# 3. Check Models
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host 'Checking AI models...' -ForegroundColor Green
    $models = ollama list | Out-String
    $required = @('qwen2.5-coder:1.5b', 'qwen2.5-coder:3b')
    foreach ($model in $required) {
        if ($models -notmatch [regex]::Escape($model)) {
            Write-Host "Model '$model' missing. Pulling (this may take a while)..." -ForegroundColor Yellow
            ollama pull $model
        }
    }
}

# 4. Create Virtual Environment if missing
if (-not (Test-Path 'venv')) {
    Write-Host 'Creating Python virtual environment...' -ForegroundColor Green
    python -m venv venv
}

# 5. Install Dependencies
Write-Host 'Checking dependencies...' -ForegroundColor Green
# Upgrade pip first to fix potential "Request-sent" or SSL errors
./venv/Scripts/python.exe -m pip install --upgrade pip
./venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependency installation failed." -ForegroundColor Red
    exit
}

# 6. Run Server
Write-Host 'Starting BuddAI Server...' -ForegroundColor Cyan

# Get LAN IP for local network access
$lanIp = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" }).IPv4Address.IPAddress | Select-Object -First 1

Write-Host "   Local PC:  http://localhost:8000/web" -ForegroundColor Gray
Write-Host "   On Phone:  http://$($lanIp):8000/web" -ForegroundColor Green

# Check for Tailscale (Private VPN)
# Try multiple methods to detect Tailscale IP
$tailscaleIp = (Get-NetIPAddress -InterfaceAlias "*Tailscale*" -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress | Select-Object -First 1

if (-not $tailscaleIp) {
    # Fallback: Look for any IP in the 100.x.x.x range (Tailscale uses CGNAT 100.64.0.0/10)
    $tailscaleIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -like "100.*" -and $_.InterfaceAlias -notlike "*Loopback*" }).IPAddress | Select-Object -First 1
}

if ($tailscaleIp) {
    Write-Host "   Tailscale: http://$($tailscaleIp):8000/web (Secure VPN)" -ForegroundColor Magenta
} elseif (Get-Service "Tailscale" -ErrorAction SilentlyContinue) {
    Write-Host "   Tailscale: Installed but not connected. Open app to log in." -ForegroundColor Yellow
} else {
    Write-Host "   Tailscale: (Optional) Run 'winget install Tailscale.Tailscale' for VPN access" -ForegroundColor DarkGray
}

# Attempt to open Firewall for LAN/VPN access
if (-not (Get-NetFirewallRule -DisplayName "BuddAI Allow Port 8000" -ErrorAction SilentlyContinue)) {
    try {
        New-NetFirewallRule -DisplayName "BuddAI Allow Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow -ErrorAction Stop | Out-Null
        Write-Host "   [+] Firewall rule added for Port 8000" -ForegroundColor DarkGray
    } catch {
        Write-Host "   [!] Firewall rule missing. Remote access will be blocked." -ForegroundColor Red
        Write-Host "   [?] Press 'A' to restart as Administrator to fix, or any key to continue..." -NoNewline -ForegroundColor Yellow
        if ([Console]::ReadKey($true).Key -eq 'A') {
            Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
            exit
        }
        Write-Host ""
    }
}

# Check for ngrok (Global or Local)
$ngrokPath = $null
$publicUrl = ""
if (Test-Path ".\ngrok.exe") {
    $ngrokPath = (Resolve-Path ".\ngrok.exe").Path
} elseif (Get-Command ngrok -ErrorAction SilentlyContinue) {
    $ngrokPath = "ngrok"
}

if ($ngrokPath -and -not $tailscaleIp) {
    Write-Host "   Remote:    Run '$ngrokPath http 8000' for public access" -ForegroundColor DarkGray
    Write-Host "   [?] Press 'N'/'S' for Ngrok, or any key to skip (3s)..." -NoNewline -ForegroundColor Yellow
    
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 3) {
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true).Key
            if ($key -eq 'N' -or $key -eq 'S') {
                $ngrokArgs = "http 8000"
                if ($key -eq 'S') {
                    $ngrokArgs += " --basic-auth=`"admin:buddai`""
                    Write-Host "`n   Launching Ngrok (Secure: admin/buddai)..." -ForegroundColor Green
                } else {
                    Write-Host "`n   Launching Ngrok (Public)..." -ForegroundColor Green
                }
                Start-Process $ngrokPath -ArgumentList $ngrokArgs -WindowStyle Hidden
            
            # Retry loop to fetch URL (up to 15s)
            $url = $null
            Write-Host "   Waiting for tunnel..." -NoNewline -ForegroundColor DarkGray
            for ($i = 0; $i -lt 15; $i++) {
                Start-Sleep -Seconds 1
                try {
                    $tunnels = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction Stop
                    if ($tunnels.tunnels.Count -gt 0) { $url = $tunnels.tunnels[0].public_url; break }
                } catch {}
                Write-Host "." -NoNewline -ForegroundColor DarkGray
            }
            Write-Host ""

            if ($url) {
                $publicUrl = $url
                Write-Host "   Remote URL: $url" -ForegroundColor Cyan
                Write-Host "   Scan QR Code:" -ForegroundColor Gray
                $qrScript = "import sys, qrcode; qr = qrcode.QRCode(); qr.add_data(sys.argv[1]); qr.print_ascii(invert=True)"
                & ./venv/Scripts/python.exe -c $qrScript $url 2>$null
            } else {
                Write-Host "   Ngrok running. Check http://localhost:4040 for URL" -ForegroundColor Yellow
            }
        } else {
            Write-Host "`n   Skipping Ngrok..." -ForegroundColor DarkGray
        }
        break
        }
        Start-Sleep -Milliseconds 50
    }
    Write-Host ""
} elseif ($ngrokPath) {
    Write-Host "   Remote:    Ngrok available (Skipped due to Tailscale)" -ForegroundColor DarkGray
} else {
    Write-Host "   Remote:    (Optional) Run 'winget install Ngrok.Ngrok' to enable remote access" -ForegroundColor DarkGray
}

# Determine best URL for the server to know about
if (-not $publicUrl -and $tailscaleIp) {
    $publicUrl = "http://$($tailscaleIp):8000/web"
} elseif (-not $publicUrl) {
    $publicUrl = "http://$($lanIp):8000/web"
}

Write-Host '   Opening browser...' -ForegroundColor DarkGray
Start-Process 'http://localhost:8000/'
# Use --host 0.0.0.0 to allow connections from other devices
./venv/Scripts/python.exe main.py --server --port 8000 --host 0.0.0.0 --public-url "$publicUrl"