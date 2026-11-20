"use strict";

const byId = (id) => document.getElementById(id);
const refreshButton = byId("refresh");
const refreshStatus = byId("refresh-status");
const hostList = byId("hosts");
const notice = byId("notice");
const filters = document.querySelectorAll("[data-filter]");
const states = { low: "低占用", active: "有占用", unknown: "未知" };
const sampleClock = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  timeZone: "Asia/Shanghai",
});
let snapshot;
let filter = "all";

function escapeText(value) {
  return String(value).replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function gib(mib) {
  return mib === null ? "—" : (mib / 1024).toFixed(1);
}

function card(gpu, host, openDetails) {
  const key = `${escapeText(host)}-${gpu.index}`;
  const utilization = gpu.util === null ? "—" : `${gpu.util}%`;
  const memory = gpu.total === null ? "—" : `${gib(gpu.used)} / ${gib(gpu.total)} GiB`;
  const temperature = gpu.temp === null ? "—" : `${gpu.temp} °C`;
  const utilBar = gpu.util === null
    ? '<div class="track"></div>'
    : `<progress aria-label="GPU 利用率" value="${gpu.util}" max="100"></progress>`;
  const memoryBar = gpu.used === null || !gpu.total
    ? '<div class="track"></div>'
    : `<progress class="memory" aria-label="已用显存" value="${gpu.used}" max="${gpu.total}"></progress>`;
  const apps = gpu.processes.map((app) => (
    `<li><b>${app.username ? `用户 ${escapeText(app.username)}` : "用户未知"}</b> · ${escapeText(app.name)} · PID ${app.pid} · ${app.memory === null ? "显存未知" : `${gib(app.memory)} GiB`}</li>`
  )).join("");
  const processStatus = gpu.process_known ? `${gpu.processes.length} 个进程` : "进程数据不全";

  return `<article class="gpu" aria-label="GPU ${gpu.index}">
    <div class="gpu-head">
      <strong class="gpu-name"><span class="gpu-index">GPU ${gpu.index}</span>${escapeText(gpu.model)}</strong>
      <span class="gpu-status ${gpu.status}"><span class="dot"></span>${states[gpu.status]}</span>
    </div>
    <div class="metric"><span class="metric-label">利用率<b>${utilization}</b></span>${utilBar}</div>
    <div class="metric"><span class="metric-label">显存<b>${memory}</b></span>${memoryBar}</div>
    <div class="gpu-footer"><span>温度 <strong>${temperature}</strong></span><span>${processStatus}</span></div>
    ${apps ? `<details data-key="${key}" ${openDetails.has(key) ? "open" : ""}><summary>计算进程</summary><ul class="apps">${apps}</ul></details>` : ""}
  </article>`;
}

function render() {
  if (!snapshot) return;

  const { hosts, sampled_at: sampledAt } = snapshot;
  const gpus = hosts.flatMap((host) => host.gpus);
  const measured = gpus.filter((gpu) => gpu.total !== null && gpu.used !== null);
  const available = measured.reduce((total, gpu) => total + Math.max(0, gpu.total - gpu.used), 0);
  const online = hosts.filter((host) => host.state === "online").length;
  byId("online").innerHTML = `${online} <small>/ ${hosts.length}</small>`;
  byId("detected").textContent = gpus.length;
  byId("low").textContent = gpus.length ? gpus.filter((gpu) => gpu.status === "low").length : "—";
  byId("memory").innerHTML = measured.length ? `${gib(available)} <small>GiB</small>` : "—";

  const timestamp = byId("timestamp");
  timestamp.dateTime = sampledAt;
  timestamp.textContent = sampleClock.format(new Date(sampledAt));
  timestamp.title = "北京时间";

  // 轮询刷新时保留用户展开的进程详情和键盘焦点。
  const openDetails = new Set(Array.from(hostList.querySelectorAll("details[open]"), (item) => item.dataset.key));
  const focused = document.activeElement.closest("details")?.dataset.key;
  hostList.innerHTML = hosts.map((host) => {
    const cards = (filter === "low" ? host.gpus.filter((gpu) => gpu.status === "low") : host.gpus)
      .map((gpu) => card(gpu, host.name, openDetails)).join("");
    const hostStatus = { online: `在线 · ${host.gpus.length} 卡`, auth: "认证失败", error: "采样失败" }[host.state];
    const message = host.message || "当前没有符合筛选条件的 GPU。";
    return `<section class="host ${host.gpus.length > 2 ? "wide" : ""}">
      <header class="host-header">
        <div class="host-identity"><h3>${escapeText(host.name)}</h3><span class="host-address">${escapeText(host.address)}</span></div>
        <span class="node-state ${host.state === "online" ? "" : "error"}"><span class="dot"></span>${hostStatus}</span>
      </header>
      ${cards ? `<div class="gpus">${cards}</div>` : `<p class="host-message">${escapeText(message)}</p>`}
    </section>`;
  }).join("");
  if (focused) {
    hostList.querySelector(`details[data-key="${CSS.escape(focused)}"] summary`)?.focus({ preventScroll: true });
  }
}

async function refresh() {
  if (refreshButton.disabled) return;
  refreshButton.disabled = true;
  refreshStatus.textContent = "正在采样…";
  refreshStatus.classList.remove("error");
  try {
    const response = await fetch("/api/status", { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error("status");
    snapshot = await response.json();
    render();
    notice.hidden = true;
    refreshStatus.textContent = "每 15 秒自动刷新";
  } catch {
    refreshStatus.textContent = "更新失败";
    refreshStatus.classList.add("error");
    notice.textContent = snapshot ? "暂时无法更新。下方保留上次采样结果。" : "无法读取本地看板服务，请重试。";
    notice.hidden = false;
  } finally {
    refreshButton.disabled = false;
  }
}

filters.forEach((button) => {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    filters.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    render();
  });
});
refreshButton.addEventListener("click", refresh);
setInterval(() => {
  if (!document.hidden) refresh();
}, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
refresh();
