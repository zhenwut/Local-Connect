"""Optional real Office/Chrome test, creates only disposable sample documents."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pdf_convert import ROOT, convert, run_hidden
from pypdf import PdfReader

folder = ROOT / '.ui-artifacts' / 'conversions'
folder.mkdir(parents=True, exist_ok=True)
if not all((folder / ('sample.' + extension)).is_file() for extension in ('doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx')):
    run_hidden(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                str(ROOT / 'tests' / 'office_fixtures.ps1'), '-Folder', str(folder)], timeout=90)
for extension in ('docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt'):
    source = folder / ('sample.' + extension)
    output = folder / (extension + '.pdf')
    convert([{'name': source.name, 'path': source, 'bytes': source.stat().st_size}], output)
    reader = PdfReader(output)
    assert len(reader.pages) == 2, (extension, len(reader.pages))
    assert 'Local Connect' in reader.pages[0].extract_text(), extension
    print(extension + ': two complete pages OK', flush=True)
source = folder / 'sample.html'
source.write_text('<h1>Local Connect HTML</h1><script>document.body.innerHTML="BAD"</script><p style="page-break-before:always">Second page</p>', encoding='utf-8')
output = folder / 'html.pdf'
convert([{'name': source.name, 'path': source, 'bytes': source.stat().st_size}], output)
reader = PdfReader(output)
assert len(reader.pages) == 2
assert 'Local Connect' in reader.pages[0].extract_text()
assert 'BAD' not in ''.join(page.extract_text() for page in reader.pages)
print('HTML: two pages, script blocked OK', flush=True)
