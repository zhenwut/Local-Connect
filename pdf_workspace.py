"""PDF containers and asynchronous local downloads, scoped to the current batch."""
import hashlib
import json
import secrets
import threading
import zipfile
from pathlib import Path

from file_transfer import safe_name
from pdf_convert import IMAGE_FORMATS, capabilities, convert, file_format, MAX_CONVERT_BYTES


class PdfWorkspace:
    def __init__(self, files):
        self.files = files
        self.lock = threading.RLock()
        self.conversion_lock = threading.Lock()
        self.stopped = threading.Event()
        self.worker = None
        self.capabilities = capabilities()
        self.version = 0
        self.reset()

    def reset(self):
        with self.lock:
            self.epoch = secrets.token_hex(12)
            self.containers = {}
            self.jobs = {}
            self.version += 1

    def close(self):
        self.stopped.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=25)

    def status(self):
        with self.lock:
            return {'pdf_version': self.version, 'pdf_containers': [dict(c, file_ids=list(c['file_ids']), rotations=dict(c['rotations'])) for c in self.containers.values()],
                    'pdf_capabilities': self.capabilities}

    def action(self, payload):
        with self.lock:
            action = payload.get('action')
            if action == 'create':
                if any(not c['file_ids'] for c in self.containers.values()):
                    raise ValueError('请先给空的 PDF 容器加入文件，再新建下一个')
                if len(self.containers) >= 100:
                    raise ValueError('最多创建 100 个 PDF 容器')
                used_numbers = {c['number'] for c in self.containers.values()}
                used_names = {c['name'].casefold() for c in self.containers.values()}
                number = 1
                while number in used_numbers or f'pdf{number}' in used_names:
                    number += 1
                key = secrets.token_hex(12)
                self.containers[key] = {'id': key, 'number': number, 'name': f'pdf{number}', 'format': '', 'file_ids': [], 'rotations': {}}
            else:
                key = payload.get('id')
                if not isinstance(key, str) or key not in self.containers:
                    raise ValueError('PDF 容器已不存在，请刷新列表')
                container = self.containers[key]
                if action == 'delete':
                    del self.containers[key]
                elif action == 'rename':
                    name = payload.get('name')
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError('PDF 名称不能为空')
                    name = name.strip()
                    if name.lower().endswith('.pdf'):
                        name = name[:-4]
                    if not name.strip():
                        raise ValueError('PDF 名称不能为空')
                    container['name'] = safe_name(name)[:80]
                elif action == 'add':
                    ids = payload.get('file_ids')
                    if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
                        raise ValueError('请选择已上传的文件')
                    ids = list(dict.fromkeys(ids))
                    items = [self.files.get(i) for i in ids]
                    if any(f is None for f in items):
                        raise ValueError('文件已不在本次列表中')
                    formats = {file_format(f['name']) for f in items}
                    if container['format']:
                        formats.add(container['format'])
                    if len(formats) != 1:
                        raise ValueError('一个容器只能放相同格式；例如 JPG 和 PNG 请分别建容器')
                    kind = next(iter(formats))
                    if kind not in self.capabilities['formats']:
                        raise ValueError('此格式暂不支持转 PDF，仍可下载原文件')
                    before_id = payload.get('before_id')
                    after_id = payload.get('after_id')
                    if before_id is not None and after_id is not None:
                        raise ValueError('一次只能指定一个插入位置')
                    if before_id is not None and before_id not in container['file_ids']:
                        raise ValueError('目标图片已不在容器中，请重试')
                    if after_id is not None and after_id not in container['file_ids']:
                        raise ValueError('目标图片已不在容器中，请重试')
                    combined = list(dict.fromkeys(container['file_ids'] + ids))
                    if sum(self.files.get(i)['bytes'] for i in combined) > MAX_CONVERT_BYTES:
                        raise ValueError('每个 PDF 容器的文件总量不能超过 500 MiB')
                    target_id = before_id if before_id is not None else after_id
                    if target_id is not None and target_id not in ids:
                        combined = [i for i in combined if i not in ids]
                        position = combined.index(target_id) + (1 if after_id is not None else 0)
                        combined[position:position] = ids
                    transferred = {}
                    for other in self.containers.values():
                        if other is not container:
                            transferred.update({i: other['rotations'][i] for i in ids if i in other['rotations']})
                            other['file_ids'] = [i for i in other['file_ids'] if i not in ids]
                            for i in ids:
                                other['rotations'].pop(i, None)
                            if not other['file_ids']:
                                other['format'] = ''
                    container['file_ids'] = combined
                    container['format'] = kind
                    container['rotations'].update(transferred)
                elif action == 'remove':
                    file_id = payload.get('file_id')
                    container['file_ids'] = [i for i in container['file_ids'] if i != file_id]
                    container['rotations'].pop(file_id, None)
                    if not container['file_ids']:
                        container['format'] = ''
                elif action == 'rotate':
                    file_id = payload.get('file_id')
                    if not isinstance(file_id, str) or file_id not in container['file_ids'] or container['format'] not in IMAGE_FORMATS:
                        raise ValueError('只能旋转此容器中的图片')
                    angle = (container['rotations'].get(file_id, 0) + 90) % 360
                    if angle:
                        container['rotations'][file_id] = angle
                    else:
                        container['rotations'].pop(file_id, None)
                else:
                    raise ValueError('未知操作')
            self.version += 1
            return self.status()

    def start_export(self, payload):
        with self.lock:
            if self.stopped.is_set():
                raise ValueError('服务正在关闭')
            epoch = self.epoch
            # Immutable snapshot: files arriving later belong to the next download.
            with self.files.lock:
                files = {k: dict(v) for k, v in self.files.files.items()}
            is_zip = payload.get('all') is True or 'selected' in payload
            if 'selected' in payload:
                selection = payload['selected']
                if not isinstance(selection, dict) or payload.get('all') is True or 'container_id' in payload:
                    raise ValueError('请选择明确的下载范围')
                chosen = []
                for field in ('file_ids', 'container_ids'):
                    ids = selection.get(field, [])
                    if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
                        raise ValueError('勾选列表无效，请重新选择')
                    chosen.append(set(ids))
                file_ids, container_ids = chosen
                if not file_ids and not container_ids:
                    raise ValueError('请先勾选要下载的文件或 PDF 容器')
                if not file_ids <= files.keys() or not container_ids <= self.containers.keys():
                    raise ValueError('部分勾选项已不存在，请重新选择')
                grouped = {i for c in self.containers.values() for i in c['file_ids']}
                if file_ids & grouped:
                    raise ValueError('勾选的文件已移入 PDF 容器，请重新勾选该容器')
                containers = [dict(c, file_ids=list(c['file_ids']), rotations=dict(c['rotations'])) for key, c in self.containers.items() if key in container_ids]
                if any(not c['file_ids'] for c in containers):
                    raise ValueError('勾选的 PDF 容器为空，请先加入文件')
                included = file_ids | {i for c in containers for i in c['file_ids']}
                files = {key: file for key, file in files.items() if key in included}
                name = 'Local Connect 选中.zip'
            elif payload.get('all') is True:
                containers = [dict(c, file_ids=list(c['file_ids']), rotations=dict(c['rotations'])) for c in self.containers.values() if c['file_ids']]
                if not files:
                    raise ValueError('还没有可下载的文件')
                name = 'Local Connect.zip'
            else:
                key = payload.get('container_id')
                if not isinstance(key, str) or key not in self.containers or not self.containers[key]['file_ids']:
                    raise ValueError('请先向 PDF 容器加入文件')
                container = self.containers[key]
                containers = [dict(container, file_ids=list(container['file_ids']), rotations=dict(container['rotations']))]
                name = safe_name(container['name'] + '.pdf')
            if not self.conversion_lock.acquire(blocking=False):
                raise ValueError('正在准备上一次下载，请稍候再试')
            job_id = secrets.token_hex(16)
            job = {'id': job_id, 'state': 'working', 'name': name, 'message': '正在准备文件…', 'bytes': 0}
            self.jobs[job_id] = job
            self.worker = threading.Thread(target=self._export, args=(job, epoch, files, containers, is_zip), daemon=True)
            self.worker.start()
            return dict(job)

    def _export(self, job, epoch, files, containers, is_zip):
        zip_path = None
        try:
            folder = self.files.root / ('exports-' + epoch)
            folder.mkdir(parents=True, exist_ok=True)
            entries = []
            grouped = set()
            for index, container in enumerate(containers):
                if self.stopped.is_set():
                    raise ValueError('服务已关闭，下载已取消')
                job['message'] = f'正在转换 {container["name"]}（{index + 1}/{len(containers)}）…'
                pages = [(i, container['rotations'].get(i, 0)) for i in container['file_ids']]
                signature = hashlib.sha256(json.dumps(pages).encode()).hexdigest()
                path = folder / (signature + '.pdf')
                if not path.is_file():
                    part = path.with_suffix('.part')
                    quota = self.files.quota
                    ticket = quota.reserve(max(1024 * 1024, 2 * sum(files[i]['bytes'] for i in container['file_ids']) + 1024 * 1024)) if quota else None
                    try:
                        convert([files[i] for i in container['file_ids']], part, cancel=self.stopped,
                                rotations=container['rotations'])
                        if quota:
                            quota.check(ticket)
                        part.replace(path)
                    finally:
                        part.unlink(missing_ok=True)
                        if quota:
                            quota.release(ticket)
                entries.append((safe_name(container['name'] + '.pdf'), path))
                grouped.update(container['file_ids'])
            if is_zip:
                entries.extend((f['name'], f['path']) for key, f in files.items() if key not in grouped)
                path = folder / (job['id'] + '.zip')
                zip_path = path
                used = set()
                job['message'] = '正在打包文件…'
                quota = self.files.quota
                ticket = quota.reserve(sum(source.stat().st_size for _, source in entries) + max(1024 * 1024, len(entries) * 1024)) if quota else None
                try:
                    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                        for name, source in entries:
                            original = Path(name)
                            number = 1
                            while name.casefold() in used:
                                number += 1
                                name = f'{original.stem} ({number}){original.suffix}'
                            used.add(name.casefold())
                            with source.open('rb') as content, archive.open(name, 'w', force_zip64=True) as entry:
                                while chunk := content.read(1024 * 1024):
                                    if self.stopped.is_set():
                                        raise ValueError('服务已关闭，打包已取消')
                                    entry.write(chunk)
                    if quota:
                        quota.check(ticket)
                finally:
                    if quota:
                        quota.release(ticket)
            else:
                path = entries[0][1]
            with self.lock:
                if self.epoch == epoch:
                    job.update(state='ready', path=path, bytes=path.stat().st_size,
                               download_url=f'/api/exports/{job["id"]}/download', message='下载已准备好')
        except Exception as error:
            if zip_path is not None:
                try:
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    pass
            job.update(state='error', message=str(error) or '转换失败，请检查文件和磁盘空间')
        finally:
            self.conversion_lock.release()

    def get_job(self, key, include_path=False):
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                return None
            return {k: v for k, v in job.items() if include_path or k != 'path'}
