/* Agent Inventory — 前端（原生 JS，無打包） */
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.setAttribute("style", v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false || kid === true) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { data: null, tool: null, filter: "all", q: "", sort: "name" };
  const DAY = 86400000;
  const staleMs = () => (state.data?.usageWindowDays || 90) * DAY;
  const KIND = { rule: "規則", skill: "技能", note: "說明" };
  const SOURCE = { user: "自建", plugin: "外掛", builtin: "內建", bundled: "內附", compat: "相容讀取" };
  const SUMSRC = { frontmatter: "摘要來源：技能 frontmatter 的 description", agent: "摘要來源：AI agent 讀檔撰寫", user: "摘要來源：你在網頁上手改，agent 不會覆蓋", import: "摘要來源：自動判定為引用檔", note: "", pending: "尚未撰寫摘要，請執行 inventory-summarize 技能" };

  // ---------------------------------------------------------------- 載入
  fetch("../data/inventory.json", { cache: "no-store" })
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(init)
    .catch((err) => {
      $("#lede").innerHTML = `讀不到 <code>data/inventory.json</code>。請先在專案目錄執行 <code>python3 bin/scan.py</code>，再用 <code>python3 bin/serve.py</code> 開啟本頁。<br><small class="mono">${esc(err.message)}</small>`;
    });

  function init(data) {
    state.data = data;
    const first = data.tools.find((t) => t.installed) || data.tools[0];
    state.tool = first?.id;
    $("#generatedAt").textContent = "掃描時間 " + fmtTime(data.generatedAt);
    const s = data.stats;
    $("#lede").textContent = `這台電腦上有 ${s.installedTools} 個 AI agent 工具，共載入 ${s.rules} 條規則與 ${s.skills} 個技能；其中 ${s.shared} 個項目透過 symlink 或共用目錄同時餵給多個工具。點任何卡片可看完整摘要與路徑。`;
    $("#configLine").textContent = `掃描根目錄 ${data.config.projectRoots.join("、")} · 深度 ${data.config.scanDepth}`;
    renderUsageNote();
    renderStats(); renderMatrix(); renderNav(); renderTool();
    if (!state.bound) { bindToolbar(); state.bound = true; }
    $("#app").hidden = false;
  }
  function reload() {
    return fetch("../data/inventory.json", { cache: "no-store" }).then((r) => r.json()).then((data) => {
      state.data = data;
      if (!data.tools.some((t) => t.id === state.tool)) state.tool = data.tools[0]?.id;
      renderUsageNote(); renderStats(); renderMatrix(); renderNav(); renderTool();
    });
  }
  function renderUsageNote() {
    const src = state.data.usageSources || {};
    const on = state.data.tools.filter((t) => src[t.id]?.available).map((t) => t.name);
    const off = state.data.tools.filter((t) => t.installed && src[t.id] && !src[t.id].available).map((t) => t.name);
    $("#usageNote").textContent = on.length
      ? `使用紀錄來源：${on.join("、")}${off.length ? `；無法取得：${off.join("、")}` : ""}。技能依名稱對應各工具的呼叫紀錄，專案依工作目錄對應 agent 工作階段；沒有紀錄的項目退回顯示檔案修改時間。`
      : "尚未收集使用紀錄。執行 python3 bin/usage.py 或重新掃描即可。";
  }

  // ---------------------------------------------------------------- 總覽
  function renderStats() {
    const s = state.data.stats;
    const cells = [
      [s.rules, "條規則", "rules"], [s.skills, "個技能", "skills"], [s.projects, "個專案", "projects"],
      [s.shared, "個跨工具共用", "shared"], [s.unused90 ?? "—", `個技能 ${state.data.usageWindowDays || 90} 天未用`, "unused"], [s.pending, "筆待補摘要", "pending"],
    ];
    $("#stats").replaceChildren(...cells.map(([n, l]) => h("div", { class: "stat" }, h("div", { class: "stat__n" }, n), h("div", { class: "stat__l" }, l))));
  }

  function counts(tool) {
    const pr = tool.projects.reduce((a, p) => a + p.rules.length, 0);
    const ps = tool.projects.reduce((a, p) => a + p.skills.length, 0);
    return { gr: tool.global.rules.filter((id) => state.data.items[id]?.kind !== "note").length, gs: tool.global.skills.length, pr, ps, p: tool.projects.length };
  }

  function renderMatrix() {
    const head = h("tr", {}, h("th", {}, "工具"), h("th", {}, "全域規則"), h("th", {}, "全域技能"), h("th", {}, "專案"), h("th", {}, "專案規則"), h("th", {}, "專案技能"));
    const rows = state.data.tools.map((t) => {
      const c = counts(t);
      const num = (n) => h("td", {}, h("span", { class: n ? "" : "n0" }, n));
      return h("tr", { class: t.installed ? "" : "is-off", onclick: () => selectTool(t.id), style: "cursor:pointer" },
        h("td", {}, h("span", { class: "dot", style: `--c:${t.color}` }), t.name, t.installed ? "" : h("span", { class: "mono", style: "margin-left:8px;font-size:10px;color:var(--ink-3)" }, "未偵測到")),
        num(c.gr), num(c.gs), num(c.p), num(c.pr), num(c.ps));
    });
    $("#matrix").replaceChildren(h("thead", {}, head), h("tbody", {}, rows));
  }

  // ---------------------------------------------------------------- 工具分頁
  function renderNav() {
    const nav = $("#toolnav");
    nav.replaceChildren(...state.data.tools.map((t) => {
      const c = counts(t);
      return h("button", { class: `tab ${t.id === state.tool ? "is-on" : ""} ${t.installed ? "" : "is-off"}`, "data-id": t.id, onclick: () => selectTool(t.id) },
        h("span", { class: "dot", style: `--c:${t.color}` }), t.name,
        t.installed ? h("span", { class: "count" }, c.gr + c.gs + c.pr + c.ps) : h("span", { class: "off" }, "未偵測到"));
    }));
  }
  function selectTool(id) {
    state.tool = id;
    for (const b of document.querySelectorAll(".tab")) b.classList.toggle("is-on", b.dataset.id === id);
    renderTool();
    $("#tool").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bindToolbar() {
    $("#search").addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); renderTool(); });
    $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; renderTool(); });
    $("#modalCancel").addEventListener("click", closeModal);
    $("#modalScrim").addEventListener("click", closeModal);
    $("#filters").addEventListener("click", (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      state.filter = b.dataset.filter;
      for (const c of document.querySelectorAll(".chip")) c.classList.toggle("is-on", c === b);
      renderTool();
    });
    $("#drawerClose").addEventListener("click", closeDrawer);
    $("#drawerScrim").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (ed.open) closeEditor(false); else if ($("#modal").getAttribute("aria-hidden") === "false") closeModal(); else closeDrawer(); } });
  }

  // ---------------------------------------------------------------- 篩選
  function visible(item) {
    if (!item) return false;
    const f = state.filter;
    if (f === "rule" && item.kind !== "rule") return false;
    if (f === "skill" && item.kind !== "skill") return false;
    if (f === "shared" && item.tools.length < 2) return false;
    if (f === "user" && item.source !== "user") return false;
    if (f === "plugin" && !["plugin", "builtin", "bundled"].includes(item.source)) return false;
    if (f === "unused" && !(item.kind === "skill" && isStale(item.usage))) return false;
    if (state.q) {
      const hay = `${item.name} ${item.summary} ${item.description} ${item.path} ${item.tag || ""} ${item.project || ""}`.toLowerCase();
      if (!hay.includes(state.q)) return false;
    }
    return true;
  }

  // ---------------------------------------------------------------- 工具內容
  function renderTool() {
    const t = state.data.tools.find((x) => x.id === state.tool);
    const root = $("#tool");
    root.style.setProperty("--tool", t.color);
    document.documentElement.style.setProperty("--tool", t.color);
    const items = state.data.items;
    const pick = (ids) => sortItems(ids.map((id) => items[id]).filter(visible));

    const head = h("div", { class: "tool__head" },
      h("h2", { class: "tool__name" }, h("span", { class: "dot", style: `--c:${t.color}` }), t.name),
      t.docs && h("a", { class: "tool__docs", href: t.docs, target: "_blank", rel: "noopener" }, "官方文件 ↗"));
    const notes = [];
    if (!t.installed) notes.push(h("div", { class: "note note--off" }, "這台電腦沒有偵測到這個工具的設定目錄。下面列出的是它「如果安裝了」會讀到的共用目錄內容。"));
    for (const n of t.notes || []) notes.push(h("div", { class: "note" }, n));

    const gRules = pick(t.global.rules), gSkills = pick(t.global.skills);
    const projR = t.projects.map((p) => ({ ...p, list: pick(p.rules) })).filter((p) => p.list.length);
    const projS = t.projects.map((p) => ({ ...p, list: pick(p.skills) })).filter((p) => p.list.length);

    root.replaceChildren(head, ...notes,
      section("01", "全域規則", gRules.length, grid(gRules), "沒有找到全域規則檔。"),
      section("02", "全域技能", gSkills.length, grid(gSkills), "沒有找到全域技能。"),
      section("03", "專案規則", projR.reduce((a, p) => a + p.list.length, 0), projects(projR), "掃描的專案裡沒有這個工具會讀的規則檔。"),
      section("04", "專案技能", projS.reduce((a, p) => a + p.list.length, 0), projects(projS), "掃描的專案裡沒有這個工具會讀的技能。"));
  }

  function sortItems(list) {
    if (state.sort === "recent") return list.sort((a, b) => (b.usage?.lastUsed || "").localeCompare(a.usage?.lastUsed || "") || a.name.localeCompare(b.name));
    if (state.sort === "count") return list.sort((a, b) => (b.usage?.count || 0) - (a.usage?.count || 0) || a.name.localeCompare(b.name));
    return list;
  }
  function isStale(u) { return !u || !u.lastUsed || (Date.now() - new Date(u.lastUsed).getTime()) > staleMs(); }
  function ago(iso) {
    if (!iso) return "";
    const d = Math.floor((Date.now() - new Date(iso).getTime()) / DAY);
    return d <= 0 ? "今天" : d === 1 ? "昨天" : d < 30 ? `${d} 天前` : d < 365 ? `${Math.floor(d / 30)} 個月前` : `${Math.floor(d / 365)} 年前`;
  }
  function usageLine(u, fallbackIso, cls = "card__use") {
    if (u && u.count) {
      const dots = state.data.tools.filter((t) => u.byTool[t.id]).map((t) => h("span", { class: "dot", style: `--c:${t.color}`, title: `${t.name} ${u.byTool[t.id].count} 次` }));
      return h("div", { class: `${cls} ${isStale(u) ? "is-stale" : ""}` }, `上次使用 ${ago(u.lastUsed)} · ${u.count} 次`, h("span", { class: "shared" }, dots));
    }
    return h("div", { class: `${cls} is-none` }, `無使用紀錄${fallbackIso ? " · 最後修改 " + ago(fallbackIso) : ""}`);
  }
  function section(num, title, count, body, empty) {
    return h("section", { class: "section" },
      h("div", { class: "section__head" }, h("span", { class: "section__num" }, num), h("h3", { class: "section__title" }, title), h("span", { class: "section__count" }, count)),
      count ? body : h("p", { class: "section__empty" }, state.q || state.filter !== "all" ? "沒有符合目前搜尋或篩選的項目。" : empty));
  }
  function grid(list) { return h("div", { class: "grid" }, list.map((it, i) => card(it, i))); }
  function projects(list) {
    return h("div", {}, list.map((p) => {
      const meta = state.data.projects?.[p.id];
      return h("div", { class: "project" },
        h("div", { class: "project__head" },
          h("button", { class: "project__name", onclick: () => meta && openProject(meta) }, p.name),
          h("span", { class: "project__path" }, p.path)),
        h("p", { class: `project__sum ${meta?.summary ? "" : "is-pending"}` }, meta?.summary || "尚未撰寫這個專案的目的摘要"),
        meta && usageLine(meta.usage, meta.gitLastCommit, "project__use"),
        grid(p.list));
    }));
  }
  function openProject(meta) {
    const tools = state.data.tools.filter((t) => meta.tools.includes(t.id));
    $("#drawerBody").replaceChildren(h("div", {},
      h("div", { class: "d-kicker" }, "專案", h("span", { class: "mono" }, meta.path)),
      h("h2", { class: "d-title" }, meta.name),
      summaryEditable(meta),
      h("div", { class: "d-h" }, "在這個專案裡讀規則或技能的工具"),
      h("ul", { class: "d-paths" }, tools.map((t) => h("li", {}, h("span", { class: "who" }, h("span", { class: "dot", style: `--c:${t.color}` }), t.name), h("span", {}, "")))),
      h("div", { class: "d-h" }, "數量"),
      h("div", { class: "d-meta" }, h("div", {}, h("b", {}, "規則"), meta.rules), h("div", {}, h("b", {}, "技能"), meta.skills), h("div", {}, h("b", {}, "git 最後 commit"), meta.gitLastCommit ? fmtTime(meta.gitLastCommit) : "不是 git 倉庫")),
      usageBlock(meta.usage),
      h("div", { class: "d-actions" },
        h("button", { class: "btn btn--primary", onclick: (e) => openWith(meta.id, "reveal", e.target) }, isMac() ? "在 Finder 顯示" : "在檔案總管顯示"),
        h("button", { class: "btn", onclick: (e) => openWith(meta.id, "vscode", e.target) }, "VS Code"),
        h("button", { class: "btn", onclick: (e) => openWith(meta.id, "cursor", e.target) }, "Cursor"),
        h("button", { class: "btn", onclick: (e) => copy(meta.realPath || meta.path, e.target) }, "複製路徑"),
        h("button", { class: "btn btn--danger", onclick: () => confirmDelete(meta, "project") }, "刪除專案…"))));
    $("#drawer").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function card(it, i) {
    const shared = it.tools.length > 1;
    return h("button", { class: `card card--${it.kind}`, style: `--i:${Math.min(i, 24)}`, onclick: () => openDrawer(it) },
      h("div", { class: "card__top" }, h("div", { class: "card__name" }, it.name), h("span", { class: "card__kind" }, it.tag ? it.tag.replace(/^plugin:/, "") : KIND[it.kind])),
      h("div", { class: `card__sum ${it.summarySource === "pending" ? "is-pending" : ""}` }, it.summary || "尚未撰寫摘要"),
      it.kind === "skill" && usageLine(it.usage, it.updatedAt),
      h("div", { class: "card__foot" },
        h("div", { class: "tags" }, it.source !== "user" && h("span", { class: `tag tag--${it.source}` }, SOURCE[it.source] || it.source), it.isSymlink && h("span", { class: "tag" }, "symlink")),
        shared && sharedDots(it)));
  }
  function sharedDots(it) {
    const tools = state.data.tools.filter((t) => it.tools.includes(t.id));
    return h("span", { class: "shared", title: "共用於：" + tools.map((t) => t.name).join("、") },
      tools.map((t) => h("span", { class: "dot", style: `--c:${t.color}` })), h("span", { class: "shared__n" }, `×${tools.length}`));
  }

  // ---------------------------------------------------------------- 抽屜
  function openDrawer(it) {
    const tools = state.data.tools.filter((t) => it.tools.includes(t.id));
    const body = $("#drawerBody");
    const abs = it.realPath || it.path;
    // 用 h() 包一層，讓條件式產生的 false / 0 / null 被自動略過，不會變成文字
    body.replaceChildren(h("div", {},
      h("div", { class: "d-kicker" }, KIND[it.kind], it.tag && h("span", {}, "· " + it.tag), it.source !== "user" && h("span", {}, "· " + (SOURCE[it.source] || it.source)), h("span", {}, "· " + (it.scope === "global" ? "全域" : "專案")), it.project && h("span", { class: "mono" }, it.project)),
      h("h2", { class: `d-title ${it.kind === "rule" ? "mono" : ""}` }, it.name),
      summaryEditable(it),
      it.description && it.summarySource !== "frontmatter" && it.kind !== "note" && [h("div", { class: "d-h" }, "frontmatter description"), h("div", { class: "d-desc" }, it.description)],
      it.trigger && [h("div", { class: "d-h" }, "觸發 / 套用條件"), h("div", { class: "d-desc mono" }, it.trigger)],
      it.imports?.length ? [h("div", { class: "d-h" }, "引用"), h("div", { class: "d-desc mono" }, it.imports.join("、"))] : null,
      it.kind !== "note" && [h("div", { class: "d-h" }, `讀取這個檔案的工具（${tools.length}）`),
        h("ul", { class: "d-paths" }, tools.map((t) => h("li", {}, h("span", { class: "who" }, h("span", { class: "dot", style: `--c:${t.color}` }), t.name), h("code", {}, it.paths?.[t.id] || it.path))))],
      it.kind === "skill" && usageBlock(it.usage),
      it.kind !== "note" && [h("div", { class: "d-h" }, "檔案"),
        h("div", { class: "d-meta" },
          h("div", {}, h("b", {}, "實體路徑"), h("code", {}, it.realPath)),
          h("div", {}, h("b", {}, "最後修改"), fmtTime(it.updatedAt)),
          h("div", {}, h("b", {}, "大小"), fmtSize(it.size)),
          h("div", {}, h("b", {}, "內容 hash"), h("code", {}, it.hash)))],
      it.kind !== "note" && h("div", { class: "d-actions" },
        h("button", { class: "btn btn--primary", onclick: () => openEditor(it) }, "在網頁上編輯"),
        h("button", { class: "btn", onclick: (e) => openWith(it.id, "editor", e.target) }, isMac() ? "用文字編輯開啟" : "用記事本開啟"),
        h("button", { class: "btn", onclick: (e) => openWith(it.id, "reveal", e.target) }, isMac() ? "在 Finder 顯示" : "在檔案總管顯示"),
        h("button", { class: "btn", onclick: (e) => openWith(it.id, "vscode", e.target) }, "VS Code"),
        h("button", { class: "btn", onclick: (e) => openWith(it.id, "cursor", e.target) }, "Cursor"),
        h("button", { class: "btn", onclick: (e) => copy(abs, e.target) }, "複製路徑"),
        h("button", { class: "btn btn--danger", onclick: () => confirmDelete(it, "item") }, "刪除…"))));
    $("#drawer").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }
  function closeDrawer() { $("#drawer").setAttribute("aria-hidden", "true"); document.body.style.overflow = ""; }
  function usageBlock(u) {
    const src = state.data.usageSources || {};
    if (!u || !u.count) return [h("div", { class: "d-h" }, "使用紀錄"), h("div", { class: "d-desc" }, "沒有在任何 agent 的紀錄裡找到使用痕跡。")];
    const rows = state.data.tools.filter((t) => u.byTool[t.id]).map((t) =>
      h("li", {}, h("span", { class: "who" }, h("span", { class: "dot", style: `--c:${t.color}` }), t.name), h("span", { class: "n" }, `${u.byTool[t.id].count} 次 · 上次 ${fmtTime(u.byTool[t.id].last)}`)));
    const silent = state.data.tools.filter((t) => t.installed && !src[t.id]?.available).map((t) => t.name);
    return [h("div", { class: "d-h" }, `使用紀錄（共 ${u.count} 次，上次 ${ago(u.lastUsed)}）`), h("ul", { class: "d-usage" }, rows),
      silent.length && h("div", { class: "d-src", style: "margin:8px 0 0" }, `${silent.join("、")} 沒有可讀的使用紀錄，不代表沒用過。`)];
  }

  // ---------------------------------------------------------------- 刪除（移到垃圾桶）
  function confirmDelete(rec, kind) {
    const body = $("#modalBody"), ok = $("#modalConfirm");
    ok.disabled = true; ok.textContent = "移到垃圾桶";
    const isProject = kind === "project";
    const shared = !isProject && rec.tools.length > 1;
    const needType = isProject || shared;
    const toolNames = state.data.tools.filter((t) => (rec.tools || []).includes(t.id)).map((t) => t.name);
    body.replaceChildren(h("p", {}, "正在讀取實際會刪除的路徑…"));
    $("#modal").setAttribute("aria-hidden", "false");
    fetch(`../api/info?id=${encodeURIComponent(rec.id)}`).then((r) => r.json()).then((info) => {
      if (!info.ok) { body.replaceChildren(h("p", {}, info.error || "讀取失敗")); return; }
      let includeTarget = true;
      const list = () => h("ul", {}, info.targets.filter((t) => includeTarget || t.symlink).map((t) =>
        h("li", {}, h("span", { class: `tag ${t.symlink ? "tag--compat" : ""}` }, t.symlink ? "連結" : t.isDir ? "資料夾" : "檔案"), h("code", {}, t.path), !t.exists && h("span", { class: "tag" }, "已不存在"))));
      const listWrap = h("div", {}, list());
      const input = h("input", { class: "modal__input", placeholder: `輸入「${rec.name}」以確認`, autocomplete: "off" });
      input.addEventListener("input", () => { ok.disabled = input.value.trim() !== rec.name; });
      const check = h("label", { class: "modal__check" }, h("input", { type: "checkbox", checked: true, onchange: (e) => { includeTarget = e.target.checked; listWrap.replaceChildren(list()); } }),
        "連同實體檔案一起移到垃圾桶（取消勾選則只移除連結，其他工具仍保有這個技能）");
      const hasLink = info.targets.some((t) => t.symlink);
      body.replaceChildren(h("div", {},  // 包一層 h()，條件式產生的 false / null 才不會被當成文字
        h("p", {}, isProject ? "將把整個專案資料夾移到垃圾桶：" : `將把這個${rec.kind === "rule" ? "規則檔" : "技能"}移到垃圾桶：`, h("strong", {}, ` ${rec.name}`)),
        listWrap,
        isProject && info.info && h("p", { class: "mono", style: "font-size:12px" }, `共 ${info.info.files}${info.info.capped ? "+" : ""} 個檔案，${fmtSize(info.info.bytes)}`),
        shared && h("div", { class: "modal__warn" }, `這個項目同時被 ${toolNames.join("、")} 使用，刪除實體後這些工具都會失去它。`),
        hasLink && !isProject && check,
        h("div", { class: "modal__warn" }, "會移到系統垃圾桶，可從垃圾桶救回。刪除後會自動重新掃描。"),
        needType ? input : h("p", { style: "font-size:12.5px;color:var(--ink-3)" }, "按下按鈕即執行。")));
      if (!needType) ok.disabled = false;
      ok.onclick = () => doDelete(rec, includeTarget, needType ? input.value : rec.name);
      if (needType) input.focus();
    }).catch(() => body.replaceChildren(h("p", {}, "連不到 serve.py，無法刪除。")));
  }
  function doDelete(rec, includeTarget, confirm) {
    const ok = $("#modalConfirm"); ok.disabled = true; ok.textContent = "處理中…";
    fetch("../api/delete", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "agent-inventory" },
      body: JSON.stringify({ id: rec.id, includeTarget, confirm }) })
      .then((r) => r.json()).then((res) => {
        closeModal(); closeDrawer();
        const done = (res.results || []).filter((x) => x.ok).length, failed = (res.results || []).filter((x) => !x.ok);
        toast(res.ok ? `已移到垃圾桶（${done} 個路徑），畫面已更新。` : `部分失敗：${failed.map((f) => f.path + "：" + f.message).join("；") || res.error}`);
        return reload();
      }).catch((e) => { toast("刪除失敗：" + e.message); ok.disabled = false; ok.textContent = "移到垃圾桶"; });
  }
  function closeModal() { $("#modal").setAttribute("aria-hidden", "true"); }

  // ---------------------------------------------------------------- 摘要：網頁上直接改
  function summaryEditable(rec) {
    const wrap = h("div", {});
    const pending = rec.summarySource === "pending";
    const view = () => {
      wrap.replaceChildren(
        h("p", { class: `d-summary ${pending ? "is-pending" : ""}` }, rec.summary || "尚未撰寫摘要"),
        h("div", { class: "d-src" }, SUMSRC[rec.summarySource] || "", " ",
          h("button", { class: "btn btn--small", onclick: edit }, "改摘要"),
          rec.summarySource === "user" && h("button", { class: "btn btn--small", style: "margin-left:6px", onclick: () => saveSummary(rec, "") }, "交還給 agent")));
    };
    const edit = () => {
      const ta = h("textarea", { class: "d-summary-edit" });
      ta.value = rec.summary || "";
      wrap.replaceChildren(ta, h("div", { class: "d-summary-actions" },
        h("button", { class: "btn btn--primary btn--small", onclick: () => saveSummary(rec, ta.value) }, "儲存摘要"),
        h("button", { class: "btn btn--small", onclick: view }, "取消")));
      ta.focus();
    };
    view();
    return wrap;
  }
  function saveSummary(rec, text) {
    return api("../api/summary", { id: rec.id, summary: text }).then((res) => {
      toast(res.ok ? (res.locked ? "摘要已儲存，agent 之後不會覆蓋這一筆。" : "已交還給 agent，下次 inventory-summarize 會重寫。") : "儲存失敗：" + (res.error || ""));
      return reload().then(() => reopen(rec.id));
    });
  }
  function reopen(id) {
    const it = state.data.items[id]; if (it) return openDrawer(it);
    const p = state.data.projects?.[id]; if (p) return openProject(p);
    closeDrawer();
  }
  function api(url, payload) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "agent-inventory" }, body: JSON.stringify(payload) })
      .then((r) => r.json()).catch((e) => ({ ok: false, error: "連不到 serve.py：" + e.message }));
  }

  // ---------------------------------------------------------------- 檔案編輯器（CodeMirror 6，離線退回純文字）
  const ed = { open: false, item: null, hash: "", dirty: false, get: null, set: null, view: null };
  let cmPromise = null;
  function loadCodeMirror() {
    // CodeMirror 6 的各套件必須共用同一份 @codemirror/state，否則會出現「Unrecognized extension value」。
    // 用 esm.sh 的 ?deps= 把兩個入口釘到同一組相依版本，就只會載入一份。
    const deps = "@codemirror/state@6.7.4,@codemirror/view@6.43.11,@codemirror/language@6.12.4";
    if (!cmPromise) cmPromise = Promise.all([
      import(`https://esm.sh/codemirror@6.0.2?deps=${deps}`),
      import(`https://esm.sh/@codemirror/lang-markdown@6.5.2?deps=${deps}`),
    ]).then(([cm, md]) => ({ cm, md })).catch((e) => { cmPromise = null; throw e; });
    return cmPromise;
  }
  async function openEditor(it) {
    const box = $("#editor"), body = $("#editorBody"), status = $("#editorStatus");
    $("#editorName").textContent = it.name; $("#editorPath").textContent = ""; $("#editorShared").textContent = ""; status.textContent = "載入中…";
    body.replaceChildren(); $("#editorSave").disabled = true;
    box.setAttribute("aria-hidden", "false"); document.body.style.overflow = "hidden";
    const res = await fetch(`../api/read?id=${encodeURIComponent(it.id)}`).then((r) => r.json()).catch(() => ({ ok: false, error: "連不到 serve.py" }));
    if (!res.ok) { status.textContent = res.error || "讀取失敗"; return; }
    ed.item = it; ed.hash = res.hash; ed.dirty = false; ed.open = true;
    $("#editorPath").textContent = res.path;
    const shared = state.data.tools.filter((t) => (res.sharedWith || []).includes(t.id)).map((t) => t.name);
    $("#editorShared").textContent = shared.length > 1 ? `共用於 ${shared.join("、")}，存檔後全部生效` : "";
    const markDirty = () => { if (!ed.dirty) { ed.dirty = true; $("#editorSave").disabled = false; } status.textContent = "未儲存"; status.classList.add("is-dirty"); };
    try {
      const { cm, md } = await loadCodeMirror();
      const ev = new cm.EditorView({
        doc: res.content,
        extensions: [cm.basicSetup, md.markdown(), cm.EditorView.lineWrapping,
          cm.EditorView.updateListener.of((u) => { if (u.docChanged) markDirty(); })],
        parent: body,
      });
      ed.view = ev; ed.get = () => ev.state.doc.toString(); ed.set = (txt) => ev.dispatch({ changes: { from: 0, to: ev.state.doc.length, insert: txt } });
      status.textContent = "CodeMirror"; status.classList.remove("is-dirty");
      ev.focus();
    } catch (e) {
      // 離線或 CDN 被擋：純文字編輯器
      const gutter = h("div", { class: "editor__gutter" });
      const ta = h("textarea", { class: "editor__ta", spellcheck: "false" });
      ta.value = res.content;
      const lines = () => { gutter.textContent = Array.from({ length: ta.value.split("\n").length }, (_, i) => i + 1).join("\n"); };
      ta.addEventListener("input", () => { lines(); markDirty(); });
      ta.addEventListener("scroll", () => { gutter.scrollTop = ta.scrollTop; });
      ta.addEventListener("keydown", (k) => {
        if (k.key === "Tab") { k.preventDefault(); const s = ta.selectionStart, e2 = ta.selectionEnd; ta.value = ta.value.slice(0, s) + "  " + ta.value.slice(e2); ta.selectionStart = ta.selectionEnd = s + 2; ta.dispatchEvent(new Event("input")); }
        if ((k.metaKey || k.ctrlKey) && k.key === "s") { k.preventDefault(); saveEditor(); }
      });
      body.replaceChildren(h("div", { class: "editor__plain" }, gutter, ta));
      lines(); ed.view = null; ed.get = () => ta.value; ed.set = (txt) => { ta.value = txt; lines(); };
      status.textContent = "純文字模式（CodeMirror 無法載入：" + (e && e.message ? e.message.slice(0, 80) : "離線") + "）"; status.classList.remove("is-dirty");
      console.warn("CodeMirror 載入失敗，改用純文字編輯器", e);
      ta.focus();
    }
  }
  async function saveEditor() {
    if (!ed.open || !ed.dirty) return;
    const status = $("#editorStatus"); status.textContent = "儲存中…";
    const res = await api("../api/save", { id: ed.item.id, content: ed.get(), hash: ed.hash });
    if (!res.ok) {
      status.textContent = res.error || "儲存失敗"; status.classList.add("is-dirty");
      if (res.hash) toast(res.error);
      return;
    }
    ed.hash = res.hash; ed.dirty = false; $("#editorSave").disabled = true;
    status.textContent = "已儲存 " + new Date().toLocaleTimeString("zh-TW", { hour12: false }); status.classList.remove("is-dirty");
    toast("已存回原檔並重新掃描。這個檔的摘要會標為待更新，下次 inventory-summarize 補上。");
    await reload();
  }
  function closeEditor(force) {
    if (!ed.open) return;
    if (ed.dirty && !force && !confirm("有尚未儲存的修改，確定要關閉嗎？")) return;
    ed.open = false; ed.dirty = false;
    if (ed.view) { ed.view.destroy(); ed.view = null; }
    $("#editor").setAttribute("aria-hidden", "true");
    document.body.style.overflow = $("#drawer").getAttribute("aria-hidden") === "false" ? "hidden" : "";
    reopen(ed.item?.id);
  }
  $("#editorCancel").addEventListener("click", () => closeEditor(false));
  $("#editorSave").addEventListener("click", saveEditor);
  window.addEventListener("beforeunload", (e) => { if (ed.open && ed.dirty) { e.preventDefault(); e.returnValue = ""; } });
  document.addEventListener("keydown", (e) => { if (ed.open && (e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); saveEditor(); } }, true);
  function toast(msg) {
    let el = $("#toast");
    if (!el) { el = h("div", { id: "toast", class: "toast" }); document.body.append(el); }
    el.textContent = msg; el.classList.add("is-on");
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("is-on"), 5000);
  }
  function copy(text, btn) {
    navigator.clipboard?.writeText(expandHome(text)).then(() => { const o = btn.textContent; btn.textContent = "已複製"; setTimeout(() => (btn.textContent = o), 1200); });
  }
  function expandHome(p) { return p.startsWith("~") ? (state.data.home || "") + p.slice(1) : p; }
  function isMac() { return /Mac/i.test(navigator.platform || navigator.userAgent); }
  // 透過本機 serve.py 的 /api/open 呼叫作業系統開檔（瀏覽器本身無法啟動記事本／文字編輯）
  function openWith(id, how, btn) {
    const o = btn.textContent; btn.textContent = "開啟中…";
    fetch(`../api/open?id=${encodeURIComponent(id)}&with=${how}`).then((r) => r.json()).then((j) => {
      btn.textContent = j.ok ? "已送出" : "失敗";
      if (!j.ok) alert(`無法開啟：${j.error || j.message || "未知錯誤"}\n這個功能需要用 bin/serve.py 啟動網站。`);
    }).catch(() => { btn.textContent = "失敗"; alert("連不到 serve.py。請用 python3 bin/serve.py 啟動網站，直接開 index.html 無法呼叫本機程式。"); })
      .finally(() => setTimeout(() => (btn.textContent = o), 1400));
  }

  // ---------------------------------------------------------------- 工具函式
  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso); if (isNaN(d)) return iso;
    return d.toLocaleString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  }
  function fmtSize(n) { if (!n) return "—"; return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`; }
})();
