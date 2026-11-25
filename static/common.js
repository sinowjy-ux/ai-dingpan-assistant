// 各页面共用：导航、界面颜色、首次使用免责声明、收藏、退出程序、提示条
{ const q = new URLSearchParams(location.search).get("theme");    // 链接里带 ?theme=light/dark/system 时直接切换
  if (["dark", "light", "system"].includes(q)) localStorage.setItem("aidp_theme", q); }
document.documentElement.dataset.theme = localStorage.getItem("aidp_theme") || "dark";
const NAV = [["/dashboard.html", "统计"], ["/review.html", "每日复盘"], ["/monitor.html", "AI 盯盘"],
             ["/screener.html", "主力选股"], ["/", "个股研判"]];
const APP_NAME = "AI 盯盘助手";

async function api(p, opt) {
  const r = await fetch(p, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}
const post = (p, body) => api(p, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const sgn = (x, d = 2) => x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "dim";
const yi = x => x == null ? "—" : Math.abs(x) >= 10000 ? (x / 10000).toFixed(2) + " 万亿" : x.toFixed(1) + " 亿";

function toast(t) {
  let el = document.getElementById("toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; document.body.appendChild(el); }
  el.textContent = t; el.hidden = false;
  clearTimeout(el._t); el._t = setTimeout(() => el.hidden = true, 2600);
}

function renderNav() {
  const nav = document.querySelector("nav.top");
  if (!nav) return;
  const here = location.pathname === "/index.html" ? "/" : location.pathname;
  nav.innerHTML = `<span class="brand">${APP_NAME}<small id="app-ver" style="font-weight:600;font-size:10.5px"></small></span>` +
    `<span class="seg">` + NAV.map(([h, t]) => `<a href="${h}" class="${h === here ? "on" : ""}">${t}</a>`).join("") + `</span>` +
    `<span class="sp"></span><select class="theme" id="theme-sel" title="界面颜色"><option value="dark">◐ 深色</option><option value="light">◑ 浅色</option><option value="system">◒ 跟随系统</option></select>` +
    `<button class="quit" id="quit-btn" title="关闭后台程序（Windows 版关闭窗口后请点这里）">退出程序</button>`;
  const ts = document.getElementById("theme-sel");
  ts.value = localStorage.getItem("aidp_theme") || "dark";
  ts.onchange = () => { localStorage.setItem("aidp_theme", ts.value); document.documentElement.dataset.theme = ts.value; window.dispatchEvent(new Event("resize")); };
  api("/api/version").then(v => { const e = document.getElementById("app-ver"); if (e) e.textContent = "v" + v.version + " " + v.channel; }).catch(() => {});
  document.getElementById("quit-btn").onclick = async () => {
    if (!confirm("退出后台程序？正在进行的盯盘和扫描会停止。")) return;
    try { await post("/api/shutdown"); } catch (e) { /* 已退出 */ }
    document.body.innerHTML = `<div class="empty" style="padding:80px">${APP_NAME} 已退出，可以关闭这个窗口。</div>`;
  };
}

function disclaimer() {
  if (localStorage.getItem("aidp_disclaimer_v1")) return;
  const m = document.createElement("div");
  m.className = "modal";
  m.innerHTML = `<div class="box"><h3>使用前请阅读</h3><ol>
    <li>本软件是个人编写的<b>学习与研究工具</b>，所有选股、盯盘信号都是规则的机械输出，<b>不构成任何投资建议</b>，不推荐任何具体股票。</li>
    <li>回测和实盘统计只反映历史，不代表未来收益。股市有风险，投资决策和盈亏由使用者自行负责。</li>
    <li>行情数据来自腾讯、新浪、东方财富、Yahoo、Nasdaq 等公开接口，可能延迟、缺失或出错，仅供个人学习使用，请勿用于商业用途或二次分发数据。</li>
    <li>软件免费、开源，作者不收费、不带单、不提供荐股服务。任何以本软件名义收费的行为都与作者无关。</li>
    <li>所有数据只保存在你自己的电脑上，不上传任何服务器。</li></ol>
    <div style="text-align:right;margin-top:12px"><button class="btn" id="dis-ok">我已了解，继续使用</button></div></div>`;
  document.body.appendChild(m);
  document.getElementById("dis-ok").onclick = () => { localStorage.setItem("aidp_disclaimer_v1", "1"); m.remove(); };
  document.getElementById("dis-ok").focus();
}

// 收藏：source|market|date|code|method（source：screener 选股 / monitor 盯盘 / stock 个股研判）
const FAV = {
  keys: new Set(),
  key: (s, m, d, c, me) => [s, m, d, c, me].join("|"),
  async load() {
    try {
      const r = await api("/api/db/favorites");
      this.keys = new Set(r.favorites.map(f => this.key(f.source, f.market, f.date, f.code, f.method)));
    } catch (e) { /* 忽略 */ }
  },
  btn(it) {
    const k = this.key(it.source, it.market, it.date, it.code, it.method);
    const on = this.keys.has(k);
    return `<button class="star ${on ? "on" : ""}" data-fav='${esc(JSON.stringify(it))}' title="${on ? "取消收藏" : "收藏（存进数据库）"}">${on ? "★" : "☆"}</button>`;
  },
  async toggle(btn) {
    const it = JSON.parse(btn.dataset.fav);
    const k = this.key(it.source, it.market, it.date, it.code, it.method);
    const on = !this.keys.has(k);
    await post("/api/db/favorite", {item: it, on: on ? 1 : 0});
    on ? this.keys.add(k) : this.keys.delete(k);
    btn.classList.toggle("on", on); btn.textContent = on ? "★" : "☆";
    toast(on ? "★ 已收藏 " + it.name : "已取消收藏 " + it.name);
  },
};
document.addEventListener("click", e => {
  const b = e.target.closest("button.star[data-fav]");
  if (b) { e.stopPropagation(); FAV.toggle(b).catch(err => toast("收藏失败：" + err.message)); }
}, true);

function bjNow(fmt) {
  const d = new Date(Date.now() + (new Date().getTimezoneOffset() + 480) * 60000);
  const p = n => String(n).padStart(2, "0");
  return fmt === "time" ? `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
    : `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

document.addEventListener("DOMContentLoaded", () => { renderNav(); disclaimer(); });
