# Full test suite on PostgreSQL (Windows equivalent of `make test-pg`; docs/adr/0003).
#
#   .\scripts\test-pg.ps1                 # Testcontainers postgres:16.4 (needs Docker)
#   .\scripts\test-pg.ps1 -UseSirdbEnv    # the local ccre-sirdb container, URL from deploy\sirdb.env
#
# A throw-away database is created for the run and dropped afterwards; loaded data is never touched.
param([switch]$UseSirdbEnv)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($UseSirdbEnv) {
    $line = Select-String -Path "deploy\sirdb.env" -Pattern "^SIRDB_DATABASE_URL=" | Select-Object -First 1
    if ($null -eq $line) { throw "SIRDB_DATABASE_URL not found in deploy\sirdb.env" }
    $env:CCRE_TEST_PG_URL = $line.Line.Substring("SIRDB_DATABASE_URL=".Length)
}
$env:CCRE_LLM_MODE = "stub"
$env:CCRE_TEST_PG = "1"
& .\.venv\Scripts\python.exe -m pytest tests -q
exit $LASTEXITCODE
