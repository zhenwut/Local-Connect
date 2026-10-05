param([string]$Folder)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if (Get-Process WINWORD,EXCEL,POWERPNT -ErrorAction SilentlyContinue) { throw 'Close Office before running this optional fixture test.' }
New-Item -ItemType Directory -Force -Path $Folder | Out-Null
foreach ($program in @('Word', 'Excel', 'PowerPoint')) {
    Write-Output "Starting $program"
    $app = $null
    $doc = $null
    try {
        $app = New-Object -ComObject ($program + '.Application')
        Write-Output "Created $program"
        $app.AutomationSecurity = 3
        if ($program -eq 'Word') {
            $app.Visible = $false
            $app.DisplayAlerts = 0
            $doc = $app.Documents.Add()
            Write-Output 'Created Word document'
            $doc.Content.Text = "Local Connect Word page 1`fLocal Connect Word page 2"
            Write-Output 'Set Word text'
            [object]$savePath = [string](Join-Path $Folder 'sample.docx')
            [object]$saveFormat = [int]16
            $doc.SaveAs2([ref]$savePath, [ref]$saveFormat)
            Write-Output 'Saved DOCX'
            [object]$savePath = [string](Join-Path $Folder 'sample.doc')
            [object]$saveFormat = [int]0
            $doc.SaveAs2([ref]$savePath, [ref]$saveFormat)
            $doc.Close([ref]([object]0))
        } elseif ($program -eq 'Excel') {
            $app.Visible = $false
            $app.DisplayAlerts = $false
            $doc = $app.Workbooks.Add()
            $doc.Worksheets.Item(1).Cells.Item(1,1) = 'Local Connect Excel first sheet'
            $sheet = $doc.Worksheets.Add()
            $sheet.Cells.Item(1,1) = 'Local Connect Excel second sheet'
            $doc.SaveAs((Join-Path $Folder 'sample.xlsx'), 51)
            $doc.SaveAs((Join-Path $Folder 'sample.xls'), 56)
            $doc.Close($false)
        } else {
            $app.DisplayAlerts = 1
            $doc = $app.Presentations.Add(0)
            $slide = $doc.Slides.Add(1, 1)
            $slide.Shapes.Title.TextFrame.TextRange.Text = 'Local Connect slide one'
            $slide = $doc.Slides.Add(2, 1)
            $slide.Shapes.Title.TextFrame.TextRange.Text = 'Local Connect slide two'
            $doc.SaveAs((Join-Path $Folder 'sample.pptx'), 24)
            $doc.SaveAs((Join-Path $Folder 'sample.ppt'), 1)
            $doc.Close()
        }
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        throw
    } finally {
        if ($doc) {
            try { if ($program -eq 'Word') { $doc.Close([ref]([object]0)) } elseif ($program -eq 'Excel') { $doc.Close($false) } else { $doc.Close() } } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc)
        }
        if ($app) {
            try { if ($program -eq 'Word') { $app.Quit([ref]([object]0)) } else { $app.Quit() } } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)
        }
    }
}
