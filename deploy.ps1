<#
.SYNOPSIS
    Installs or updates the ArchiMate MCP server in a fixed folder from an install package.

.DESCRIPTION
    Run it from an unzipped install package (or give -Package with the .zip).
    With an empty or missing -Target it installs; with an existing install it
    updates it in place:

      1. refuses while the server still answers on its port, or still runs
         over stdio for an MCP client (stop it first);
      2. backs the installation up next to it, as <Target>.backup-<timestamp>
         (without .venv);
      3. copies the package's files over the old ones. Your own files are
         kept: .env, .venv, anything you added.
         Files the old version installed and the new one does not have are
         deleted (MANIFEST.txt lists what a package installs);
      4. installs the Python packages into .venv (created when missing);
      5. lists settings that are new in .env.example, and settings in your
         .env this version no longer knows;
      6. with -Start, starts the server over HTTP in a window of its own.
         MCP clients that start it over stdio need nothing: they run the
         new version the next time they start it.

    The same script is in the packages of the ArchiMate API and the
    ArchiMate Browser; only the settings block below differs.

.PARAMETER Target
    The installation folder, e.g. C:\Apps\ArchiMateMCP.

.PARAMETER Package
    The install package: its .zip or its unzipped folder. Default: the folder
    this script is in.

.PARAMETER Start
    Start the server (HTTP) when done.

.PARAMETER Force
    Also install a package older than the installed version.

.PARAMETER NoSkills
    Do not install the package's skills for Claude (a package with
    skills\install.ps1, such as the API's): they are installed by default,
    into %USERPROFILE%\.claude\skills.

.EXAMPLE
    .\deploy.ps1 -Target C:\Apps\ArchiMateMCP -Start

.EXAMPLE
    archimatemcp.bat deploy C:\Apps\ArchiMateMCP
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Package = "",
    [switch]$Start,
    [switch]$Force,
    [switch]$NoSkills
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------------ settings of this project
$Product      = "ArchiMate MCP server"
$Launcher     = "archimatemcp.bat"
# Folders whose content belongs to the package: an install made before packages
# had a MANIFEST.txt is cleaned there (files the new package lacks are deleted).
$OwnedDirs    = @("app")
# Never copied over, never deleted.
$KeepNames    = @(".env", ".venv")
$KeepPatterns = @()
$UsesPython   = $true    # .venv + requirements.txt
$UsesDatabase = $false
$DefaultPort  = 8100     # the HTTP transport
$PortSetting  = "PORT"   # in .env
$HostSetting  = "HOST"
$StartCommand = "start"
# Launchers of earlier versions (none: the first version was ArchiMateMCP).
$OldLaunchers = @()
# Comment out settings of .env that .env.example does not name: the server refuses
# to start with a setting it does not know (an obsolete one, after an update).
$CommentOutUnknown = $true
# Added to the message when programs started from the installation still run.
$RunningHint  = " An MCP client (Claude Desktop, Claude Code) that started the server over stdio keeps it running: quit it, or end its session."

# ------------------------------------------------------------------ helpers
function Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }
function Note([string]$Text) { Write-Host "   $Text" }
function Warn([string]$Text) { Write-Host "   WARNING: $Text" -ForegroundColor Yellow }
function Fail([string]$Text) { Write-Host ""; Write-Host "ERROR: $Text" -ForegroundColor Red; exit 1 }

# Windows PowerShell 5.1 refuses paths of 260 characters or more; with the \\?\ prefix .NET takes any length.
function Long([string]$Path) {
    if ($Path.StartsWith("\\?\")) { return $Path }
    if ($Path.StartsWith("\\")) { return "\\?\UNC\" + $Path.Substring(2) }
    return "\\?\" + $Path
}

function Read-Manifest([string]$Folder) {
    $file = Join-Path $Folder "MANIFEST.txt"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    return @(Get-Content -LiteralPath $file -Encoding UTF8 | Where-Object { $_ -and -not $_.StartsWith("#") })
}

function Is-Kept([string]$RelativePath) {
    $first = ($RelativePath -split '[\\/]')[0]
    if ($KeepNames -contains $first) { return $true }
    $name = Split-Path $RelativePath -Leaf
    foreach ($pattern in $KeepPatterns) { if ($name -like $pattern) { return $true } }
    return $false
}

# KEY=value lines of a .env file; with -Commented also the "#KEY=value" examples.
function Read-Settings([string]$File, [switch]$Commented) {
    $keys = @{}
    if (-not (Test-Path -LiteralPath $File)) { return $keys }
    $pattern = '^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$'
    if ($Commented) { $pattern = '^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=(.*)$' }
    foreach ($line in Get-Content -LiteralPath $File -Encoding UTF8) {
        if ($line -match $pattern) { $keys[$Matches[1]] = $Matches[2].Trim() }
    }
    return $keys
}

function Version-Of([string]$Folder) {
    # app\version.py (API, MCP server) or js\version.js (browser, since 2.7.0)
    foreach ($name in @("app\version.py", "js\version.js")) {
        $file = Join-Path $Folder $name
        if (Test-Path -LiteralPath $file) {
            $m = Select-String -LiteralPath $file -Pattern 'APP_VERSION\s*=\s*["'']([^"'']+)["'']' | Select-Object -First 1
            if ($m) { return $m.Matches[0].Groups[1].Value }
        }
    }
    # Without a version number of its own: the first heading of the CHANGELOG.
    $log = Join-Path $Folder "CHANGELOG.md"
    if (Test-Path -LiteralPath $log) {
        $m = Select-String -LiteralPath $log -Pattern '^## (\S+)' | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return $null
}

function Compare-Version([string]$A, [string]$B) {
    # 1: A newer, -1: A older, 0: the same. Dates (the browser before 2.7.0) compare as text, and any
    # version number is newer than a date.
    $isDate = { param($v) $v -match '^\d{4}-\d{2}-\d{2}$' }
    $dateA = & $isDate $A; $dateB = & $isDate $B
    if ($dateA -and -not $dateB) { return -1 }
    if ($dateB -and -not $dateA) { return 1 }
    try { return ([version]$A).CompareTo([version]$B) } catch { return [Math]::Sign([string]::CompareOrdinal($A, $B)) }
}

# Processes started from the installation (its .venv's Python): they keep files open.
function Running-From([string]$Folder) {
    $prefix = $Folder.TrimEnd('\') + "\"
    return @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) })
}

function Port-In-Use([string]$HostName, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect($HostName, $Port, $null, $null)
        if ($wait.AsyncWaitHandle.WaitOne(700) -and $client.Connected) { return $true }
        return $false
    } catch { return $false } finally { $client.Close() }
}

function Copy-Folder([string]$Source, [string]$Destination, [string[]]$SkipDirs) {
    [void][System.IO.Directory]::CreateDirectory((Long $Destination))
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $to = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            if ($SkipDirs -notcontains $item.Name) { Copy-Folder $item.FullName $to $SkipDirs }
        } else {
            [System.IO.File]::Copy((Long $item.FullName), (Long $to), $true)
        }
    }
}

# ------------------------------------------------------------------ the package
if (-not $Package) { $Package = $PSScriptRoot }
$Package = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Package)
$Target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Target).TrimEnd('\')
$Unzipped = $null
$PackageLabel = $Package
if ($Package -like "*.zip") {
    if (-not (Test-Path -LiteralPath $Package)) { Fail "No such package: $Package" }
    $Unzipped = Join-Path ([System.IO.Path]::GetTempPath()) ("deploy-" + [guid]::NewGuid().ToString("N"))
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Package, $Unzipped)
    $Package = $Unzipped
}

try {
    $NewFiles = Read-Manifest $Package
    if ($null -eq $NewFiles) { Fail "$Package is not an install package of the $Product (no MANIFEST.txt). Build one with createinstallpackage.ps1." }
    if ($Target -eq $Package.TrimEnd('\')) { Fail "The target is the package folder itself. Give the installation folder, e.g. C:\Apps\ArchiMateMCP." }

    $NewVersion = Version-Of $Package
    $Existing = (Test-Path -LiteralPath $Target) -and @(Get-ChildItem -LiteralPath $Target -Force).Count -gt 0
    $OldVersion = $null
    if ($Existing) { $OldVersion = Version-Of $Target }

    Write-Host "$Product`: $(if ($Existing) { "update of $Target" } else { "new installation in $Target" })"
    Write-Host "   package: $PackageLabel ($NewVersion)"
    if ($Existing) { Write-Host "   installed: $(if ($OldVersion) { $OldVersion } else { 'unknown version' })" }

    $launchers = @($Launcher) + $OldLaunchers
    if ($Existing -and -not ($launchers | Where-Object { Test-Path -LiteralPath (Join-Path $Target $_) })) {
        Fail "$Target holds files, but no ${Launcher}: not an installation of the $Product. Give an empty folder or the installation."
    }
    if ($Existing -and $OldVersion -and $NewVersion -and (Compare-Version $NewVersion $OldVersion) -lt 0 -and -not $Force) {
        Fail "The package ($NewVersion) is older than the installation ($OldVersion). Use -Force to install it anyway."
    }

    # -------------------------------------------------------------- 1. not running
    $envFile = Join-Path $Target ".env"
    $settings = Read-Settings $envFile
    $port = $DefaultPort
    if ($settings.ContainsKey($PortSetting) -and $settings[$PortSetting] -match '^\d+$') { $port = [int]$settings[$PortSetting] }
    $hostName = "127.0.0.1"
    if ($settings.ContainsKey($HostSetting) -and $settings[$HostSetting] -and $settings[$HostSetting] -notin @("0.0.0.0", "::", "localhost")) { $hostName = $settings[$HostSetting] }
    if ($Existing -and $port -and (Port-In-Use $hostName $port)) {
        Fail "Something answers on $hostName`:$port - the $Product is probably still running. Stop it (Ctrl+C in its window), then run this again."
    }
    $running = @()
    if ($Existing) { $running = Running-From $Target }
    if ($running.Count) {
        $list = ($running | ForEach-Object { "$($_.ProcessName) ($($_.Id))" }) -join ", "
        Fail "Programs started from $Target still run: $list.$RunningHint Stop them, then run this again."
    }

    # -------------------------------------------------------------- 2. backup
    $backup = $null
    if ($Existing) {
        Step "Backup"
        $backup = "$Target.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Folder $Target $backup @(".venv", "__pycache__")
        Note "Copied to $backup$(if ($UsesPython) { ' (without .venv)' })."
        if ($UsesDatabase -and $settings.ContainsKey("DB_URL")) {
            $db = $settings["DB_URL"]
            if ($db -match '^sqlite:///(.+)$') {
                $dbPath = $Matches[1]
                if (-not [System.IO.Path]::IsPathRooted($dbPath)) { $dbPath = Join-Path $Target $dbPath }
                $dbPath = [System.IO.Path]::GetFullPath($dbPath)
                if (-not $dbPath.StartsWith($Target + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
                    if (Test-Path -LiteralPath $dbPath) {
                        Copy-Item -LiteralPath $dbPath -Destination $backup
                        Note "The database $dbPath is outside the installation; copied into the backup too."
                    }
                } else {
                    Note "The SQLite database is in the installation folder, so it is in the backup."
                }
            } elseif ($db) {
                Warn "The database is not SQLite ($($db -replace '://[^@]*@', '://***@')): back it up yourself before going on, e.g. with mysqldump."
            }
        }
    }

    # -------------------------------------------------------------- 3. files
    Step "Files"
    [void][System.IO.Directory]::CreateDirectory((Long $Target))
    $OldFiles = $null
    if ($Existing) { $OldFiles = Read-Manifest $Target }
    $newSet = @{}
    foreach ($f in $NewFiles) { $newSet[$f.ToLowerInvariant()] = $true }
    $copied = 0
    foreach ($f in $NewFiles) {
        if (Is-Kept $f) { continue }
        $to = Join-Path $Target $f
        [void][System.IO.Directory]::CreateDirectory((Long (Split-Path $to -Parent)))
        [System.IO.File]::Copy((Long (Join-Path $Package $f)), (Long $to), $true)
        $copied++
    }
    [System.IO.File]::Copy((Long (Join-Path $Package "MANIFEST.txt")), (Long (Join-Path $Target "MANIFEST.txt")), $true)
    Note "$copied files copied."

    # Files the old version installed that the new one does not have.
    $stale = @()
    if ($null -ne $OldFiles) {
        $stale = @($OldFiles | Where-Object { -not $newSet.ContainsKey($_.ToLowerInvariant()) -and -not (Is-Kept $_) })
    } elseif ($Existing) {
        # An installation from before MANIFEST.txt: the package's own folders are cleaned.
        foreach ($dir in $OwnedDirs) {
            $root = Join-Path $Target $dir
            if (-not (Test-Path -LiteralPath $root)) { continue }
            foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File -Force) {
                $rel = $file.FullName.Substring($Target.Length + 1)
                if (-not $newSet.ContainsKey($rel.ToLowerInvariant())) { $stale += $rel }
            }
        }
    }
    foreach ($rel in $stale) {
        $path = Join-Path $Target $rel
        if (Test-Path -LiteralPath $path) { [System.IO.File]::Delete((Long $path)) }
    }
    # Python's caches of deleted modules, and folders left empty
    foreach ($dir in $OwnedDirs) {
        $root = Join-Path $Target $dir
        if (-not (Test-Path -LiteralPath $root)) { continue }
        Get-ChildItem -LiteralPath $root -Recurse -Directory -Force -Filter "__pycache__" | ForEach-Object { [System.IO.Directory]::Delete((Long $_.FullName), $true) }
        Get-ChildItem -LiteralPath $root -Recurse -Directory -Force | Sort-Object { $_.FullName.Length } -Descending |
            Where-Object { @(Get-ChildItem -LiteralPath $_.FullName -Force).Count -eq 0 } |
            ForEach-Object { [System.IO.Directory]::Delete((Long $_.FullName)) }
    }
    if ($stale.Count) { Note "$($stale.Count) file(s) of the old version deleted: $((($stale | Select-Object -First 5) -join ', '))$(if ($stale.Count -gt 5) { ', ...' })" }

    # -------------------------------------------------------------- 4. settings
    Step "Settings"
    $example = Join-Path $Target ".env.example"
    $createdEnv = $false
    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $example -Destination $envFile
        $createdEnv = $true
        Note ".env created from .env.example. Edit it before you start (see the README, Configuration)."
    } else {
        Note ".env kept."
    }
    $known = Read-Settings $example -Commented
    $mine = Read-Settings $envFile
    $unknown = @($mine.Keys | Where-Object { -not $known.ContainsKey($_) } | Sort-Object)
    if ($unknown.Count -and $CommentOutUnknown) {
        $stamp = Get-Date -Format "yyyy-MM-dd"
        $lines = foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=' -and $unknown -contains $Matches[1]) {
                "# Not a setting of $NewVersion, commented out by deploy.ps1 on ${stamp}:"
                "#$line"
            } else { $line }
        }
        [System.IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
        Warn "Settings in .env that this version does not know, now commented out: $($unknown -join ', ')"
    } elseif ($unknown.Count) {
        Warn "Settings in .env that this version does not know (remove them): $($unknown -join ', ')"
    }
    if ($backup) {
        $before = Read-Settings (Join-Path $backup ".env.example") -Commented
        $added = @($known.Keys | Where-Object { -not $before.ContainsKey($_) } | Sort-Object)
        if ($added.Count) { Note "New settings, described in .env.example: $($added -join ', ')" }
    }

    # -------------------------------------------------------------- 5. Python packages
    if ($UsesPython) {
        Step "Python packages"
        $python = Join-Path $Target ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) {
            Note "Creating .venv..."
            & python -m venv (Join-Path $Target ".venv")
            if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment (is Python 3 on the PATH?)." }
        }
        & $python -m pip install --disable-pip-version-check -q -r (Join-Path $Target "requirements.txt")
        if ($LASTEXITCODE -ne 0) { Fail "pip could not install requirements.txt. The files are updated; the backup is $backup." }
        Note "requirements.txt installed."
    }

    # -------------------------------------------------------------- 6. database
    if ($UsesDatabase) {
        Step "Database"
        Push-Location $Target
        try {
            $env:PYTHONIOENCODING = "utf-8"
            # alembic logs to stderr, which Windows PowerShell turns into errors once it is redirected
            # (by the caller too, e.g. deploy.ps1 ... 2>&1): the exit code decides
            $ErrorActionPreference = "Continue"
            & $python -m alembic upgrade head
            $migrated = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            if ($migrated -ne 0) {
                $restore = ""
                if ($backup) { $restore = " To go back: delete $Target except .venv, copy $backup over it, and run $Launcher migrate there." }
                Fail "The migration failed; see the messages above.$restore"
            }
            $ErrorActionPreference = "Continue"
            $current = & $python -m alembic current 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch '^INFO' } | Select-Object -Last 1
            $ErrorActionPreference = "Stop"
            Note "Database at revision $current"
        } finally { Pop-Location }
    }

    # -------------------------------------------------------------- skills for Claude
    # A package with skills\install.ps1 (the API's SQL skill, 3.23.0) installs its skills into the user's
    # Claude skills, %USERPROFILE%\.claude\skills, replacing the copies there; -NoSkills leaves them.
    $skillInstaller = Join-Path $Target "skills\install.ps1"
    if ((Test-Path -LiteralPath $skillInstaller) -and -not $NoSkills) {
        Step "Skills for Claude"
        $ErrorActionPreference = "Continue"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $skillInstaller | ForEach-Object { Note "$_" }
        $installed = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($installed -ne 0) { Warn "The skills could not be installed; run $Launcher skills (in $Target) later." }
    }

    # -------------------------------------------------------------- done
    Step "Done"
    if ($Existing) {
        Note "$Product updated: $(if ($OldVersion) { $OldVersion } else { '?' }) -> $NewVersion."
        $log = Join-Path $Target "CHANGELOG.md"
        if ($OldVersion -and (Test-Path -LiteralPath $log)) {
            $newer = @(Select-String -LiteralPath $log -Pattern '^## (.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value } |
                Where-Object { (Compare-Version (($_ -split ' ')[0]) $OldVersion) -gt 0 })
            if ($newer.Count) { Note "What changed: CHANGELOG.md, $($newer -join '; ')" }
        }
        Note "Backup: $backup (delete it once the new version works)."
    } else {
        Note "$Product $NewVersion installed in $Target."
    }
    if ($Start -and -not $createdEnv) {
        # .\ : cmd does not look in the current folder when NoDefaultCurrentDirectoryInExePath is set
        Start-Process -FilePath "cmd.exe" -ArgumentList "/k", ".\$Launcher $StartCommand" -WorkingDirectory $Target
        Note "Started in a window of its own."
    } elseif ($Start) {
        Note "Not started: edit .env first, then run: $Launcher $StartCommand (in $Target)."
    } else {
        Note "Start it with: $Launcher $StartCommand (in $Target)."
    }
} finally {
    if ($Unzipped -and (Test-Path -LiteralPath $Unzipped)) { Remove-Item -LiteralPath $Unzipped -Recurse -Force }
}
