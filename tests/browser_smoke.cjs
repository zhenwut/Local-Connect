/* Optional real Chrome test. Run: node tests/browser_smoke.cjs */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const readline = require('node:readline');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'local-connect-ui-'));
const output = path.join(root, '.ui-artifacts');
fs.mkdirSync(output, { recursive: true });
const browserPath = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const fixture = spawn('python', [path.join(__dirname, 'browser_fixture.py')], { cwd: root, windowsHide: true });
let browser, socket;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try { if (await check()) return; } catch {} // Navigation may replace the JS context.
    await pause(100);
  }
  throw new Error('Timed out: ' + label);
}

(async () => {
  const fixtureData = await new Promise((resolve, reject) => {
    const lines = readline.createInterface({ input: fixture.stdout });
    lines.once('line', line => { lines.close(); resolve(JSON.parse(line)); });
    fixture.once('error', reject);
    fixture.stderr.on('data', data => process.stderr.write(data));
  });
  browser = spawn(browserPath, ['--headless=new', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', '--disable-extensions', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true });
  const endpoint = await new Promise((resolve, reject) => {
    let text = '';
    browser.stderr.on('data', data => {
      text += data.toString();
      const match = text.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) resolve(match[1]);
    });
    browser.once('error', reject);
    browser.once('exit', code => reject(new Error('Chrome exited: ' + code)));
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0;
  const pending = new Map(), errors = [];
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const task = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) task.reject(new Error(message.error.message)); else task.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  };
  const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const requestId = ++id;
    pending.set(requestId, { resolve, reject });
    socket.send(JSON.stringify({ id: requestId, method, params, sessionId }));
  });
  const targets = new Map();
  async function page(url, width, height) {
    const { targetId } = await call('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await call('Target.attachToTarget', { targetId, flatten: true });
    targets.set(sessionId, targetId);
    await call('Page.enable', {}, sessionId);
    await call('Runtime.enable', {}, sessionId);
    await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 }, sessionId);
    await call('Page.navigate', { url }, sessionId);
    return sessionId;
  }
  async function evaluate(sessionId, expression) {
    const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId);
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
  const pc = await page(fixtureData.url + '/receiver', 1150, 1400);
  await until(() => evaluate(pc, "typeof receiverReady !== 'undefined' && receiverReady"), 'receiver registered');
  await until(() => evaluate(pc, "connectSteps.dataset.stage === '1' && connectQr.complete && connectQr.naturalWidth > 0"), 'first scan reflected in timeline');
  const qrBeforeArrival = await evaluate(pc, "connectQr.src");
  const firstScanCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, pc);
  fs.writeFileSync(path.join(output, 'connection-first-scan.png'), Buffer.from(firstScanCapture.data, 'base64'));
  await call('Page.bringToFront', {}, pc);
  await evaluate(pc, "resetTimeline(); updateTimeline('wifi', false); updateTimeline('web', false)");
  const progressBefore = await evaluate(pc, "timelineProgress");
  await pause(350);
  const progressAfter = await evaluate(pc, "timelineProgress");
  assert(progressAfter > progressBefore && progressAfter < 1, `line did not advance after hotspot scan: ${progressBefore} → ${progressAfter}`);
  assert.equal(await evaluate(pc, "timelineStage === 1 && !connectSteps.classList.contains('is-complete')"), true);
  const midScanCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, pc);
  fs.writeFileSync(path.join(output, 'connection-line-moving.png'), Buffer.from(midScanCapture.data, 'base64'));
  await until(() => evaluate(pc, "timelineProgress === 1"), 'line fills after first scan');
  assert.equal(await evaluate(pc, "connectSteps.classList.contains('is-complete')"), false);
  const phone = await page(fixtureData.url + '/#code=ABCD2345', 390, 844);
  await until(() => evaluate(phone, "!!document.getElementById('photos') && typeof LocalFiles !== 'undefined'"), 'phone ready');
  for (const target of [pc, phone]) {
    assert.equal(await evaluate(target, "document.documentElement.lang"), 'zh-CN');
    assert.equal(await evaluate(target, "document.querySelector('.brand-mark')"), null);
    await evaluate(target, "document.getElementById('language-toggle').click()");
    assert.equal(await evaluate(target, "document.documentElement.lang"), 'en');
    assert.equal(await evaluate(target, "document.querySelector('h1').textContent"), target === pc ? 'Receive workspace' : 'Send to computer');
    await evaluate(target, "document.getElementById('language-toggle').click()");
    assert.equal(await evaluate(target, "document.documentElement.lang"), 'zh-CN');
  }
  assert.equal((await fetch(fixtureData.url + '/api/send', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: 'ABCD2345', text: '发送到电脑' })
  })).status, 200);
  await until(() => evaluate(pc, "document.getElementById('text').textContent === '发送到电脑'"), 'user text received');
  await evaluate(pc, "document.getElementById('language-toggle').click()");
  assert.equal(await evaluate(pc, "document.getElementById('text').textContent"), '发送到电脑');
  await evaluate(pc, "document.getElementById('language-toggle').click()");
  await until(async () => (await (await fetch(fixtureData.url + '/api/connect')).json()).phone_opened, 'second QR arrival reported');
  await until(() => evaluate(pc, "connectSteps.dataset.stage === '2' && connectSteps.classList.contains('is-complete')"), 'second scan lights second node');
  assert.equal(await evaluate(pc, "connectQr.src"), qrBeforeArrival);
  await call('Page.bringToFront', {}, pc);
  assert.equal(await evaluate(pc, "!webStep.hasAttribute('aria-current')"), true);
  assert.equal(await evaluate(pc, "timelineProgress"), 1);
  await pause(700);
  const secondScanCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, pc);
  fs.writeFileSync(path.join(output, 'connection-second-scan.png'), Buffer.from(secondScanCapture.data, 'base64'));
  assert.equal(await evaluate(pc, "updateTimeline('wifi', false); connectSteps.dataset.stage === '2' && connectSteps.classList.contains('is-complete')"), true);
  const languageButton = await evaluate(phone, "(() => { const r = document.getElementById('language-toggle').getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()");
  await call('Input.dispatchMouseEvent', { type: 'mouseMoved', ...languageButton }, phone);
  await evaluate(phone, "document.getElementById('language-toggle').click()");
  assert.equal(await evaluate(phone, "getComputedStyle(document.getElementById('language-toggle')).backgroundColor.match(/\\d+/g).slice(0, 3).every(value => Number(value) > 200)"), true);
  await evaluate(phone, "document.getElementById('language-toggle').click()");
  assert.deepEqual(await evaluate(pc, `(() => {
    const qr = document.getElementById('connect-panel').getBoundingClientRect();
    const text = document.querySelector('.text-workspace').getBoundingClientRect();
    const files = document.querySelector('.files-workspace').getBoundingClientRect();
    return { qrAbove: qr.bottom < text.top && qr.bottom < files.top,
      textLeft: text.right < files.left, aligned: Math.abs(text.top - files.top) < 2 };
  })()`), { qrAbove: true, textLeft: true, aligned: true });
  assert.equal(await evaluate(phone, "document.querySelector('.file-picker').getBoundingClientRect().top < document.querySelector('form').getBoundingClientRect().top"), true);
  await call('Emulation.setDeviceMetricsOverride', { width: 700, height: 900, deviceScaleFactor: 1, mobile: false }, pc);
  assert.equal(await evaluate(pc, `(() => {
    const text = document.querySelector('.text-workspace').getBoundingClientRect();
    const files = document.querySelector('.files-workspace').getBoundingClientRect();
    return text.bottom < files.top && document.documentElement.scrollWidth <= window.innerWidth;
  })()`), true);
  await call('Emulation.setDeviceMetricsOverride', { width: 1150, height: 1400, deviceScaleFactor: 1, mobile: false }, pc);
  assert.equal(await evaluate(phone, "document.getElementById('manual-code').hidden"), true);
  assert.equal(await evaluate(phone, "document.getElementById('upload') === null && document.getElementById('retry-upload').hidden"), true);
  const initialPhone = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }, phone);
  fs.writeFileSync(path.join(output, 'phone-initial.png'), Buffer.from(initialPhone.data, 'base64'));
  const { root: documentNode } = await call('DOM.getDocument', {}, phone);
  const { nodeId } = await call('DOM.querySelector', { nodeId: documentNode.nodeId, selector: '#photos' }, phone);
  await evaluate(phone, "codeInput.value = 'WRONG123'");
  await call('DOM.setFileInputFiles', { nodeId, files: fixtureData.files.slice(0, 3) }, phone);
  await until(() => evaluate(phone, "!document.getElementById('retry-upload').hidden && document.querySelector('.upload-row[data-state=error]') !== null"), 'failed upload exposes retry');
  assert.deepEqual(await evaluate(phone, "Array.from(document.querySelectorAll('.upload-row strong'), node => node.textContent)"),
    ['年度报表.xlsx', '项目说明.docx', '照片.jpg']);
  await evaluate(phone, "codeInput.value = 'ABCD2345'; codeInput.dispatchEvent(new Event('input'))");
  await call('DOM.setFileInputFiles', { nodeId, files: fixtureData.files.slice(3) }, phone);
  assert.equal(await evaluate(phone, "document.querySelectorAll('.upload-row').length"), 8);
  await evaluate(phone, "textInput.value = '你好🙂\\nA'; textInput.dispatchEvent(new Event('input')); form.requestSubmit()");
  assert.equal(await evaluate(phone, "document.getElementById('text-count').textContent"), '5 字符');
  await until(() => evaluate(pc, "document.getElementById('text-count').textContent === '5 字符'"), 'received character count');
  await until(() => evaluate(phone, "document.querySelectorAll('.upload-row[data-state=done]').length === 8"), 'uploads complete');
  assert.deepEqual((await (await fetch(fixtureData.url + '/api/latest')).json()).files.map(file => file.name),
    [...fixtureData.files.slice(0, 3).reverse(), ...fixtureData.files.slice(3).reverse()].map(file => path.basename(file)));
  assert.equal(await evaluate(phone, `(() => {
    const name = document.querySelector('.upload-row strong');
    const original = name.textContent;
    name.textContent = '发送到电脑';
    document.getElementById('language-toggle').click();
    const afterSwitch = name.textContent;
    document.getElementById('language-toggle').click();
    name.textContent = original;
    return afterSwitch;
  })()`), '发送到电脑');
  assert.equal(await evaluate(phone, "document.getElementById('retry-upload').hidden"), true);
  await until(() => evaluate(pc, "document.querySelectorAll('.file-card').length === 8"), 'cards received');
  assert.equal(await evaluate(pc, `(() => {
    const colored = Array.from(document.querySelectorAll('.file-icon svg')).map(svg => svg.querySelector('rect').getAttribute('fill'));
    return new Set(colored).size >= 4 && colored.every(color => color !== '#191919');
  })()`), true);
  await evaluate(phone, "document.getElementById('language-toggle').click()");
  assert.equal(await evaluate(phone, "document.getElementById('text-count').textContent"), '5 characters');
  assert.equal(await evaluate(phone, "document.getElementById('photo-status').textContent.includes('files uploaded')"), true);
  await evaluate(phone, "document.getElementById('language-toggle').click()");
  await evaluate(pc, "document.getElementById('language-toggle').click()");
  await until(() => evaluate(pc, "document.getElementById('files-total').textContent.includes('8 original files')"), 'English file summary');
  assert.equal(await evaluate(pc, "document.getElementById('pdf-support').textContent.startsWith('Images, PDF')"), true);
  assert.equal(await evaluate(pc, "document.querySelector('.file-card').title.startsWith('Download ')"), true);
  await evaluate(pc, "document.getElementById('language-toggle').click()");
  assert.equal(await evaluate(pc, "Math.abs(document.querySelector('.text-workspace').getBoundingClientRect().height - document.querySelector('.files-workspace').getBoundingClientRect().height) < 2"), true);
  assert.equal(await evaluate(pc, "document.querySelectorAll('.file-download').length === 0"), true);
  await call('Page.bringToFront', {}, pc);
  await evaluate(pc, "document.getElementById('file-list').scrollIntoView()");
  await until(() => evaluate(pc, "document.querySelectorAll('.file-preview').length === 1 && document.querySelector('.file-preview').naturalWidth > 0"), 'image rendering and broken-image fallback');
  const imageCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }, pc);
  fs.writeFileSync(path.join(output, 'receiver-image.png'), Buffer.from(imageCapture.data, 'base64'));
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.file-preview')).objectFit === 'cover'"), true);
  assert.equal(await evaluate(pc, "(() => { const card = document.querySelector('.file-preview').closest('.file-item'); const box = card.querySelector('.file-select'); const style = getComputedStyle(box); const insetX = box.getBoundingClientRect().left - card.getBoundingClientRect().left; const insetY = box.getBoundingClientRect().top - card.getBoundingClientRect().top; return insetX >= 8 && insetX <= 12 && insetY >= 8 && insetY <= 12 && style.boxShadow === 'none' && style.borderRadius === '6px' && style.appearance === 'none' && !card.querySelector('.file-select-wrap'); })()"), true);
  assert.equal(await evaluate(pc, "document.querySelector('.file-preview').parentElement.querySelector('.file-size').textContent === '644 B'"), true);
  assert.equal(await evaluate(pc, "document.querySelectorAll('.file-size').length"), 8);
  assert.equal(await evaluate(phone, "document.documentElement.scrollWidth <= window.innerWidth"), true);
  const downloaded = path.join(output, '年度报表.xlsx');
  if (fs.existsSync(downloaded)) fs.unlinkSync(downloaded);
  await call('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: output });
  const photoDownload = path.join(output, '照片.jpg');
  if (fs.existsSync(photoDownload)) fs.unlinkSync(photoDownload);
  await evaluate(pc, "document.querySelector('.file-preview').click()");
  await until(() => fs.existsSync(photoDownload), 'clicking image downloads original file');
  assert.equal(fs.readFileSync(photoDownload).equals(fs.readFileSync(fixtureData.files[0])), true);
  await evaluate(pc, "Array.from(document.querySelectorAll('.file-card')).find(a => a.download.endsWith('.xlsx')).click()");
  await until(() => fs.existsSync(downloaded), 'card download');
  assert.equal(fs.readFileSync(downloaded, 'utf8'), 'sample-excel-data');
  assert.equal(await evaluate(pc, "document.getElementById('make-pdf') === null"), true);
  await evaluate(pc, "document.getElementById('add-pdf').click()");
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-container').length === 1"), 'first PDF container');
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.pdf-badge')).backgroundColor"), 'rgb(207, 56, 69)');
  assert.equal(await evaluate(pc, "document.getElementById('add-pdf').disabled"), true);
  await evaluate(pc, "document.querySelector('.pdf-close').click()");
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-container').length === 0"), 'delete pdf1');
  await evaluate(pc, "document.getElementById('add-pdf').click()");
  await until(() => evaluate(pc, "document.querySelector('.pdf-name')?.textContent === 'pdf1'"), 'reuse pdf1 after deletion');
  async function drag(extension, targetIndex = 0) {
    await evaluate(pc, `(() => {
      const source = Array.from(document.querySelectorAll('.file-card')).find(a => a.download.endsWith('${extension}'));
      const target = document.querySelectorAll('.pdf-container')[${targetIndex}];
      const data = new DataTransfer();
      source.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:data}));
      target.dispatchEvent(new DragEvent('dragover', {bubbles:true, dataTransfer:data}));
      target.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:data}));
      source.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer:data}));
    })()`);
  }
  const receivedImageWidth = await evaluate(pc, "document.querySelector('.file-preview').getBoundingClientRect().width");
  await drag('.jpg');
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-member').length === 1"), 'JPG moved into container');
  const expanded = await evaluate(pc, "(() => { const card = document.querySelector('.pdf-container.image-container'); return { width: card.getBoundingClientRect().width, grid: document.querySelector('.file-grid').getBoundingClientRect().width, tile: card.querySelector('.pdf-thumbnail').getBoundingClientRect().width }; })()");
  assert(expanded.width > 600 && Math.abs(expanded.width - expanded.grid) < 2 && expanded.tile >= receivedImageWidth * .85 && expanded.tile <= 190);
  assert.equal(await evaluate(pc, "document.querySelector('.pdf-expand, .pdf-container.wide') === null"), true);
  assert.equal(await evaluate(pc, "document.querySelector('.image-tile').children.length === 1 && !document.querySelector('.image-tile .pdf-member-name, .image-tile .pdf-member-size')"), true);
  await evaluate(pc, "document.querySelector('.pdf-preview-trigger').click()");
  await until(() => evaluate(pc, "document.querySelector('.pdf-image-dialog').open && document.querySelector('.pdf-image-dialog img').naturalWidth > 0"), 'full image preview');
  assert.equal(await evaluate(pc, "document.querySelector('.pdf-image-dialog img').src.endsWith('/preview') && document.querySelector('.pdf-image-dialog-title').textContent === '照片.jpg'"), true);
  const previewCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, pc);
  fs.writeFileSync(path.join(output, 'pdf-image-preview.png'), Buffer.from(previewCapture.data, 'base64'));
  await evaluate(pc, "document.querySelector('.pdf-image-dialog img').src = '/api/files/missing/thumbnail'");
  await until(() => evaluate(pc, "document.querySelector('.pdf-image-dialog img').hidden && document.querySelector('.pdf-image-dialog-stage').dataset.error"), 'failed preview shows error');
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.pdf-image-dialog img')).display"), 'none');
  await evaluate(pc, "document.querySelector('.pdf-image-dialog-close').click()");
  assert.equal(await evaluate(pc, "document.querySelector('.pdf-image-dialog').open"), false);
  assert.equal(await evaluate(pc, "(() => { const card = document.querySelector('.pdf-container.has-members'); const action = card.querySelector('.pdf-body'); return Math.abs(card.getBoundingClientRect().bottom - action.getBoundingClientRect().bottom) < 4; })()"), true);
  assert.equal(await evaluate(pc, "document.querySelector('.pdf-container.has-members .pdf-badge') === null && document.querySelector('.pdf-container.has-members .pdf-hint') === null && document.querySelector('.pdf-container.has-members .pdf-download-label').textContent === '下载 PDF'"), true);
  assert.equal(await evaluate(pc, "document.querySelectorAll('.file-card').length"), 7);
  assert.match(await evaluate(pc, "document.getElementById('files-total').textContent"), /^8 /);
  await evaluate(pc, `(() => {
    const source = document.querySelector('.pdf-member');
    const target = document.querySelector('.file-card');
    const data = new DataTransfer();
    source.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:data}));
    target.dispatchEvent(new DragEvent('dragover', {bubbles:true, dataTransfer:data}));
    target.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:data}));
    source.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer:data}));
  })()`);
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-member').length === 0 && Array.from(document.querySelectorAll('.file-card')).some(a => a.download === '照片.jpg')"), 'drag member out restores original card');
  await drag('.jpg');
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-member').length === 1"), 'restored file can rejoin PDF');
  await drag('.docx');
  await until(() => evaluate(pc, "document.getElementById('files-status').textContent.includes('相同格式')"), 'mixed format rejected');
  assert.equal(await evaluate(pc, "document.querySelectorAll('.pdf-member').length"), 1);
  await evaluate(pc, "document.querySelector('.pdf-name').click()");
  assert.equal(await evaluate(pc, "(() => { const input = document.querySelector('.pdf-rename').getBoundingClientRect(); const close = document.querySelector('.pdf-close').getBoundingClientRect(); return Math.abs(input.height - 42) < 2 && Math.abs((input.top + input.bottom) / 2 - (close.top + close.bottom) / 2) < 2 && input.right + 4 <= close.left; })()"), true);
  await evaluate(pc, "document.querySelector('.pdf-rename').value = '我的相册'; document.querySelector('.pdf-rename').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}))");
  await until(() => evaluate(pc, "document.querySelector('.pdf-name').textContent === '我的相册'"), 'rename PDF');
  const pdfPath = path.join(output, '我的相册.pdf');
  if (fs.existsSync(pdfPath)) fs.unlinkSync(pdfPath);
  await evaluate(pc, "document.querySelector('.pdf-body').click()");
  await until(() => fs.existsSync(pdfPath), 'PDF download');
  assert.equal(fs.readFileSync(pdfPath).subarray(0, 5).toString(), '%PDF-');
  await evaluate(pc, "document.getElementById('add-pdf').click()");
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-container').length === 2"), 'second PDF container');
  assert.equal(await evaluate(pc, "document.querySelectorAll('.pdf-name')[1].textContent"), 'pdf2');
  await drag('.xlsx', 1);
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-member').length === 2"), 'second container populated');
  assert.equal(await evaluate(pc, "document.querySelectorAll('.pdf-container')[1].querySelector('.pdf-member .file-icon rect').getAttribute('fill')"), '#218354');
  assert.equal(await evaluate(pc, "Array.from(document.querySelectorAll('.pdf-container.has-members')).every(card => Math.abs(card.getBoundingClientRect().bottom - card.querySelector('.pdf-body').getBoundingClientRect().bottom) < 4)"), true);
  await evaluate(pc, "document.querySelectorAll('.pdf-close')[1].click()");
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-container').length === 1 && Array.from(document.querySelectorAll('.file-card')).some(a => a.download.endsWith('.xlsx'))"), 'remove container restores source');
  const zipPath = path.join(output, 'Local Connect.zip');
  if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
  await evaluate(pc, "document.getElementById('download-all').click()");
  await until(() => fs.existsSync(zipPath), 'download all ZIP');
  // Check ZIP directory names directly (stored entries) without an extra npm dependency.
  const zip = fs.readFileSync(zipPath), zipNames = [];
  for (let offset = 0; offset + 46 <= zip.length; offset++) {
    if (zip.readUInt32LE(offset) !== 0x02014b50) continue;
    const nameLength = zip.readUInt16LE(offset + 28);
    zipNames.push(zip.subarray(offset + 46, offset + 46 + nameLength).toString('utf8'));
  }
  assert.equal(zipNames.length, 8);
  assert.ok(zipNames.includes('我的相册.pdf'));
  assert.ok(!zipNames.includes('照片.jpg'));
  assert.ok(zipNames.includes('年度报表.xlsx'));
  const selectedZip = path.join(output, 'Local Connect 选中.zip');
  function selectedZipNames() {
    const bytes = fs.readFileSync(selectedZip), names = [];
    for (let offset = 0; offset + 46 <= bytes.length; offset++) {
      if (bytes.readUInt32LE(offset) === 0x02014b50) {
        names.push(bytes.subarray(offset + 46, offset + 46 + bytes.readUInt16LE(offset + 28)).toString('utf8'));
      }
    }
    return names.sort();
  }
  if (fs.existsSync(selectedZip)) fs.unlinkSync(selectedZip);
  await evaluate(pc, "Array.from(document.querySelectorAll('.file-card')).find(a => a.download.endsWith('.xlsx')).parentElement.querySelector('.file-select').click()");
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.file-select:checked')).backgroundImage.startsWith('url(')"), true);
  assert.match(await evaluate(pc, "document.getElementById('download-all').textContent"), /下载选中（1 项）/);
  assert.match(await evaluate(pc, "document.getElementById('files-total').textContent"), /已选 1 项/);
  await evaluate(pc, "document.getElementById('download-all').click()");
  await until(() => fs.existsSync(selectedZip), 'selected file ZIP');
  assert.deepEqual(selectedZipNames(), ['年度报表.xlsx']);
  await until(() => evaluate(pc, "!document.getElementById('download-all').disabled"), 'selection download finished');
  fs.unlinkSync(selectedZip);
  await evaluate(pc, "document.querySelector('.pdf-select').click()");
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.pdf-select:checked')).borderRadius"), '6px');
  assert.match(await evaluate(pc, "document.getElementById('download-all').textContent"), /下载选中（2 项）/);
  await evaluate(pc, "document.getElementById('download-all').click()");
  await until(() => fs.existsSync(selectedZip), 'selected file and PDF ZIP');
  assert.deepEqual(selectedZipNames(), ['年度报表.xlsx', '我的相册.pdf'].sort());
  await until(() => evaluate(pc, "!document.getElementById('download-all').disabled"), 'mixed selection download finished');
  await evaluate(pc, "document.querySelectorAll('.file-select:checked, .pdf-select:checked').forEach(input => input.click())");
  assert.equal(await evaluate(pc, "document.getElementById('download-all').textContent"), '一键下载 ZIP ↓');
  await evaluate(pc, "document.querySelector('.pdf-remove-file').click()");
  await until(() => evaluate(pc, "document.querySelectorAll('.file-card').length === 8 && document.querySelectorAll('.pdf-member').length === 0"), 'remove individual member');
  assert.equal(await evaluate(pc, "document.getElementById('add-pdf').disabled"), true);
  await drag('.jpg');
  await until(() => evaluate(pc, "document.querySelectorAll('.pdf-member').length === 1"), 'restore PDF member');
  const uploadedSecond = await evaluate(pc, `(async () => {
    const sourceId = document.querySelector('.pdf-member').dataset.fileId;
    const source = await fetch('/api/files/' + sourceId).then(response => response.blob());
    const response = await fetch('/api/files', {
      method: 'POST', headers: {
        'X-Access-Code': 'ABCD2345', 'X-File-Name': encodeURIComponent('第二张.jpg'),
        'Content-Type': 'application/octet-stream'
      }, body: source
    });
    return response.ok;
  })()`);
  assert.equal(uploadedSecond, true);
  await until(() => evaluate(pc, "Array.from(document.querySelectorAll('.file-card')).some(a => a.download === '第二张.jpg')"), 'second image received');
  await drag('.jpg');
  await until(() => evaluate(pc, "document.querySelectorAll('.image-members .pdf-member').length === 2"), 'two thumbnails');
  await evaluate(pc, "document.querySelector('.image-members').scrollIntoView()");
  await until(() => evaluate(pc, "Array.from(document.querySelectorAll('.pdf-thumbnail img')).every(img => img.naturalWidth > 0)"), 'thumbnails decoded');
  assert.equal(await evaluate(pc, "document.querySelectorAll('.pdf-thumbnail .pdf-rotate').length"), 2);
  await evaluate(pc, `(() => {
    const members = document.querySelectorAll('.image-members .pdf-member');
    const data = new DataTransfer();
    members[1].dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:data}));
    members[0].dispatchEvent(new DragEvent('dragover', {bubbles:true, dataTransfer:data}));
    members[0].dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:data}));
    members[1].dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer:data}));
  })()`);
  await until(() => evaluate(pc, "document.querySelector('.image-members .pdf-member img').alt === '第二张.jpg'"), 'drag reordered image');
  await evaluate(pc, "document.querySelector('.image-members .pdf-member .pdf-rotate').click()");
  await until(() => evaluate(pc, "document.querySelector('.image-members .pdf-member img').style.transform === 'rotate(90deg)'"), 'clockwise preview rotation');
  await evaluate(pc, "document.querySelector('.image-members .pdf-preview-trigger').click()");
  assert.equal(await evaluate(pc, "document.querySelector('.pdf-image-dialog').open && document.querySelector('.pdf-image-dialog img').style.transform.includes('rotate(90deg)')"), true);
  await evaluate(pc, "document.querySelector('.pdf-image-dialog-close').click()");
  if (fs.existsSync(pdfPath)) fs.unlinkSync(pdfPath);
  await evaluate(pc, "document.querySelector('.pdf-body').click()");
  await until(() => fs.existsSync(pdfPath), 'rotated PDF download');
  assert.equal(fs.readFileSync(pdfPath).subarray(0, 5).toString(), '%PDF-');
  async function addMorePhoto(name) {
    const uploaded = await evaluate(pc, `(async () => {
      const sourceId = document.querySelector('.image-members .pdf-member').dataset.fileId;
      const source = await fetch('/api/files/' + sourceId).then(response => response.blob());
      const response = await fetch('/api/files', {
        method: 'POST', headers: {
          'X-Access-Code': 'ABCD2345', 'X-File-Name': encodeURIComponent('${name}'),
          'Content-Type': 'application/octet-stream'
        }, body: source
      });
      return response.ok;
    })()`);
    assert.equal(uploaded, true);
    await until(() => evaluate(pc, "Array.from(document.querySelectorAll('.file-card')).some(card => card.download === '" + name + "')"), name + ' received');
    await drag('.jpg');
    await until(() => evaluate(pc, "document.querySelectorAll('.image-members .pdf-member').length === " + Number(name.match(/\d+/)[0])), name + ' added');
  }
  for (let number = 3; number <= 5; number++) await addMorePhoto(`第${number}张.jpg`);
  const fiveImages = await evaluate(pc, "(() => { const card = document.querySelector('.image-container'); const tiles = Array.from(card.querySelectorAll('.pdf-thumbnail')).map(tile => tile.getBoundingClientRect()); return { width: card.getBoundingClientRect().width, widths: tiles.map(tile => tile.width), firstRow: tiles.filter(tile => Math.abs(tile.y - tiles[0].y) < 2).length }; })()");
  assert.equal(fiveImages.width, expanded.width);
  assert(fiveImages.widths.length === 5 && fiveImages.widths.every(width => Math.abs(width - expanded.tile) < 2));
  assert(fiveImages.firstRow >= 3);
  assert.equal(await evaluate(pc, "fetch('/api/latest').then(response => response.json()).then(data => data.pdf_containers[0].format === 'jpg' && data.pdf_containers[0].file_ids.length === 5)"), true);
  await addMorePhoto('第6张.jpg');
  const sixImages = await evaluate(pc, "(() => { const card = document.querySelector('.image-container'); const tiles = Array.from(card.querySelectorAll('.pdf-thumbnail')).map(tile => tile.getBoundingClientRect()); return { width: card.getBoundingClientRect().width, widths: tiles.map(tile => tile.width), firstRow: tiles.filter(tile => Math.abs(tile.y - tiles[0].y) < 2).length }; })()");
  assert(sixImages.width === expanded.width && sixImages.firstRow === fiveImages.firstRow);
  assert(sixImages.widths.length === 6 && sixImages.widths.every(width => Math.abs(width - expanded.tile) < 2));
  assert.deepEqual(errors, []);
  const capture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }, pc);
  fs.writeFileSync(path.join(output, 'receiver.png'), Buffer.from(capture.data, 'base64'));
  await call('Emulation.setDeviceMetricsOverride', { width: 750, height: 900, deviceScaleFactor: 1, mobile: false }, pc);
  assert.equal(await evaluate(pc, "(() => { const card = document.querySelector('.image-container'); const tiles = Array.from(card.querySelectorAll('.pdf-thumbnail')); return Math.abs(card.getBoundingClientRect().width - document.querySelector('.file-grid').getBoundingClientRect().width) < 2 && tiles.every(tile => tile.getBoundingClientRect().width <= 190) && card.querySelector('.image-members').clientHeight <= 650; })()"), true);
  await call('Emulation.setDeviceMetricsOverride', { width: 600, height: 900, deviceScaleFactor: 1, mobile: false }, pc);
  assert.equal(await evaluate(pc, "(() => { const card = document.querySelector('.image-container'); const strip = card.querySelector('.image-members'); const tiles = Array.from(card.querySelectorAll('.pdf-thumbnail')).map(tile => tile.getBoundingClientRect()); return !card.querySelector('.pdf-expand') && strip.scrollWidth > strip.clientWidth && tiles.every(tile => tile.width <= 190 && Math.abs(tile.y - tiles[0].y) < 2); })()"), true);
  await call('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }, pc);
  assert.equal(await evaluate(pc, "document.documentElement.scrollWidth <= window.innerWidth"), true);
  assert.equal(await evaluate(pc, "(() => { const card = document.querySelector('.image-container'); const strip = card.querySelector('.image-members'); const tiles = Array.from(card.querySelectorAll('.pdf-thumbnail')).map(tile => tile.getBoundingClientRect()); return tiles.length === 6 && tiles.every(tile => tile.width <= 190 && Math.abs(tile.y - tiles[0].y) < 2) && strip.scrollWidth > strip.clientWidth; })()"), true);
  const mobileCapture = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }, pc);
  fs.writeFileSync(path.join(output, 'receiver-mobile.png'), Buffer.from(mobileCapture.data, 'base64'));
  await call('Emulation.setDeviceMetricsOverride', { width: 320, height: 740, deviceScaleFactor: 1, mobile: true }, pc);
  assert.equal(await evaluate(pc, "document.documentElement.scrollWidth <= window.innerWidth"), true);
  assert.equal(await evaluate(pc, "Array.from(document.querySelectorAll('.image-members .pdf-thumbnail')).every(tile => tile.getBoundingClientRect().width <= 190)"), true);
  await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] }, pc);
  assert.equal(await evaluate(pc, "getComputedStyle(document.querySelector('.file-item')).animationName"), 'none');
  await call('Emulation.setEmulatedMedia', { features: [] }, pc);
  await call('Emulation.setDeviceMetricsOverride', { width: 1150, height: 1400, deviceScaleFactor: 1, mobile: false }, pc);
  const oldPageId = await evaluate(pc, 'pageId');
  await call('Page.reload', {}, pc);
  await until(() => evaluate(pc, `typeof receiverReady !== 'undefined' && receiverReady && pageId !== '${oldPageId}'`), 'receiver reload');
  await until(() => evaluate(pc, "document.querySelectorAll('.file-card').length === 0 && document.getElementById('text-count').textContent === '0 字符'"), 'new page clears records');
  assert.equal(await evaluate(pc, "document.getElementById('new-batch') === null"), true);
  const secondPc = await page(fixtureData.url + '/receiver', 1150, 1400);
  await until(() => evaluate(secondPc, "typeof receiverReady !== 'undefined' && receiverReady"), 'second receiver tab');
  await call('Target.closeTarget', { targetId: targets.get(phone) });
  await call('Target.closeTarget', { targetId: targets.get(pc) });
  await pause(9500);
  assert.equal((await fetch(fixtureData.url + '/api/latest')).status, 200);
  await call('Target.closeTarget', { targetId: targets.get(secondPc) });
  await until(async () => {
    try { await fetch(fixtureData.url + '/api/latest', { signal: AbortSignal.timeout(1000) }); return false; }
    catch { return true; }
  }, 'service stops after last receiver tab closes');
  assert.deepEqual(errors, []);
  console.log('Browser OK: automatic phone uploads and retry, bottom-aligned PDF actions, image reorder/rotation, selection ZIPs, reload reset, multiple tabs, shutdown.');
  await call('Browser.close');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (socket) socket.close();
  if (browser && browser.exitCode === null) browser.kill();
  fixture.stdin.end('\n');
  await pause(800);
  if (fixture.exitCode === null) fixture.kill();
  if (path.dirname(profile) !== path.resolve(os.tmpdir()) || !path.basename(profile).startsWith('local-connect-ui-')) {
    throw new Error('Refusing unexpected cleanup path');
  }
  try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 }); } catch {}
});
