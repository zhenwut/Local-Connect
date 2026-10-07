/* Receiver-only PDF workspace. All names are rendered as text. */
window.PdfFiles = (() => {
  const t = LocalI18n.t;
  const list = document.getElementById('file-list');
  const workspace = document.querySelector('.files-workspace');
  const addButton = document.getElementById('add-pdf');
  const allButton = document.getElementById('download-all');
  const message = document.getElementById('files-status');
  const selected = new Set();
  const selectedContainers = new Set();
  const imageFormats = new Set(['jpg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'avif']);
  let snapshot = null, version = '', busy = false, dragging = false;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function tell(text) { message.textContent = text; }
  function updateDownloadControls() {
    if (!snapshot) return;
    const containers = snapshot.pdf_containers.filter(c => selectedContainers.has(c.id));
    const included = new Set([...selected, ...containers.flatMap(c => c.file_ids)]);
    const count = selected.size + selectedContainers.size;
    const totalBytes = snapshot.files.reduce((sum, file) => sum + file.bytes, 0);
    const chosenBytes = snapshot.files.reduce((sum, file) => sum + (included.has(file.id) ? file.bytes : 0), 0);
    document.getElementById('files-total').textContent = t('{count} 个原文件 · 总大小 {size}', {count: snapshot.files.length, size: LocalFiles.formatSize(totalBytes)})
      + (count ? t(' · 已选 {count} 项（原文件 {size}）', {count, size: LocalFiles.formatSize(chosenBytes)}) : '');
    allButton.textContent = count ? t('下载选中（{count} 项）ZIP ↓', {count}) : t('一键下载 ZIP ↓');
    allButton.disabled = busy || !snapshot.files.length;
  }
  async function request(url, payload) {
    const token = await window.getReceiverToken();
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, receiver_token: token }) });
    const data = await response.json();
    if (!response.ok) throw new Error(t(data.error || '操作失败，请重试'));
    return data;
  }
  async function action(payload) {
    try {
      const result = await request('/api/pdf-containers', payload);
      version = '';
      update({ ...snapshot, ...result });
      tell(payload.action === 'delete' ? t('已移除容器，文件已放回列表。') : '');
    } catch (error) { tell(error.message); }
  }
  function dragSource(node, file, fromContainer = false) {
    node.draggable = true;
    node.dataset.fileId = file.id;
    node.addEventListener('dragstart', event => {
      dragging = true;
      const ids = !fromContainer && selected.has(file.id) ? [...selected] : [file.id];
      event.dataTransfer.setData('application/x-local-connect-files', JSON.stringify(ids));
      if (fromContainer) event.dataTransfer.setData('application/x-local-connect-member', file.id);
      event.dataTransfer.effectAllowed = 'move';
    });
    node.addEventListener('dragend', () => {
      dragging = false;
      workspace.classList.remove('drag-return');
      document.querySelectorAll('.drag-over').forEach(n => n.classList.remove('drag-over'));
    });
    node.querySelectorAll('img').forEach(img => { img.draggable = false; });
  }
  function dropTarget(node, callback) {
    node.addEventListener('dragover', event => {
      if (!event.dataTransfer.types.includes('application/x-local-connect-files')) return;
      event.preventDefault(); event.stopPropagation();
      event.dataTransfer.dropEffect = 'move';
      workspace.classList.remove('drag-return');
      node.classList.add('drag-over');
    });
    node.addEventListener('dragleave', event => {
      if (!node.contains(event.relatedTarget)) node.classList.remove('drag-over');
    });
    node.addEventListener('drop', event => {
      const raw = event.dataTransfer.getData('application/x-local-connect-files');
      if (!raw) return;
      event.preventDefault(); event.stopPropagation();
      dragging = false;
      workspace.classList.remove('drag-return');
      node.classList.remove('drag-over');
      try { callback(JSON.parse(raw)); } catch { tell(t('拖入失败，请重试')); }
    });
  }
  function rename(container, button) {
    const input = element('input', 'pdf-rename');
    input.value = container.name;
    input.maxLength = 80;
    input.setAttribute('aria-label', t('PDF 文件名'));
    let finished = false;
    const finish = save => {
      if (finished) return;
      finished = true;
      input.replaceWith(button);
      if (save && input.value.trim() && input.value.trim() !== container.name) {
        action({ action: 'rename', id: container.id, name: input.value });
      } else { version = ''; update(snapshot); }
    };
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      if (event.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
    button.replaceWith(input); input.focus(); input.select();
  }
  function containerCard(container, files) {
    const item = element('li', 'pdf-container');
    item.dataset.containerId = container.id;
    const header = element('div', 'pdf-header');
    const select = element('input', 'pdf-select'); select.type = 'checkbox';
    select.disabled = !container.file_ids.length;
    select.checked = selectedContainers.has(container.id);
    select.setAttribute('aria-label', t('选择 {name}', {name: `${container.name}.pdf`}));
    select.title = t('勾选此 PDF，加入选中项下载');
    select.addEventListener('change', () => {
      if (select.checked) selectedContainers.add(container.id); else selectedContainers.delete(container.id);
      item.classList.toggle('selected', select.checked);
      updateDownloadControls();
    });
    item.classList.toggle('selected', select.checked);
    const name = element('button', 'pdf-name', container.name);
    name.type = 'button'; name.title = t('单击重命名 PDF');
    name.addEventListener('click', event => { event.stopPropagation(); rename(container, name); });
    const close = element('button', 'pdf-close', '×');
    close.type = 'button'; close.title = t('移除容器，保留文件');
    close.setAttribute('aria-label', t('移除 {name}', {name: container.name}));
    close.addEventListener('click', event => { event.stopPropagation(); action({ action: 'delete', id: container.id }); });
    header.append(select, name, close);
    const body = element('div', 'pdf-body');
    body.tabIndex = 0; body.setAttribute('role', 'button');
    body.setAttribute('aria-label', t('转换并下载 {name}.pdf', {name: container.name}));
    const members = container.file_ids.map(id => files.get(id)).filter(Boolean);
    item.classList.toggle('has-members', members.length > 0);
    if (members.length) {
      body.append(element('span', 'pdf-download-label', t('下载 PDF')));
    } else {
      body.append(element('span', 'pdf-badge', 'PDF'));
      body.append(element('p', 'pdf-summary', t('将文件拖到这里')));
      body.append(element('p', 'pdf-hint', t('同一容器仅接受相同格式')));
    }
    body.addEventListener('click', () => download({ container_id: container.id }));
    body.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); download({ container_id: container.id }); }
    });
    item.append(header);
    const isImage = imageFormats.has(container.format);
    const memberList = element('ul', isImage ? 'pdf-members image-members' : 'pdf-members');
    members.forEach((file, index) => {
      const row = element('li', 'pdf-member');
      row.dataset.fileId = file.id;
      if (isImage) {
        const thumb = element('div', 'pdf-thumbnail');
        const image = element('img');
        image.src = `/api/files/${encodeURIComponent(file.id)}/thumbnail`;
        image.alt = file.name;
        image.loading = 'lazy';
        image.style.transform = `rotate(${container.rotations?.[file.id] || 0}deg)`;
        image.draggable = false;
        image.addEventListener('error', () => {
          thumb.classList.add('thumbnail-error');
          image.replaceWith(element('span', '', t('无法预览')));
        }, { once: true });
        thumb.append(image);
        const rotate = element('button', 'pdf-rotate', '↻');
        rotate.type = 'button'; rotate.draggable = false;
        rotate.title = t('顺时针旋转 {name} 90°', {name: file.name});
        rotate.setAttribute('aria-label', rotate.title);
        rotate.addEventListener('click', event => {
          event.stopPropagation();
          action({ action: 'rotate', id: container.id, file_id: file.id });
        });
        thumb.append(rotate);
        row.append(thumb);
      }
      const position = element('span', 'pdf-position', String(index + 1));
      const label = element('span', '', file.name);
      label.title = file.name;
      const remove = element('button', 'pdf-remove-file', '↗');
      remove.type = 'button'; remove.title = t('移出容器'); remove.setAttribute('aria-label', t('移出 {name}', {name: file.name}));
      remove.addEventListener('click', event => { event.stopPropagation(); action({ action: 'remove', id: container.id, file_id: file.id }); });
      row.append(position, label, remove);
      dragSource(row, file, true);
      dropTarget(row, ids => {
        const origin = container.file_ids.indexOf(ids[0]);
        const target = container.file_ids.indexOf(file.id);
        const place = origin >= 0 && origin < target ? { after_id: file.id } : { before_id: file.id };
        action({ action: 'add', id: container.id, file_ids: ids, ...place });
      });
      memberList.append(row);
    });
    if (members.length) item.append(memberList);
    item.append(body);
    dropTarget(item, ids => action({ action: 'add', id: container.id, file_ids: ids }));
    return item;
  }
  function update(result) {
    if (!result) return;
    if (snapshot && result.pdf_version < snapshot.pdf_version) {
      result = { ...result, pdf_version: snapshot.pdf_version, pdf_containers: snapshot.pdf_containers };
    }
    snapshot = result;
    const nextVersion = `${result.files_version}:${result.pdf_version}`;
    if (nextVersion === version || dragging || document.activeElement?.classList.contains('pdf-rename')) return;
    version = nextVersion;
    const files = new Map(result.files.map(file => [file.id, file]));
    const grouped = new Set(result.pdf_containers.flatMap(c => c.file_ids));
    for (const id of selected) if (!files.has(id) || grouped.has(id)) selected.delete(id);
    const selectableContainers = new Set(result.pdf_containers.filter(c => c.file_ids.length).map(c => c.id));
    for (const id of selectedContainers) if (!selectableContainers.has(id)) selectedContainers.delete(id);
    list.replaceChildren();
    result.files.filter(file => !grouped.has(file.id)).forEach(file => {
      const item = element('li', 'file-item');
      const card = LocalFiles.createCard(file);
      dragSource(card, file);
      const select = element('input', 'file-select'); select.type = 'checkbox';
      select.checked = selected.has(file.id); select.title = t('勾选后下载选中项，也可一起拖动');
      select.setAttribute('aria-label', t('选择 {name}', {name: file.name}));
      select.addEventListener('change', () => {
        if (select.checked) selected.add(file.id); else selected.delete(file.id);
        item.classList.toggle('selected', select.checked);
        updateDownloadControls();
      });
      item.classList.toggle('selected', select.checked);
      item.append(card, select); list.append(item);
    });
    result.pdf_containers.forEach(container => list.append(containerCard(container, files)));
    document.getElementById('files-empty').hidden = files.size > 0 || result.pdf_containers.length > 0;
    document.getElementById('files-folder').textContent = files.size ? t('保存位置：{folder}', {folder: result.files_folder}) : '';
    addButton.disabled = result.pdf_containers.some(c => !c.file_ids.length);
    addButton.title = t(addButton.disabled ? '请先给空容器加入文件' : '新建 PDF 容器');
    updateDownloadControls();
    document.getElementById('pdf-support').textContent = t(result.pdf_capabilities.hint);
  }
  async function download(payload) {
    if (busy) { tell(t('正在准备上一次下载，请稍候…')); return; }
    busy = true; allButton.disabled = true;
    list.setAttribute('aria-busy', 'true');
    tell(t('正在准备下载…'));
    try {
      let job = await request('/api/exports', payload);
      while (job.state === 'working') {
        tell(t(job.message));
        await new Promise(resolve => setTimeout(resolve, 600));
        const response = await fetch(`/api/exports/${job.id}`, { cache: 'no-store' });
        job = await response.json();
        if (!response.ok) throw new Error(t(job.error || '下载准备失败'));
      }
      if (job.state !== 'ready') throw new Error(t(job.message));
      const link = element('a'); link.href = job.download_url; link.download = job.name;
      document.body.append(link); link.click(); link.remove();
      tell(t('已开始下载 {name} · {size}', {name: job.name, size: LocalFiles.formatSize(job.bytes)}));
    } catch (error) { tell(error.message || t('下载失败，请重试')); }
    finally {
      busy = false; list.removeAttribute('aria-busy');
      updateDownloadControls();
    }
  }
  addButton.addEventListener('click', () => action({ action: 'create' }));
  document.addEventListener('dragover', event => {
    if (!event.dataTransfer.types.includes('application/x-local-connect-member')) return;
    const outsideContainer = !event.target.closest('.pdf-container');
    workspace.classList.toggle('drag-return', outsideContainer);
    if (outsideContainer) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
    }
  });
  document.addEventListener('drop', event => {
    workspace.classList.remove('drag-return');
    if (event.target.closest('.pdf-container')) return;
    const fileId = event.dataTransfer.getData('application/x-local-connect-member');
    if (!fileId) return;
    event.preventDefault();
    const container = snapshot?.pdf_containers.find(c => c.file_ids.includes(fileId));
    if (container) action({ action: 'remove', id: container.id, file_id: fileId });
  });
  allButton.addEventListener('click', () => download(selected.size || selectedContainers.size
    ? { selected: { file_ids: [...selected], container_ids: [...selectedContainers] } } : { all: true }));
  return { update, refreshLanguage: () => { tell(''); version = ''; update(snapshot); }, reset: () => { snapshot = null; version = ''; selected.clear(); selectedContainers.clear(); } };
})();
