param(
    [string]$OutputDir,
    [string]$PackageName = "HQ_DFM_kicad_plugin",
    [switch]$IncludeDocs
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "dist"
}

$outputDirFull = if (Test-Path $OutputDir) {
    (Resolve-Path $OutputDir).Path
} else {
    (New-Item -ItemType Directory -Path $OutputDir).FullName
}

$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("hqdfm-plugin-" + [System.Guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $outputDirFull ($PackageName + ".zip")
$unpackedPath = Join-Path $outputDirFull $PackageName

$includeRoots = @("__init__.py", "__main__.py", "kicad_dfm")
if ($IncludeDocs) {
    $includeRoots += "docs"
}

$excludedDirs = @(
    ".codegraph",
    ".git",
    ".idea",
    ".pytest_cache",
    ".vscode",
    "__pycache__",
    "build",
    "dist"
)

$excludedExtensions = @(
    ".fbp",
    ".log",
    ".po",
    ".pot",
    ".pyc",
    ".pyo",
    ".tmp"
)

$excludedNames = @(
    ".DS_Store",
    "generate_param_mapping.py",
    "geni18n.py",
    "Thumbs.db",
    "temp.json"
)

function Test-Excluded {
    param(
        [System.IO.FileSystemInfo]$Item
    )

    if ($Item.PSIsContainer -and $excludedDirs -contains $Item.Name) {
        return $true
    }
    if (-not $Item.PSIsContainer -and $excludedExtensions -contains $Item.Extension) {
        return $true
    }
    if ($excludedNames -contains $Item.Name) {
        return $true
    }
    try {
        $relative = Get-RelativePackagePath $repoRoot $Item.FullName
        foreach ($part in $relative.Split("/")) {
            if ($excludedDirs -contains $part) {
                return $true
            }
        }
    } catch {
        return $true
    }

    return $false
}

function ConvertTo-ZipEntryName {
    param(
        [string]$Name
    )

    $entryName = $Name.Replace("\", "/")
    if ([string]::IsNullOrWhiteSpace($entryName) -or $entryName.StartsWith("/") -or $entryName.Contains(":")) {
        throw "Invalid ZIP entry path: $Name"
    }
    foreach ($part in $entryName.Split("/")) {
        if ([string]::IsNullOrEmpty($part) -or $part -eq "." -or $part -eq "..") {
            throw "Invalid ZIP entry path: $Name"
        }
    }

    return $entryName
}

function Get-RelativePackagePath {
    param(
        [string]$BasePath,
        [string]$Path
    )

    $baseUri = [System.Uri]((Resolve-Path $BasePath).Path.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar)
    $pathUri = [System.Uri](Resolve-Path $Path).Path

    return ConvertTo-ZipEntryName ([System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($pathUri).ToString()
    ))
}

function Assert-ZipEntryNames {
    param(
        [string]$ArchivePath
    )

    $zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $zip.Entries) {
            $entryName = ConvertTo-ZipEntryName $entry.FullName
            $entryParts = $entryName.Split("/")
            if ($entryParts | Where-Object { $_ -in @("docs", "tests", "tools", "script") }) {
                throw "Development-only directory found in release: $entryName"
            }
            if ($entry.Extension -in @(".fbp", ".po", ".pot", ".pyc", ".pyo")) {
                throw "Development-only file found in release: $entryName"
            }
            if ($entry.Name -in @("generate_param_mapping.py", "geni18n.py")) {
                throw "Development-only file found in release: $entryName"
            }
        }
        return $zip.Entries.Count
    } finally {
        $zip.Dispose()
    }
}

function Copy-PackageItem {
    param(
        [string]$RelativePath
    )

    $sourcePath = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path $sourcePath)) {
        throw "Required package path not found: $RelativePath"
    }

    $sourceItem = Get-Item -LiteralPath $sourcePath
    if (Test-Excluded $sourceItem) {
        return
    }

    if (-not $sourceItem.PSIsContainer) {
        $destPath = Join-Path $stageRoot $RelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destPath) -Force | Out-Null
        Copy-Item -LiteralPath $sourceItem.FullName -Destination $destPath -Force
        return
    }

    Get-ChildItem -LiteralPath $sourceItem.FullName -Recurse -Force |
        Where-Object { -not (Test-Excluded $_) } |
        ForEach-Object {
            $relative = Get-RelativePackagePath $repoRoot $_.FullName
            $destPath = Join-Path $stageRoot $relative

            if ($_.PSIsContainer) {
                New-Item -ItemType Directory -Path $destPath -Force | Out-Null
            } else {
                New-Item -ItemType Directory -Path (Split-Path -Parent $destPath) -Force | Out-Null
                Copy-Item -LiteralPath $_.FullName -Destination $destPath -Force
            }
        }
}

try {
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

    foreach ($root in $includeRoots) {
        Copy-PackageItem $root
    }

    if (Test-Path $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open($archivePath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem -LiteralPath $stageRoot -Recurse -File |
            ForEach-Object {
                $entryName = Get-RelativePackagePath $stageRoot $_.FullName
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $archive,
                    $_.FullName,
                    $entryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
    } finally {
        $archive.Dispose()
    }

    if (Test-Path $unpackedPath) {
        Remove-Item -LiteralPath $unpackedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $unpackedPath -Force | Out-Null
    Copy-Item -Path (Join-Path $stageRoot "*") -Destination $unpackedPath -Recurse -Force

    $entryCount = Assert-ZipEntryNames $archivePath
    Write-Host "Created: $archivePath"
    Write-Host "Copied unpacked: $unpackedPath"
    Write-Host "Entries: $entryCount"
    Write-Host "Install: extract this zip into KiCad's scripting/plugins directory."
} finally {
    if (Test-Path $stageRoot) {
        $resolvedStage = (Resolve-Path $stageRoot).Path
        if ($resolvedStage.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
}
