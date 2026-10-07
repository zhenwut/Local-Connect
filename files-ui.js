/* Local assets only; filenames are always inserted as text. */
window.LocalFiles = (() => {
  const types = {
    pdf: ["#cf3845", "PDF"], word: ["#2869bd", "W"], excel: ["#218354", "X"],
    slides: ["#ce622f", "P"], audio: ["#8861bd", "♪"], video: ["#ad4f9e", "▶"],
    image: ["#2b8e9e", "IMG"], archive: ["#b0822a", "ZIP"], text: ["#527590", "TXT"],
    csv: ["#218354", "CSV"], ebook: ["#965ea5", "BOOK"],
    file: ["#78879b", "FILE"]
  };

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KiB", "MiB", "GiB"];
    let value = bytes / 1024, index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
    return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[index]}`;
  }

  function fileIcon(category) {
    const [color, label] = types[category] || types.file;
    const holder = document.createElement("div");
    holder.className = "file-icon";
    holder.setAttribute("aria-hidden", "true");
    holder.innerHTML = `<svg viewBox="0 0 60 70" xmlns="http://www.w3.org/2000/svg"><path d="M10 2h27l15 15v46a5 5 0 0 1-5 5H10a5 5 0 0 1-5-5V7a5 5 0 0 1 5-5Z" fill="${color}" opacity=".13"/><path d="M37 2v15h15" fill="${color}" opacity=".3"/><rect x="0" y="26" width="48" height="28" rx="5" fill="${color}"/><text x="24" y="45" text-anchor="middle" font-size="${label.length > 2 ? 13 : 21}" font-family="system-ui,sans-serif" font-weight="700" fill="white">${label}</text></svg>`;
    return holder;
  }

  function createCard(file) {
    const card = document.createElement("a");
    card.className = file.preview_url ? "file-card has-preview" : "file-card";
    card.href = file.download_url;
    card.download = file.name;
    card.title = window.LocalI18n ? LocalI18n.t('下载 {name}', {name: file.name}) : `下载 ${file.name}`;
    card.setAttribute("aria-label", card.title);
    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("span");
    name.className = "file-name";
    name.textContent = file.name;
    info.appendChild(name);
    const size = document.createElement("span");
    size.className = "file-size";
    size.textContent = formatSize(file.bytes);
    if (file.preview_url) {
      const preview = document.createElement("img");
      preview.className = "file-preview";
      preview.alt = file.name;
      preview.loading = "lazy";
      preview.src = file.preview_url;
      preview.addEventListener("error", () => {
        preview.replaceWith(fileIcon(file.category));
        info.appendChild(size);
      }, { once: true });
      card.appendChild(preview);
    } else {
      card.appendChild(fileIcon(file.category));
      info.appendChild(size);
    }
    card.appendChild(info);
    return card;
  }
  function characterCount(text) { return Array.from(text).length; }
  return { createCard, formatSize, characterCount };
})();
