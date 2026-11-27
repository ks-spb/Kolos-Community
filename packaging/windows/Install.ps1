param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\KolosRunner'),
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
try {
    $payload = Join-Path $PSScriptRoot 'payload'
    $bundle = Get-Content -Raw -LiteralPath (Join-Path $payload 'build.json') | ConvertFrom-Json
    if ($bundle.version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{12}$') { throw 'Invalid Kolos package version.' }
    $root = [IO.Path]::GetFullPath($InstallDir)
    $install = Join-Path $root $bundle.version
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    if (-not (Test-Path -LiteralPath $install -PathType Container)) {
        $staging = Join-Path $root ('install-' + [guid]::NewGuid().ToString('N'))
        Copy-Item -LiteralPath $payload -Destination $staging -Recurse
        & (Join-Path $staging 'Kolos.cmd') --help | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Kolos could not start from the copied package.' }
        [IO.Directory]::Move($staging, $install)
    }
    if (-not $NoShortcut) {
        $programs = [Environment]::GetFolderPath('Programs')
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $programs 'Kolos.lnk'))
        $shortcut.TargetPath = Join-Path $install 'runtime\pythonw.exe'
        $shortcut.Arguments = '-B -m kolos_states.task_runner gui'
        $shortcut.WorkingDirectory = $install
        $shortcut.Description = 'Kolos task runner'
        $shortcut.Save()
    }
    Write-Output "Kolos installed at $install"
    exit 0
} catch {
    Write-Error -ErrorAction Continue $_
    exit 1
}
