param([string]$InputPath, [string]$OutputPath, [string]$ProcessRecord, [switch]$Cleanup)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($Cleanup) {
    if (Test-Path -LiteralPath $ProcessRecord) {
        $record = Get-Content -LiteralPath $ProcessRecord -Raw | ConvertFrom-Json
        $ownedProcess = Get-Process -Id $record.id -ErrorAction SilentlyContinue
        if ($ownedProcess -and $ownedProcess.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.started) {
            Stop-Process -Id $ownedProcess.Id -Force
        }
    }
    exit 0
}
$extension = [IO.Path]::GetExtension($InputPath).ToLowerInvariant()
$app = $null
$document = $null
$ownsApp = $false
$before = @(Get-Process WINWORD,EXCEL,POWERPNT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
try {
    $program = switch ($extension) { '.doc' {'Word'} '.docx' {'Word'} '.xls' {'Excel'} '.xlsx' {'Excel'} '.ppt' {'PowerPoint'} '.pptx' {'PowerPoint'} default {throw 'Unsupported Office format'} }
    $app = New-Object -ComObject ($program + '.Application')
    $processName = switch ($program) { 'Word' {'WINWORD'} 'Excel' {'EXCEL'} 'PowerPoint' {'POWERPNT'} }
    $created = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id })
    $ownsApp = $created.Count -eq 1
    if (-not $ownsApp) { throw 'Please close the Office application before converting this file.' }
    $ownedProcess = $created[0]
    $appProcessId = $ownedProcess.Id
    @{id=$appProcessId; started=$ownedProcess.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json -Compress | Set-Content -LiteralPath $ProcessRecord -Encoding UTF8
    $app.AutomationSecurity = 3
    if ($program -eq 'Word') {
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $app.Options.UpdateLinksAtOpen = $false
        [object]$missing = [Type]::Missing
        [object]$yes = $true
        [object]$no = $false
        [object]$blank = [string]''
        [object]$source = [string]$InputPath
        $documents = $app.Documents
        # Only the first 12 parameters are stable across Word's COM versions.
        $openArgs = [object[]]@($source, $no, $yes, $no, $blank, $blank, $no, $blank, $blank, $missing, $missing, $no)
        $document = $documents.GetType().InvokeMember('Open', [Reflection.BindingFlags]::InvokeMethod, $null, $documents, $openArgs)
        $document.ExportAsFixedFormat($OutputPath, 17, $false, 0)
    } elseif ($program -eq 'Excel') {
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $app.EnableEvents = $false
        $app.AskToUpdateLinks = $false
        $document = $app.Workbooks.Open($InputPath, 0, $true, [Type]::Missing, '', '', $true)
        $document.ExportAsFixedFormat(0, $OutputPath, 0, $true, $false)
    } else {
        $app.DisplayAlerts = 1
        $document = $app.Presentations.Open($InputPath, -1, 0, 0)
        $document.SaveAs($OutputPath, 32)
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($document) {
        try { if ($program -eq 'Word') { $document.Close([ref]([object]0)) } elseif ($program -eq 'Excel') { $document.Close($false) } else { $document.Close() } } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    if ($app) {
        if ($ownsApp) { try { if ($program -eq 'Word') { $app.Quit([ref]([object]0)) } else { $app.Quit() } } catch {} }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)
    }
}
