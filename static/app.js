const folders = [];
const $ = (id) => document.getElementById(id);
let activeJob = null;
let pollTimer = null;

function showNotice(message) {
  const notice = $("notice");
  notice.textContent = message;
  notice.classList.remove("hidden");
  window.setTimeout(() => notice.classList.add("hidden"), 4500);
}

function renderFolders() {
  const list = $("folderList");
  list.replaceChildren();
  folders.forEach((folder, index) => {
    const item = document.createElement("li");
    item.className = "folder-item";
    const path = document.createElement("span");
    path.className = "folder-path";
    path.textContent = folder;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.setAttribute("aria-label", "Remove folder");
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      folders.splice(index, 1);
      renderFolders();
    });
    item.append(path, remove);
    list.append(item);
  });
}

function addFolder(path) {
  const value = path.trim();
  if (!value) return;
  if (!folders.includes(value)) folders.push(value);
  $("folderInput").value = "";
  renderFolders();
}

async function browseInto(input) {
  try {
    const response = await fetch("/browse", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if (data.path) {
      if (input === "folderInput") addFolder(data.path);
      else $(input).value = data.path;
    }
  } catch (error) {
    showNotice(error.message || "Folder picker failed.");
  }
}

$("addFolder").addEventListener("click", () => addFolder($("folderInput").value));
$("folderInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") addFolder($("folderInput").value);
});
$("browse").addEventListener("click", () => browseInto("folderInput"));
$("browseOutput").addEventListener("click", () => browseInto("outputDir"));
$("quality").addEventListener("input", () => {
  $("qualityValue").textContent = $("quality").value;
});
$("resizeEnabled").addEventListener("change", () => {
  $("resizeSetting").classList.toggle("hidden", !$("resizeEnabled").checked);
});

function bytes(value) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(2)} ${units[unit]}`;
}

function reportRow(report, index, total) {
  const row = document.createElement("article");
  row.className = "report-row";
  const title = document.createElement("h3");
  title.textContent = report.source;
  const stats = document.createElement("p");
  stats.textContent = `${report.files} files · ${report.images} images · ${bytes(report.original_size)} → ${bytes(report.new_size)} · ${report.saved_percent}% saved`;
  row.append(title, stats);
  if (report.failures.length) {
    const failureTitle = document.createElement("p");
    failureTitle.className = "failure";
    failureTitle.textContent = `${report.failures.length} failed file(s):`;
    row.append(failureTitle);
    report.failures.forEach((failure) => {
      const line = document.createElement("p");
      line.className = "failure";
      line.textContent = `${failure.file}: ${failure.error}`;
      row.append(line);
    });
  }
  const open = document.createElement("button");
  open.className = "button secondary";
  open.textContent = "Open output folder";
  open.addEventListener("click", async () => {
    const response = await fetch(`/open/${activeJob}/${index}`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) showNotice(data.error);
  });
  row.append(open);
  return row;
}

function renderReport(reports, status) {
  const content = $("reportContent");
  content.replaceChildren();
  let original = 0;
  let compressed = 0;
  let images = 0;
  let files = 0;
  reports.forEach((report, index) => {
    original += report.original_size;
    compressed += report.new_size;
    images += report.images;
    files += report.files;
    content.append(reportRow(report, index, reports.length));
  });
  if (status === "complete") {
    const total = document.createElement("article");
    total.className = "report-row";
    const title = document.createElement("h3");
    title.textContent = "Total";
    const stats = document.createElement("p");
    const saved = original ? ((original - compressed) * 100 / original).toFixed(1) : "0.0";
    stats.textContent = `${files} files · ${images} images · ${bytes(original)} → ${bytes(compressed)} · ${saved}% saved`;
    total.append(title, stats);
    content.prepend(total);
  }
  $("report").classList.toggle("hidden", reports.length === 0);
}

async function poll() {
  if (!activeJob) return;
  try {
    const response = await fetch(`/status/${activeJob}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error);
    const fileProgress = job.file_total ? Math.round((job.file_done / job.file_total) * 100) : 0;
    const overall = job.folder_total
      ? Math.round(((job.folders_done + fileProgress / 100) / job.folder_total) * 100)
      : 0;
    $("progress").value = job.status === "complete" ? 100 : overall;
    $("progressPercent").textContent = `${job.status === "complete" ? 100 : overall}%`;
    $("progressTitle").textContent = job.current_folder
      ? `Folder ${Math.min(job.folder_index + 1, job.folder_total)} of ${job.folder_total} · ${fileProgress}% of current folder`
      : "Preparing…";
    $("currentFile").textContent = job.current_file || "";
    $("statusText").textContent = job.status === "complete"
      ? "Compression finished."
      : `Completed ${job.folders_done} of ${job.folder_total} folders.`;
    renderReport(job.reports || [], job.status);
    if (job.status === "complete" || job.status === "failed") {
      clearInterval(pollTimer);
      $("start").disabled = false;
      if (job.error) showNotice(job.error);
      return;
    }
  } catch (error) {
    clearInterval(pollTimer);
    $("start").disabled = false;
    showNotice(error.message || "Could not read job status.");
  }
}

$("start").addEventListener("click", async () => {
  if (!folders.length) {
    showNotice("Add at least one folder first.");
    return;
  }
  $("start").disabled = true;
  $("progressArea").classList.remove("hidden");
  $("report").classList.add("hidden");
  $("progress").value = 0;
  $("statusText").textContent = "Starting…";
  const payload = {
    folders: [...folders],
    process_subfolders: $("processSubfolders").checked,
    quality: Number($("quality").value),
    max_size: $("resizeEnabled").checked ? Number($("maxSize").value) : null,
    output_dir: $("outputDir").value.trim() || null,
    strip_metadata: $("stripMetadata").checked,
    quantize_png: $("quantizePng").checked,
    copy_non_images: $("copyNonImages").checked,
  };
  try {
    const response = await fetch("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    activeJob = data.job_id;
    poll();
    pollTimer = window.setInterval(poll, 800);
  } catch (error) {
    $("start").disabled = false;
    showNotice(error.message || "Could not start compression.");
  }
});
