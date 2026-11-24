<#
.SYNOPSIS
    Builds a self-contained, deployable copy of the ArchiMate MCP server.

.DESCRIPTION
    Copies only the files needed to install and run the server (source,
    requirements, run_server.py, launcher, deploy.ps1, README.md,
    CHANGELOG.md and ACCESS_RIGHTS.md) into a new "ArchiMateMCP_<timestamp>" folder, leaving out
    dev-only material (tests/, requirements-dev.txt, runtests.ps1, the
    working documents IMPROVEMENTS.md and PLAN.md, caches, .env, git
    metadata). MANIFEST.txt lists the
    package's files, for deploy.ps1. Optionally zips the result.

.PARAMETER OutputDir
    Directory under which the timestamped package folder/zip are created.
    Defaults to "dist" under the project root (created if missing).

.PARAMETER NoZip
    Skip creating the .zip archive; only produce the plain folder.

.PARAMETER KeepFolder
    Keep the uncompressed package folder next to the .zip. Defaults to $false:
    the folder is only where the package is put together, and is deleted once
    the .zip has been created. Pass -KeepFolder to keep it.

.EXAMPLE
    .\createinstallpackage.ps1

.EXAMPLE
    .\createinstallpackage.ps1 -OutputDir C:\Releases -KeepFolder
#>
[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [switch]$NoZip,
    [switch]$KeepFolder
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
# Resolved here, not as the parameter's default: under "powershell -File" (Git
# Bash, scheduled tasks) $PSScriptRoot is still empty in the param() block.
if (-not $OutputDir) { $OutputDir = Join-Path $ProjectRoot "dist" }
# Absolute, since \\?\ paths (see Long) are not resolved against the current folder.
$OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
$Timestamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$PackageName = "ArchiMateMCP_$Timestamp"
$PackagePath = Join-Path $OutputDir $PackageName

# Files/folders that make up a runnable install — everything else (tests,
# dev-only requirements, working documents such as IMPROVEMENTS.md and PLAN.md,
# caches, secrets, git metadata) is left behind.
# Of the documents, only README.md, CHANGELOG.md, ACCESS_RIGHTS.md and REAL_USE_TESTS.md go in.
$IncludeDirs = @("app")
$IncludeFiles = @(
    "requirements.txt",
    ".env.example",
    "deploy.ps1",
    "archimatemcp.bat",
    "run_server.py",
    "README.md",
    "CHANGELOG.md",
    "ACCESS_RIGHTS.md",
    "LICENSE",
    "REAL_USE_TESTS.md"
)
# Left out of the included folders (none yet).
$ExcludeFiles = @()

# Windows PowerShell 5.1 refuses paths of 260 characters or more, which a deep
# -OutputDir reaches quickly (img\sprites\... in the browser's package). Every
# path written to goes through Long: with the \\?\ prefix, .NET takes any length.
function Long([string]$Path) {
    if ($Path.StartsWith("\\?\")) { return $Path }
    if ($Path.StartsWith("\\")) { return "\\?\UNC\" + $Path.Substring(2) }
    return "\\?\" + $Path
}

# Copy a directory tree without Python's caches: __pycache__ folders are not
# entered and *.pyc / *.pyo files are left out. $ExcludeFiles are left out too.
function Copy-Tree([string]$Source, [string]$Destination) {
    [void][System.IO.Directory]::CreateDirectory((Long $Destination))
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            if ($item.Name -ne "__pycache__") { Copy-Tree $item.FullName $target }
        } elseif ($item.Extension -notin ".pyc", ".pyo" -and $item.Name -notin $ExcludeFiles) {
            [System.IO.File]::Copy($item.FullName, (Long $target), $true)
        }
    }
}

Write-Host "Building install package: $PackagePath"

[void][System.IO.Directory]::CreateDirectory((Long $PackagePath))

foreach ($dir in $IncludeDirs) {
    $src = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $src)) {
        Write-Warning "Skipping missing directory: $dir"
        continue
    }
    $dst = Join-Path $PackagePath $dir
    Copy-Tree $src $dst
}

foreach ($file in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $file
    if (-not (Test-Path $src)) {
        Write-Warning "Skipping missing file: $file"
        continue
    }
    [System.IO.File]::Copy($src, (Long (Join-Path $PackagePath $file)), $true)
}

# MANIFEST.txt: every file of the package, so that deploy.ps1 knows which files
# of an installation came with it (and may be replaced or deleted by an update).
$files = Get-ChildItem -LiteralPath $PackagePath -Recurse -File -Force |
    ForEach-Object { $_.FullName.Substring($PackagePath.Length + 1) } | Sort-Object
$header = "# Files of $PackageName, installed by deploy.ps1. One path per line."
[System.IO.File]::WriteAllLines((Long (Join-Path $PackagePath "MANIFEST.txt")), [string[]](@($header) + $files))

Write-Host "Package folder ready: $PackagePath"

if (-not $NoZip) {
    $ZipPath = "$PackagePath.zip"
    if ([System.IO.File]::Exists((Long $ZipPath))) {
        [System.IO.File]::Delete((Long $ZipPath))
    }
    # The folder's content at the top of the archive, as Compress-Archive "folder\*" had it.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory((Long $PackagePath), (Long $ZipPath),
        [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Write-Host "Zip archive ready:   $ZipPath"

    if (-not $KeepFolder) {
        [System.IO.Directory]::Delete((Long $PackagePath), $true)
        Write-Host "Removed the uncompressed folder (-KeepFolder keeps it)."
    }
}

Write-Host "Done."
