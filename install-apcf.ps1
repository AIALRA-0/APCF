# Public APCF bootstrap; downloads data only, never pipes remote code to Invoke-Expression.
# Usage: pwsh -NoProfile -File .\install-apcf.ps1 -ProjectRoot "D:\Projects\my-project"
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [string]$Tag = 'v0.3.1'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ExpectedTag = 'v0.3.1'
if ($Tag -cne $ExpectedTag) { throw "This installer pins $ExpectedTag; use the matching release instead of an unverified tag." }
$target = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Target must be a real existing project directory.' }
if ((Test-Path -LiteralPath (Join-Path $target 'AGENTS.md')) -or (Test-Path -LiteralPath (Join-Path $target '.agent-project-control'))) {
    throw 'Project already has an Agent/APCF entry. Stop and let your Agent reconcile rules; no files were changed.'
}
$git = Join-Path $target '.git'
if (Test-Path -LiteralPath $git) {
    $staged = & git -C $target diff --cached --name-only 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing Git index. Stop.' }
    Write-Host 'Git repository detected; existing index and source files will not be rewritten.'
}
$asset = 'APCF-Deploy-v0.3.1.zip'
$base = "https://github.com/AIALRA-0/APCF/releases/download/$Tag"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ('apcf-bootstrap-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp -ErrorAction Stop | Out-Null
try {
    $archive = Join-Path $temp $asset
    $checksumFile = Join-Path $temp ($asset + '.sha256')
    Invoke-WebRequest -Uri "$base/$asset" -OutFile $archive -ErrorAction Stop
    Invoke-WebRequest -Uri "$base/$asset.sha256" -OutFile $checksumFile -ErrorAction Stop
    $line = (Get-Content -LiteralPath $checksumFile -Raw -ErrorAction Stop).Trim()
    if (-not ($line -cmatch ('^([0-9a-f]{64})  ' + [regex]::Escape($asset) + '$'))) { throw 'Invalid exact release SHA-256 checksum record.' }
    $expected = $Matches[1]
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actual -cne $expected) { throw 'Checksum mismatch. No install performed.' }
    $expanded = Join-Path $temp 'expanded'
    New-Item -ItemType Directory -Path $expanded | Out-Null
    # A separate Python ZIP-path verifier must run before extraction for untrusted archives.
    $inspect = @'
import os,sys,zipfile,stat,unicodedata,re
p=sys.argv[1]
seen=set()
reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
with zipfile.ZipFile(p) as z:
    if z.testzip(): raise SystemExit('Release ZIP CRC error')
    for m in z.infolist():
        n=m.orig_filename
        if not n or n.startswith('/') or '\\' in n or any(x in ('','.','..') or x.endswith(('.', ' ')) for x in n.strip('/').split('/')) or re.match(r'^[A-Za-z]:',n): raise SystemExit('Unsafe path: '+repr(n))
        if any(ord(c)<32 or c in '<>:"|?*' for c in n) or any(x.split('.')[0].upper() in reserved for x in n.strip('/').split('/')): raise SystemExit('Illegal Windows path')
        if (m.external_attr>>16)&0o170000 not in (0,stat.S_IFREG,stat.S_IFDIR): raise SystemExit('Unsafe special file')
        k=unicodedata.normalize('NFC',n).casefold()
        if k in seen: raise SystemExit('Duplicate archive path')
        seen.add(k)
    required={'AGENTS.md','.agent-project-control/framework.yaml','.agent-project-control/scripts/bootstrap.py','APCF-START.md','.agent-project-control/interfaces/APCF_ONBOARDING.md'}
    if not required.issubset({m.filename for m in z.infolist() if not m.is_dir()}): raise SystemExit('Release is missing a required Core/onboarding entry')
'@
    $py = Get-Command python -ErrorAction Stop
    $check = Join-Path $temp 'verify_archive.py'
    [System.IO.File]::WriteAllText($check,$inspect,[System.Text.UTF8Encoding]::new($false))
    & $py.Source -B $check $archive
    if ($LASTEXITCODE -ne 0) { throw 'Archive security preflight failed.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -ErrorAction Stop
    $bootstrap = Join-Path $expanded '.agent-project-control\scripts\bootstrap.py'
    if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) { throw 'Release archive is missing bootstrap.py.' }
    if (-not (Test-Path -LiteralPath (Join-Path $expanded 'APCF-START.md'))) { throw 'Release archive is missing the one-line onboarding prompt.' }
    & $py.Source -B $bootstrap --help
    if ($LASTEXITCODE -ne 0) { throw 'The Core bootstrap contract could not be read.' }
    & $py.Source -B $bootstrap $target
    if ($LASTEXITCODE -ne 0) { throw 'The official Core bootstrap rejected the target. Original project files are not overwritten.' }
    Write-Host "Installed APCF into: $target"
    Write-Host 'Next: ask your Agent to read .agent-project-control/interfaces/APCF_ONBOARDING.md and complete the first Pilot.'
}
finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($temp)
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedTemp.StartsWith($tempRoot,[System.StringComparison]::OrdinalIgnoreCase) -or -not ([System.IO.Path]::GetFileName($resolvedTemp) -match '^apcf-bootstrap-[0-9a-f]{32}$')) { throw 'Refusing cleanup outside the installer temporary directory.' }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
