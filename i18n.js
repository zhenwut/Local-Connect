/* Both pages start in Chinese. The language choice lasts for this page only. */
window.LocalI18n = (() => {
  const english = {
    'Local Connect · 电脑接收页': 'Local Connect · Receiver',
    'Local Connect · 手机发送页': 'Local Connect · Sender',
    '电脑接收': 'Computer', '手机发送': 'Phone',
    '接收工作台': 'Receive workspace', '扫码连接手机，文字和文件会直接出现在这里。': 'Scan to connect your phone. Text and files will appear here.',
    '每次打开或刷新此页会清空本次记录；文件仍保存在电脑上。关闭所有接收页后，服务和热点将自动结束。': 'Opening or refreshing this page clears this session. Saved files remain on your computer. Closing all receiver pages stops the service and hotspot.',
    '扫码进度': 'Connection progress', '连接热点': 'Join hotspot', '打开传输页': 'Open transfer page',
    '正在检查连接方式…': 'Checking connection…', '连接二维码': 'Connection QR code',
    '收到的文本': 'Received text', '手机发送的最新文本会显示在这里。': 'The latest text from your phone appears here.',
    '按 Unicode 字符计数，包含空格与换行': 'Unicode characters, including spaces and line breaks',
    '0 字符': '0 characters', '复制文本': 'Copy text', '等待文本…': 'Waiting for text…',
    '收到的文件': 'Received files', '＋ PDF 容器': '＋ PDF container',
    '点击文件可下载；拖入 PDF 容器合并，拖出可恢复原文件。图片支持排序与旋转；勾选后可下载指定文件。': 'Click a file to download it. Drag files into a PDF container to combine them or out to restore them. You can reorder and rotate images, and select files for download.',
    '等待手机上传文件…': 'Waiting for files from your phone…', '收到的文件与 PDF 容器': 'Received files and PDF containers',
    '0 个原文件 · 总大小 0 B': '0 original files · Total 0 B', '一键下载 ZIP ↓': 'Download all as ZIP ↓',
    '发送到电脑': 'Send to computer', '连接电脑热点后，文字和文件可以直接送到电脑。': 'Send text and files directly to your computer over its hotspot.',
    '电脑终端显示的访问码': 'Access code shown on the computer', '上传文件': 'Upload files',
    'TXT、CSV、EPUB、图片、视频等任意格式均可传输；选择后自动上传。': 'Send TXT, CSV, EPUB, images, videos, or any other file. Upload starts after selection.',
    '选择文件上传': 'Choose files', '可一次多选，也可分几次添加': 'Select several at once or add more later',
    '单个文件最多 2 GiB；每批最多 100 个，合计 10 GiB。手机文件管理器通常可长按多选。': 'Up to 2 GiB per file, 100 files and 10 GiB per batch. Long-press in your phone’s file manager to select multiple files.',
    '上传队列': 'Upload queue', '重试未完成的文件': 'Retry unfinished files', '发送文本': 'Send text',
    '电脑接收页会显示最近一次发送的内容。': 'The receiver shows the most recently sent text.', '文本': 'Text',
    '第一步：扫描二维码连接电脑热点': 'Step 1: Scan to join the computer hotspot',
    '用手机相机扫描并确认加入 Wi-Fi。连接成功后，这里会自动显示第二个二维码。': 'Scan with your phone camera and join Wi-Fi. A second QR code will appear after you connect.',
    '连接电脑热点的 Wi-Fi 二维码': 'Wi-Fi QR code for the computer hotspot',
    '手机已打开传输页': 'Transfer page opened on phone', '第二步：扫描二维码打开传输页': 'Step 2: Scan to open the transfer page',
    '两步连接已完成，可以在手机上发送文件或文本。': 'Connection complete. You can send files or text from your phone.',
    '手机已连接电脑热点。再次扫描下面的二维码，网页会自动填写本次访问码。': 'Your phone joined the hotspot. Scan the QR code below to open the page with the access code filled in.',
    '打开手机传输页的二维码': 'QR code for the phone transfer page',
    '热点已开启，正在获取地址': 'Hotspot started; finding its address',
    '热点已开启，正在等待手机入口就绪': 'Hotspot started; preparing the phone endpoint',
    '电脑正在等待热点地址可用，准备好后会自动显示二维码。': 'Waiting for the hotspot address to become available. The QR code will appear automatically.',
    '电脑正在识别热点的 IPv4 地址，识别成功后会自动出现二维码。': 'The computer is finding the hotspot IPv4 address. The QR code will appear when it is ready.',
    '热点不可用': 'Hotspot unavailable',
    '电脑热点无法使用，手机传输暂不可用。请检查 Windows 移动热点和 Wi-Fi 适配器后重启服务。': 'Phone transfer is unavailable because the computer hotspot could not start. Check Windows Mobile Hotspot and the Wi-Fi adapter, then restart the service.',
    '连接状态读取失败': 'Could not read connection status', '已收到最新文本。': 'Latest text received.',
    '连接中断，正在重试…': 'Connection lost. Retrying…', '已复制，可直接粘贴。': 'Copied. You can paste it now.',
    '复制失败，请选中文本后手动复制。': 'Copy failed. Select the text and copy it manually.',
    '服务未连接，请确认 Local Connect 正在运行。': 'Service disconnected. Check that Local Connect is running.',
    'PDF 文件名': 'PDF file name', '勾选此 PDF，加入选中项下载': 'Select this PDF for download',
    '单击重命名 PDF': 'Click to rename PDF', '移除容器，保留文件': 'Remove container and keep files',
    '下载 PDF': 'Download PDF', '将文件拖到这里': 'Drag files here', '同一容器仅接受相同格式': 'One file format per container',
    '无法预览': 'Preview unavailable', '移出容器': 'Remove from container',
    '勾选后下载选中项，也可一起拖动': 'Select for download or drag together',
    '请先给空容器加入文件': 'Add files to the empty container first', '新建 PDF 容器': 'New PDF container',
    '已移除容器，文件已放回列表。': 'Container removed. Files returned to the list.',
    '操作失败，请重试': 'Operation failed. Please retry.', '拖入失败，请重试': 'Could not add files. Please retry.',
    '正在准备上一次下载，请稍候…': 'Preparing the previous download. Please wait…',
    '正在准备下载…': 'Preparing download…', '下载准备失败': 'Could not prepare download',
    '下载失败，请重试': 'Download failed. Please retry.',
    '请先运行 python -m pip install --target .deps -r requirements.txt': 'Install dependencies: python -m pip install --target .deps -r requirements.txt',
    '图片、PDF、DOC/DOCX、XLS/XLSX、PPT/PPTX、HTML；Office 格式需要本机安装对应应用。': 'Images, PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX, HTML. Office formats require the corresponding desktop application.',
    '等待上传': 'Waiting to upload', '上传进度': 'upload progress', '移除': 'Remove',
    '正在保存…': 'Saving…', '服务响应异常，请重试': 'Unexpected server response. Please retry.',
    '上传失败': 'Upload failed', '连接中断，请检查热点连接后重试': 'Connection lost. Check the hotspot and retry.',
    '上传已中止': 'Upload cancelled', '文本超过 64 KiB，请缩短后再发送。': 'Text exceeds 64 KiB. Shorten it and try again.',
    '正在发送…': 'Sending…', '发送成功，电脑接收页已更新。': 'Sent. The receiver has been updated.',
    '连接失败，请检查电脑服务和 Wi-Fi 连接。': 'Connection failed. Check the computer service and Wi-Fi.',
    '请先填写访问码。': 'Enter the access code first.', '一次最多选择 100 个文件。': 'Select at most 100 files at once.',
    '单个文件不能超过 2 GiB。': 'Each file must be 2 GiB or smaller.',
    '每批文件总量不能超过 10 GiB。': 'The batch must be 10 GiB or smaller.',
    '已完成': 'Complete', '连接中断': 'Connection lost',
    '访问码无效': 'Invalid access code', '访问码不正确': 'Incorrect access code',
    '请输入文本': 'Enter text', '文件名无效': 'Invalid file name',
    '正在准备文件…': 'Preparing files…', '正在打包文件…': 'Creating ZIP…', '下载已准备好': 'Download ready',
    '服务已关闭，转换已取消': 'Service closed; conversion cancelled',
    '请先给空的 PDF 容器加入文件，再新建下一个': 'Add files to the empty PDF container before creating another.',
    '最多创建 100 个 PDF 容器': 'Up to 100 PDF containers are allowed.',
    'PDF 容器已不存在，请刷新列表': 'PDF container no longer exists. Refresh the list.',
    'PDF 名称不能为空': 'PDF name cannot be empty.',
    '此格式暂不支持转 PDF，仍可下载原文件': 'This format cannot be converted to PDF. You can still download the original.',
    '一个 PDF 容器只能放入相同格式的文件': 'A PDF container accepts only files of the same format.',
    '请先向 PDF 容器加入文件': 'Add files to the PDF container first.',
    '电脑热点已断开': 'Computer hotspot disconnected.',
    '请求地址无效': 'Invalid request address.',
    '接收页令牌无效，请刷新电脑页面': 'Receiver session expired. Refresh the computer page.',
    '文件大小无效': 'Invalid file size.',
    'Local Connect 文件已达到全局空间上限；请自行整理 uploads 后重试': 'Local Connect has reached its storage limit. Review the uploads folder and retry.',
    '电脑剩余空间不足；请释放磁盘空间后重试': 'Not enough free disk space. Free some space and retry.',
    '生成的文件超过 Local Connect 全局空间上限': 'The generated file exceeds the Local Connect storage limit.',
    '电脑剩余空间不足，无法保存生成的文件': 'Not enough free disk space to save the generated file.',
    '请发送 JSON 数据': 'Send JSON data.', '缺少有效的数据长度': 'Missing a valid data length.',
    '文本过长或请求为空': 'Text is too long or the request is empty.', '数据格式有误': 'Invalid data format.',
    '文本不能超过 64 KiB': 'Text must be 64 KiB or smaller.',
    '上传需要明确的文件长度': 'Upload requires a file length.',
    '缺少有效的文件长度': 'Missing a valid file length.', '请提供文件名': 'Provide a file name.',
    '上传中断或保存失败，请检查网络和电脑剩余空间后重试': 'Upload interrupted or save failed. Check the connection and free disk space, then retry.',
    '每次最多 100 个文件，请重新打开电脑接收页后继续': 'Up to 100 files per session. Reopen the receiver page to continue.',
    '文件传输不完整，请重新上传': 'Incomplete file transfer. Upload it again.',
    '请选择已上传的文件': 'Select uploaded files.', '文件已不在本次列表中': 'The file is no longer in this session.',
    '一个容器只能放相同格式；例如 JPG 和 PNG 请分别建容器': 'One format per container. Use separate containers for JPG and PNG.',
    '一次只能指定一个插入位置': 'Specify only one insertion position.',
    '目标图片已不在容器中，请重试': 'The target image is no longer in this container. Retry.',
    '每个 PDF 容器的文件总量不能超过 500 MiB': 'A PDF container can hold at most 500 MiB.',
    '只能旋转此容器中的图片': 'Only images in this container can be rotated.',
    '服务正在关闭': 'Service is shutting down.',
    '请选择明确的下载范围': 'Choose a download range.', '勾选列表无效，请重新选择': 'Selection is invalid. Choose again.',
    '请先勾选要下载的文件或 PDF 容器': 'Select files or PDF containers to download.',
    '部分勾选项已不存在，请重新选择': 'Some selected items no longer exist. Choose again.',
    '勾选的文件已移入 PDF 容器，请重新勾选该容器': 'A selected file is in a PDF container. Select the container instead.',
    '勾选的 PDF 容器为空，请先加入文件': 'The selected PDF container is empty. Add files first.',
    '还没有可下载的文件': 'There are no files to download.',
    '正在准备上一次下载，请稍候再试': 'Preparing the previous download. Please wait and retry.',
    '转换失败，请检查文件和磁盘空间': 'Conversion failed. Check the file and free disk space.',
    '转换超时；请检查文件能否正常打开，或将大文件拆分后再试': 'Conversion timed out. Check that the file opens, or split a large file and retry.',
    'HTML 转换需要电脑安装 Chrome 或 Edge': 'HTML conversion requires Chrome or Edge on the computer.',
    'HTML 转换单个文件不能超过 20 MiB': 'Each HTML file must be 20 MiB or smaller.',
    'Office 转换需要 Windows 和 Microsoft Office': 'Office conversion requires Windows and Microsoft Office.',
    '此格式暂不支持转为 PDF，可直接下载原文件': 'This format cannot be converted to PDF. Download the original file.',
    '每个 PDF 容器最多转换 500 MiB 文件': 'A PDF container can convert at most 500 MiB.',
    '请先移除 PDF 密码后再转换': 'Remove the PDF password before converting.',
    '{count} 字符': '{count} characters',
    '热点名称：{ssid}　热点密码：{password}': 'Hotspot: {ssid} · Password: {password}',
    '若扫码无法打开，请在手机浏览器输入 {url}，访问码 {code}。': 'If scanning fails, open {url} in your phone browser and enter code {code}.',
    '{count} 个原文件 · 总大小 {size}': '{count} original files · Total {size}',
    ' · 已选 {count} 项（原文件 {size}）': ' · {count} selected (original files {size})',
    '下载选中（{count} 项）ZIP ↓': 'Download {count} selected as ZIP ↓',
    '选择 {name}': 'Select {name}', '移除 {name}': 'Remove {name}',
    '转换并下载 {name}.pdf': 'Convert and download {name}.pdf',
    '顺时针旋转 {name} 90°': 'Rotate {name} 90° clockwise',
    '移出 {name}': 'Remove {name} from container', '保存位置：{folder}': 'Saved in: {folder}',
    '已开始下载 {name} · {size}': 'Download started: {name} · {size}',
    '下载 {name}': 'Download {name}',
    '{count} 个文件未完成；请检查连接后点击重试，或移除无法上传的文件。': '{count} files unfinished. Check the connection, then retry or remove files that cannot upload.',
    '{count} 个文件等待自动上传…': '{count} files waiting to upload…',
    '请先填写访问码，文件会自动上传。': 'Enter the access code to start uploading.',
    '{size} · 等待上传': '{size} · Waiting to upload',
    '从队列移除 {name}': 'Remove {name} from queue',
    '{name} 上传进度': '{name} upload progress',
    '{size} · 正在保存…': '{size} · Saving…',
    '{size} · 已完成': '{size} · Complete',
    '正在上传：{name}（本轮第 {number} 个）': 'Uploading: {name} (file {number} this round)',
    '已上传 {count} 个文件，请在电脑接收页查看。': '{count} files uploaded. Check the receiver page.',
    '本轮已上传 {count} 个；{error}。检查后可重试未完成的文件。': '{count} files uploaded this round. {error} Check the connection, then retry unfinished files.',
    '正在转换 {name}（{number}/{total}）…': 'Converting {name} ({number}/{total})…'
  };
  let language = 'zh';
  const originals = new WeakMap();
  const t = (key, values = {}) => {
    let phrase = language === 'en' ? (english[key] || key) : key;
    if (language === 'en' && phrase === key) {
      const conversion = key.match(/^正在转换 (.+)（(\d+)\/(\d+)）…$/);
      if (conversion) phrase = english['正在转换 {name}（{number}/{total}）…']
        .replace('{name}', conversion[1]).replace('{number}', conversion[2]).replace('{total}', conversion[3]);
      else if (key.startsWith('转换失败：')) phrase = 'Conversion failed: ' + key.slice(5);
    }
    return phrase.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ''));
  };
  function apply(root = document) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (['SCRIPT', 'STYLE', 'TEXTAREA'].includes(node.parentElement?.tagName)
          || node.parentElement?.closest('[data-i18n-user-content]')) continue;
      const current = node.nodeValue;
      const stored = originals.get(node);
      const original = stored && stored.last === current ? stored.original : current;
      const trimmed = original.trim();
      if (!english[trimmed]) continue;
      const translated = language === 'en' ? english[trimmed] : trimmed;
      const next = original.replace(trimmed, translated);
      node.nodeValue = next;
      originals.set(node, { original, last: next });
    }
    for (const element of root.querySelectorAll('[title], [alt], [aria-label], [placeholder]')) {
      if (element.closest('[data-i18n-user-content]')) continue;
      for (const attr of ['title', 'alt', 'aria-label', 'placeholder']) {
        const value = element.getAttribute(attr);
        if (!value) continue;
        const original = element.dataset[`original${attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase())}`] || value;
        if (!english[original]) continue;
        element.dataset[`original${attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase())}`] = original;
        element.setAttribute(attr, language === 'en' ? english[original] : original);
      }
    }
    document.title = t(document.title === english['Local Connect · 电脑接收页'] ? 'Local Connect · 电脑接收页' :
      document.title === english['Local Connect · 手机发送页'] ? 'Local Connect · 手机发送页' : document.title);
  }
  function init() {
    const button = document.getElementById('language-toggle');
    const updateButton = () => {
      document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
      button.textContent = language === 'en' ? '中文' : 'EN';
      button.setAttribute('aria-label', language === 'en' ? '切换为中文' : 'Switch to English');
      button.title = button.getAttribute('aria-label');
    };
    button.addEventListener('click', () => {
      language = language === 'zh' ? 'en' : 'zh';
      apply(); updateButton();
      window.dispatchEvent(new Event('languagechange'));
    });
    apply(); updateButton();
  }
  return { init, t, apply, get language() { return language; } };
})();
