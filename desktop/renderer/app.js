// AI Lighting Studio — renderer (без сборки, без CDN).
import { mountViewer, disposeViewer } from './viewer3d.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fileUrl = (rel) => 'als://data/' + rel.split('/').map(encodeURIComponent).join('/');

const TABS = [
  ['overview', 'Обзор'], ['design', 'Дизайн'], ['3d', '3D'], ['engineering', 'Инженерия'],
  ['viz', 'Визуализация'], ['catalog', 'Каталог'], ['sales', 'Продажи'], ['versions', 'Версии'], ['autonomy', 'Режим автономности'],
];
const SOON = [
  ['materials', 'Материалы', 'Латунь, нерж, алюминий, алебастр, хрусталь/стекло; покрытия; допуски.'],
  ['lighting', 'Светотехника', 'Мощность, драйверы, падение напряжения, кривые, тепло, CCT 3000–4000K.'],
  ['production', 'Производство', 'Маршрут, сборка, упаковка, готовность к цеху.'],
  ['calculations', 'Расчёты', 'Сводка чисел из светотехники/материалов/геометрии в таблицы для спецификации и сметы.'],
  ['suppliers', 'Поставщики', 'RFQ CN/RU; ролевой доступ к ценам.'],
  ['qc', 'Контроль качества', 'IP, пожарные нормы, допуски, чеклист перед отгрузкой.'],
];
const STEP_RU = {
  'design.brief_from_goal': 'ТЗ из задачи (design_brief + концепции)', 'design.refine_brief': 'Доработка ТЗ по замечаниям',
  'visualization.design_review': 'Ревью дизайна (verify)', 'engineering.analyze_input': 'Анализ входа (фото/PDF/видео)',
  'engineering.revise_from_review': 'Ревизия по замечаниям', 'cad3d.build_parametric': 'Параметрическая 3D-модель',
  'cad3d.export_viz_spec': 'geometry.json + viz_scene', 'engineering.engineering_report': 'Инж. отчёт: тепло / электрика / механика',
  'viz.render_prompt': 'Промпт AI-рендера', 'viz.preview_2d': '2D-превью', 'catalogs.build_catalog_table': 'Таблица каталога (xlsx/csv)',
  'catalogs.site_fragment': 'HTML-фрагмент для сайта', 'sales.product_card': 'Карточка товара', 'sales.price_quote': 'Котировка RUB/CNY',
  'engineering.export_dxf': 'DXF-чертёж (ezdxf)', 'engineering.build_spec': 'Паспорт / спецификация', 'visualization.render': 'Рендер CCT 3000–4000K',
  'automation.make_rfq': 'RFQ поставщику', 'automation.update_catalog': 'Обновление каталога',
};
const MOD_RU = { design: 'Дизайн', cad3d: '3D', engineering: 'Инженерия', viz: 'Viz', visualization: 'Визуализация', catalogs: 'Каталог', sales: 'Продажи', automation: 'Автоматизация' };
const STATUS_RU = { draft: 'черновик', planning: 'планирование', engineering: 'инженерия', visualization: 'визуализация', automation: 'автоматизация', awaiting_confirm: 'ждёт подтверждения', done: 'готово', failed: 'ошибка' };
const AUTONOMY = [
  ['step_by_step', 'Помощник', 'Пауза после каждого шага — вы подтверждаете «Продолжить».'],
  ['confirm_key_points', 'Автономный', 'Сам гоняет цепочки; пауза на ключевых гейтах (ревью дизайна, RFQ, каталог).'],
  ['full_auto', 'Эксперт', 'Полностью автономно от задачи до карточки товара.'],
];

const state = { projects: [], pid: null, proj: null, tab: 'overview', cache: {}, pickPath: null, poll: null };

async function api(cmd, args) { return window.als.call(cmd, args); }
async function readText(rel) {
  if (state.cache[rel] !== undefined) return state.cache[rel];
  try { const t = await window.als.readText(rel); state.cache[rel] = t; return t; } catch { return null; }
}
async function readJSON(rel) { const t = await readText(rel); try { return t ? JSON.parse(t) : null; } catch { return null; } }
const rel = (f) => `projects/${state.pid}/${f}`;
const has = (f) => state.proj && state.proj.files.includes(f);

function renderTabs() {
  const nav = $('#tabs');
  nav.innerHTML = TABS.map(([k, n]) => `<div class="tab ${state.tab === k ? 'active' : ''}" data-tab="${k}">${n}</div>`).join('')
    + '<div class="tab-sep"></div>'
    + SOON.map(([k, n, d]) => `<div class="tab soon ${state.tab === 'soon:' + k ? 'active' : ''}" title="${esc(d)}" data-soon="${k}">${n}<small>скоро</small></div>`).join('');
  nav.querySelectorAll('[data-tab]').forEach((el) => el.onclick = () => showTab(el.dataset.tab));
  nav.querySelectorAll('[data-soon]').forEach((el) => el.onclick = () => showSoon(el.dataset.soon));
}

async function loadProjects() {
  state.projects = await api('list_projects');
  $('#projectList').innerHTML = state.projects.map((p) => {
    const st = p.running ? 'run' : p.status;
    return `<li data-id="${p.id}" class="${p.id === state.pid ? 'active' : ''}"><div class="pt">${esc(p.title)}</div>
      <div class="ps"><span class="dot ${st}"></span>${esc(STATUS_RU[p.status] || p.status)} · ${new Date(p.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}</div></li>`;
  }).join('') || '<li class="muted">Проектов пока нет</li>';
  $('#projectList').querySelectorAll('li[data-id]').forEach((li) => li.onclick = () => selectProject(li.dataset.id));
}

async function selectProject(id) {
  state.pid = id; state.cache = {};
  await refreshProject(true);
  await loadProjects();
}

async function refreshProject(force) {
  if (!state.pid) return;
  const p = await api('project', { id: state.pid });
  const changed = force || !state.proj || state.proj.updated_at !== p.updated_at || state.proj.running !== p.running || state.proj.files.length !== p.files.length;
  state.proj = p;
  if (changed) { state.cache = {}; renderHeader(); if (state.tab !== '3d' || force) await renderTab(); }
  clearTimeout(state.poll);
  if (p.running) state.poll = setTimeout(async () => { await refreshProject(false); if (!state.proj.running) loadProjects(); }, 900);
}

function renderHeader() {
  const p = state.proj;
  $('#pTitle').textContent = p.title;
  $('#pMeta').textContent = `${p.current_version ? 'v' + p.current_version + ' · ' : ''}${p.id} · пайплайн: ${p.pipeline || '—'} · режим: ${(AUTONOMY.find((a) => a[0] === p.autonomy) || [, p.autonomy])[1]}`;
  const st = p.running ? 'run' : p.status;
  const b = $('#pStatus'); b.className = 'badge ' + st; b.textContent = p.running ? 'выполняется…' : (STATUS_RU[p.status] || p.status);
  $('#btnContinue').classList.toggle('hidden', !(p.awaiting_confirm && !p.running));
  $('#btnRerun').classList.toggle('hidden', p.running);
  $('#btnFolder').classList.remove('hidden');
  $('#btnExport').classList.remove('hidden');
}

function showTab(t) { state.tab = t; renderTabs(); renderTab(); }
function showSoon(k) {
  const s = SOON.find((x) => x[0] === k);
  state.tab = 'soon:' + k; renderTabs();
  disposeViewer();
  $('#content').innerHTML = `<div class="card soon-box"><h3>${s[1]} — скоро</h3><p>${esc(s[2])}</p>
    <p class="muted">Модуль из брифа AI Lighting Studio (версия 2 — слой производства и снабжения). Подключится к тому же оркестратору через Task / Result / Artifact.</p></div>`;
}

async function renderTab() {
  if (state.tab.startsWith('soon:')) { showSoon(state.tab.slice(5)); return; }
  if (state.tab !== '3d') disposeViewer();
  const c = $('#content');
  if (!state.proj) { c.innerHTML = '<div class="empty">Выберите или создайте проект.</div>'; return; }
  const fn = { overview: tabOverview, design: tabDesign, '3d': tab3D, engineering: tabEngineering, viz: tabViz, catalog: tabCatalog, sales: tabSales, versions: tabVersions, autonomy: tabAutonomy }[state.tab];
  await fn(c);
}

function fileLinks(prefix) {
  const fs = state.proj.files.filter((f) => f.startsWith(prefix));
  if (!fs.length) return '<span class="muted">нет файлов</span>';
  return '<div class="files">' + fs.map((f) => `<div>📄 <a data-save="${esc(f)}">${esc(f)}</a></div>`).join('') + '</div>';
}
function bindSaves(root) { root.querySelectorAll('[data-save]').forEach((a) => a.onclick = () => window.als.saveAs(rel(a.dataset.save))); }
function rerunBtn(module, action, label) { return `<button class="btn btn-sm" data-rerun="${module}.${action}">↻ ${label || 'Повторить шаг'}</button>`; }
function bindReruns(root) {
  root.querySelectorAll('[data-rerun]').forEach((b) => b.onclick = async () => {
    const [module, action] = b.dataset.rerun.split('.');
    b.disabled = true;
    try { await api('rerun_step', { id: state.pid, module, action }); } catch (e) { alert(e.message); }
    await refreshProject(true);
  });
}
function notYet(what) { return `<div class="card"><h3>${what}</h3><p class="muted">Артефакт ещё не создан этим пайплайном. ${state.proj.running ? 'Пайплайн выполняется…' : 'Запустите пайплайн «Неделя 4».'}</p></div>`; }

async function tabOverview(c) {
  const p = state.proj;
  const tasks = p.tasks;
  const done = tasks.filter((t) => t.status === 'done').length;
  const pct = tasks.length ? Math.round((done / tasks.length) * 100) : 0;
  const steps = tasks.map((t, i) => `<li class="${t.status}"><span class="num">${t.status === 'done' ? '✓' : t.status === 'failed' ? '!' : i + 1}</span>
    <span class="mod">${esc(MOD_RU[t.module] || t.module)}</span><span class="act">${esc(STEP_RU[t.module + '.' + t.action] || t.action)}<div class="muted">${t.module}.${t.action}${t.error ? ' — <span class="err">' + esc(t.error) + '</span>' : ''}</div></span>
    <span class="st">${{ queued: 'в очереди', running: 'выполняется', done: 'готово', failed: 'ошибка' }[t.status] || t.status}</span>
    ${p.running ? '' : rerunBtn(t.module, t.action, 'повторить')}</li>`).join('');
  const brief = has('design/design_brief.json') ? await readJSON(rel('design/design_brief.json')) : null;
  const quote = has('sales/price_quote.json') ? await readJSON(rel('sales/price_quote.json')) : null;
  c.innerHTML = `<div class="grid" style="grid-template-columns:2fr 1fr">
    <div class="card"><h3>Пайплайн оркестратора — ${done} / ${tasks.length} шагов</h3><div class="progress"><div style="width:${pct}%"></div></div>
      ${p.awaiting_confirm ? `<p>⏸ Пауза по режиму автономности (гейт <code>${esc(p.confirm_gate)}</code>). Нажмите «Продолжить».</p>` : ''}
      ${p.fail_reason ? `<p class="err">${esc(p.fail_reason)}</p>` : ''}
      <ul class="steps">${steps}</ul></div>
    <div>
      <div class="card"><h3>Задача</h3><p>${esc(p.goal || p.title)}</p></div><br>
      ${has('viz/preview_2d.png') ? `<div class="card"><h3>Превью</h3><img class="preview" src="${fileUrl(rel('viz/preview_2d.png'))}"></div><br>` : ''}
      ${brief ? `<div class="card"><h3>Ключевые параметры</h3><div class="kv">
        <div>Тип</div><div>${esc(brief.fixture_type)}</div><div>Габариты</div><div>${esc(Object.entries(brief.dimensions_mm || {}).map(([k, v]) => k + ' ' + v).join(', '))} мм</div>
        <div>Материалы</div><div>${esc((brief.materials || []).join(', '))}</div><div>LED</div><div>${brief.led ? `${brief.led.count}× · ${brief.led.watts_est} W · ${brief.led.cct_k}K` : '—'}</div>
        ${quote ? `<div>Цена</div><div><b>${fmt(quote.price.RUB)} ₽</b> · ${fmt(quote.price.CNY)} ¥</div>` : ''}</div></div><br>` : ''}
      <div class="card"><h3>Файлы проекта (${p.files.length})</h3>${fileLinks('')}</div>
    </div></div>`;
  bindSaves(c); bindReruns(c);
}
const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('ru-RU', { maximumFractionDigits: 2 }));

async function tabDesign(c) {
  if (!has('design/design_brief.json')) { c.innerHTML = notYet('Дизайн-ТЗ'); return; }
  const brief = await readJSON(rel('design/design_brief.json'));
  const concepts = await readJSON(rel('design/concepts.json'));
  const vars = (concepts && concepts.variants) || brief.variants || [];
  c.innerHTML = `<div class="grid">
    <div class="card"><h3>Design brief ${rerunBtn('design', 'brief_from_goal')}</h3><div class="kv">
      <div>Название</div><div>${esc(brief.title)}</div><div>Тип</div><div>${esc(brief.fixture_type)}</div>
      <div>Стиль</div><div>${(brief.style || []).map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div>
      <div>Материалы</div><div>${(brief.materials || []).map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div>
      <div>Габариты, мм</div><div>${esc(JSON.stringify(brief.dimensions_mm))}</div>
      <div>LED</div><div>${esc(JSON.stringify(brief.led))}</div><div>Цель</div><div>${esc(brief.goal)}</div></div></div>
    <div class="card"><h3>Концепции</h3><table class="t"><tr><th>ID</th><th>Вариант</th><th>Заметки</th></tr>
      ${vars.map((v) => `<tr><td>${esc(v.id)}${concepts && concepts.selected === v.id ? ' <span class="chip">выбран</span>' : ''}</td><td>${esc(v.label)}</td><td>${esc(v.notes)}</td></tr>`).join('')}</table></div>
    <div class="card"><h3>design_brief.json</h3><pre class="json">${esc(JSON.stringify(brief, null, 2))}</pre>${fileLinks('design/')}</div></div>`;
  bindSaves(c); bindReruns(c);
}

async function tab3D(c) {
  const g = await api('geometry', { id: state.pid });
  if (!g || !g.parts) { c.innerHTML = notYet('3D-геометрия'); return; }
  c.innerHTML = `<div id="viewer"><div class="viewer-hud">${esc(g.title || '')} · ${esc(g.fixture_type)} · bbox ${esc(JSON.stringify(g.bbox_mm || {}))} мм<br>ЛКМ — вращение · колесо — зум · ПКМ — сдвиг</div></div>
    <div style="margin-top:10px;display:flex;gap:10px;align-items:center">${rerunBtn('cad3d', 'build_parametric', 'Пересобрать модель')}<span class="muted">Детали: ${(g.parts || []).map((p) => `${p.name}×${p.qty}`).join(', ')}</span></div>`;
  bindReruns(c);
  requestAnimationFrame(() => mountViewer($('#viewer'), g));
}

function md(src) {
  const lines = src.split(/\r?\n/); let out = ''; let inList = false; let inTable = false;
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>');
  for (const l of lines) {
    if (/^\s*\|/.test(l)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(l)) continue;
      const cells = l.trim().replace(/^\||\|$/g, '').split('|');
      if (!inTable) { out += '<table class="t">'; inTable = true; out += '<tr>' + cells.map((x) => `<th>${inline(x.trim())}</th>`).join('') + '</tr>'; continue; }
      out += '<tr>' + cells.map((x) => `<td>${inline(x.trim())}</td>`).join('') + '</tr>'; continue;
    } else if (inTable) { out += '</table>'; inTable = false; }
    if (/^\s*[-*] /.test(l)) { if (!inList) { out += '<ul>'; inList = true; } out += `<li>${inline(l.replace(/^\s*[-*] /, ''))}</li>`; continue; }
    if (inList) { out += '</ul>'; inList = false; }
    const h = l.match(/^(#{1,4}) (.*)/);
    if (h) out += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; else if (l.trim()) out += `<p>${inline(l)}</p>`;
  }
  if (inList) out += '</ul>'; if (inTable) out += '</table>';
  return out;
}

async function tabEngineering(c) {
  const mdt = has('engineering/engineering_report.md') ? await readText(rel('engineering/engineering_report.md')) : null;
  const dxf = state.proj.files.find((f) => f.startsWith('engineering/') && f.endsWith('.dxf'));
  const input = state.proj.files.find((f) => f.startsWith('input/'));
  c.innerHTML = `<div class="grid" style="grid-template-columns:2fr 1fr">
    <div class="card md">${mdt ? md(mdt) : '<p class="muted">Инженерный отчёт ещё не создан.</p>'}<div>${rerunBtn('engineering', 'engineering_report', 'Пересчитать отчёт')}</div></div>
    <div><div class="card"><h3>DXF-чертёж</h3>${dxf ? `<p>Слои OUTLINE / HOLES / LED / NOTES (ezdxf, R2010).</p><button class="btn btn-gold" data-save="${esc(dxf)}">⬇ Скачать ${esc(dxf.split('/').pop())}</button>` : '<p class="muted">DXF ещё не экспортирован.</p>'}
      <div style="margin-top:8px">${rerunBtn('engineering', 'export_dxf', 'Экспорт DXF')}</div></div><br>
      ${input ? `<div class="card"><h3>Вход (фото/PDF/видео)</h3>${/\.(png|jpe?g|webp|bmp)$/i.test(input) ? `<img class="preview" src="${fileUrl(rel(input))}">` : ''}<p>${esc(input)}</p></div><br>` : ''}
      <div class="card"><h3>Файлы инженерии</h3>${fileLinks('engineering/')}</div></div></div>`;
  bindSaves(c); bindReruns(c);
}

async function tabViz(c) {
  const prompt = has('viz/render_prompt.txt') ? await readText(rel('viz/render_prompt.txt')) : null;
  c.innerHTML = `<div class="grid">
    <div class="card"><h3>2D-превью ${rerunBtn('viz', 'preview_2d')}</h3>${has('viz/preview_2d.png') ? `<img class="preview" src="${fileUrl(rel('viz/preview_2d.png'))}">` : '<p class="muted">нет превью</p>'}</div>
    <div class="card"><h3>Промпт AI-рендера ${rerunBtn('viz', 'render_prompt')}</h3>${prompt ? `<pre class="json" style="white-space:pre-wrap">${esc(prompt)}</pre>` : '<p class="muted">нет промпта</p>'}
      ${['cad3d/preview_3d.png', 'cad3d/preview_3d_alt.png'].filter(has).map((f) => `<img class="preview" style="margin-top:10px" src="${fileUrl(rel(f))}">`).join('')}
      <h3 style="margin-top:14px">Файлы</h3>${fileLinks('viz/')}</div></div>`;
  bindSaves(c); bindReruns(c);
}

async function tabCatalog(c) {
  if (!has('catalogs/catalog.json')) { c.innerHTML = notYet('Каталог'); return; }
  const cat = await readJSON(rel('catalogs/catalog.json'));
  const rows = cat.rows || [];
  const cols = ['model', 'title', 'dims', 'materials', 'led', 'style', 'price_stub_rub', 'price_stub_cny'];
  const colRu = { model: 'Модель', title: 'Название', dims: 'Габариты', materials: 'Материалы', led: 'LED', style: 'Стиль', price_stub_rub: 'Цена ₽', price_stub_cny: 'Цена ¥' };
  let frag = has('catalogs/site_fragment.html') ? await readText(rel('catalogs/site_fragment.html')) : '';
  frag = frag.replace(/src="([^"]*preview_2d\.png)"/g, () => `src="${fileUrl(rel('viz/preview_2d.png'))}"`);
  const fragDoc = `<!doctype html><meta charset="utf-8"><style>body{font-family:Georgia,serif;background:#faf7f0;color:#2a2418;padding:18px}
    .gilil-product-card{max-width:520px;border:1px solid #d9c9a0;border-radius:12px;padding:18px;background:#fff;box-shadow:0 4px 18px rgba(0,0,0,.08)}
    .gilil-product-card img{max-width:100%;border-radius:8px}.gilil-product-card ul{list-style:none;padding:0}.gilil-product-card li{display:flex;justify-content:space-between;border-bottom:1px solid #eee;padding:4px 0}
    .price-rub{font-size:24px;color:#8a6a2a;font-weight:bold;margin-right:10px}.btn{display:inline-block;background:#b08d47;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none}</style>${frag}`;
  c.innerHTML = `<div class="card"><h3>Таблица каталога (${rows.length}) ${rerunBtn('catalogs', 'build_catalog_table')}</h3>
      <table class="t"><tr>${cols.map((k) => `<th>${colRu[k]}</th>`).join('')}</tr>
      ${rows.map((r) => `<tr>${cols.map((k) => `<td>${esc(k.startsWith('price') ? fmt(r[k]) : r[k])}</td>`).join('')}</tr>`).join('')}</table>
      <div style="margin-top:12px;display:flex;gap:8px">${['catalogs/catalog.xlsx', 'catalogs/catalog.csv', 'catalogs/catalog.json', 'catalogs/site_fragment.html'].filter(has).map((f) => `<button class="btn" data-save="${f}">⬇ ${f.split('/').pop()}</button>`).join('')}</div></div><br>
    <div class="card"><h3>Фрагмент для сайта gilil_lighting ${rerunBtn('catalogs', 'site_fragment')}</h3><iframe class="frag" sandbox id="frag"></iframe></div>`;
  $('#frag').srcdoc = fragDoc;
  bindSaves(c); bindReruns(c);
}

async function tabSales(c) {
  if (!has('sales/price_quote.json')) { c.innerHTML = notYet('Продажи'); return; }
  const q = await readJSON(rel('sales/price_quote.json'));
  const card = has('sales/product_card.json') ? await readJSON(rel('sales/product_card.json')) : null;
  const h = q.heuristic || {};
  c.innerHTML = `<div class="grid">
    <div class="card"><h3>Котировка ${rerunBtn('sales', 'price_quote', 'Пересчитать')}</h3>
      <div class="price">${fmt(q.price.RUB)} ₽ <small>/ ${fmt(q.price.CNY)} ¥</small></div>
      <p class="muted">Себестоимость: ${fmt(q.cost.RUB)} ₽ / ${fmt(q.cost.CNY)} ¥ · наценка ×${q.markup} · курс ${h.fx_cny_per_rub} CNY/RUB</p>
      <table class="t"><tr><th>Статья</th><th>Значение</th></tr>
        ${(h.materials_breakdown || []).map((m) => `<tr><td>Материал: ${esc(m.material)} (${fmt(m.mass_kg)} кг)</td><td>${fmt(m.rub)} ₽</td></tr>`).join('')}
        <tr><td>LED</td><td>${fmt(h.led_cost_rub)} ₽</td></tr><tr><td>Сборка</td><td>${fmt(h.assembly_rub)} ₽</td></tr>
        <tr><td>Масса</td><td>${fmt(h.mass_kg)} кг</td></tr><tr><td>Мощность</td><td>${fmt(h.watts)} W</td></tr></table>
      <p class="muted">${esc(q.note || '')}</p></div>
    <div class="card"><h3>Карточка товара ${rerunBtn('sales', 'product_card')}</h3>${card ? `<p><b>${esc(card.title)}</b> · SKU ${esc(card.sku)}</p><p>${esc(card.description)}</p>
      <div class="kv">${Object.entries(card.spec_summary || {}).map(([k, v]) => `<div>${esc(k)}</div><div>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</div>`).join('')}</div>
      <p class="muted" style="margin-top:10px">${esc(card.terms || '')}</p>` : '<p class="muted">нет карточки</p>'}
      <div style="margin-top:10px">${fileLinks('sales/')}</div></div></div>`;
  bindSaves(c); bindReruns(c);
}

// ---------- Ф0: версии проекта ----------
const dt = (s) => new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
const KIND_RU = { manual: 'вручную', pipeline: 'пайплайн', rollback: 'откат' };
function askText(title, label, value, okLabel) {
  return new Promise((resolve) => {
    const m = $('#vmodal'); $('#vmTitle').textContent = title; $('#vmLabel').textContent = label;
    $('#vmInput').value = value || ''; $('#vmOk').textContent = okLabel || 'OK'; m.classList.remove('hidden'); $('#vmInput').focus();
    const done = (v) => { m.classList.add('hidden'); $('#vmOk').onclick = $('#vmCancel').onclick = $('#vmInput').onkeydown = null; resolve(v); };
    $('#vmOk').onclick = () => done($('#vmInput').value);
    $('#vmCancel').onclick = () => done(null);
    $('#vmInput').onkeydown = (e) => { if (e.key === 'Enter') done($('#vmInput').value); if (e.key === 'Escape') done(null); };
  });
}
function renderDiff(d) {
  const val = (x) => esc(typeof x === 'object' && x !== null ? JSON.stringify(x) : x ?? '—');
  const lab = (x) => (x === 'working' ? 'рабочая копия' : 'v' + x);
  return `<h3>Сравнение ${lab(d.a)} → ${lab(d.b)}</h3>
    <p class="muted">Файлы: <span class="dadd">+${d.added.length}</span> · <span class="drem">−${d.removed.length}</span> · <span class="dchg">~${d.changed.length}</span> · без изменений ${d.unchanged}</p>
    ${d.params.length ? `<table class="t"><tr><th>Файл</th><th>Параметр</th><th>Было</th><th>Стало</th></tr>${d.params.map((p) => `<tr><td>${esc(p.file.split('/').pop())}</td><td><code>${esc(p.key)}</code></td><td class="drem">${val(p.from)}</td><td class="dadd">${val(p.to)}</td></tr>`).join('')}</table>` : '<p class="muted">Ключевые параметры (design_brief / geometry) не менялись.</p>'}
    <div class="files" style="margin-top:8px">${d.added.map((f) => `<div class="dadd">+ ${esc(f)}</div>`).join('')}${d.removed.map((f) => `<div class="drem">− ${esc(f)}</div>`).join('')}${d.changed.map((f) => `<div class="dchg">~ ${esc(f)}</div>`).join('')}</div>`;
}
async function tabVersions(c) {
  const vs = await api('list_versions', { id: state.pid });
  const meta = state.proj.meta || {};
  state.vsel = (state.vsel || []).filter((v) => vs.some((x) => x.version === v));
  const busy = state.proj.running;
  c.innerHTML = `<div class="grid" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)">
    <div class="card"><h3>История версий (${vs.length}) <span class="muted">текущая: v${meta.current_version || 0}</span></h3>
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <button class="btn btn-gold" id="vSave" ${busy ? 'disabled' : ''}>💾 Сохранить версию</button>
        <button class="btn" id="vCmpWork">Сравнить с рабочей копией</button>
        <button class="btn" id="vCmp" ${state.vsel.length === 2 ? '' : 'disabled'}>⇄ Сравнить выбранные (${state.vsel.length}/2)</button>
      </div>
      <ul class="vlist">${vs.map((v) => `<li class="${v.current ? 'cur' : ''} ${state.vsel.includes(v.version) ? 'sel' : ''}">
        <div class="vnum">v${v.version}</div>
        <div><div class="vmsg">${esc(v.message)}<span class="vkind ${v.kind}">${KIND_RU[v.kind] || v.kind}</span>${v.current ? '<span class="vkind">текущая</span>' : ''}</div>
          <div class="muted">${dt(v.created_at)} · ${esc(v.author || '')} · ${v.file_count} файлов · ${(v.total_bytes / 1024).toFixed(0)} КБ${v.parent ? ' · от v' + v.parent : ''}${v.restored_from ? ' · восстановлено из v' + v.restored_from : ''} · <code>${v.tree_sha256.slice(0, 10)}</code></div></div>
        <div class="vacts"><button class="btn btn-sm" data-vsel="${v.version}">${state.vsel.includes(v.version) ? '✓' : '☐'} сравнить</button>
          <button class="btn btn-sm" data-vback="${v.version}" ${busy ? 'disabled' : ''}>↺ Откатить</button></div></li>`).join('') || '<li class="muted">Версий пока нет — нажмите «Сохранить версию».</li>'}</ul></div>
    <div><div class="card"><h3>Проект</h3><div class="kv">
      <div>Имя</div><div><span class="pname" id="vName" title="Переименовать">${esc(meta.name || state.proj.title)}</span> ✎</div>
      <div>Тип</div><div>${esc(meta.fixture_type || '—')}</div><div>Создан</div><div>${meta.created_at ? dt(meta.created_at) : '—'}</div>
      <div>Изменён</div><div>${meta.updated_at ? dt(meta.updated_at) : '—'}</div><div>Автор</div><div>${esc(meta.author || '—')}</div>
      <div>Версия приложения</div><div>${esc(meta.app_version || '—')}</div></div>
      <div style="margin-top:10px;display:flex;gap:8px"><button class="btn" id="vExport">⇪ Экспорт .alsproj</button></div></div><br>
      <div class="card" id="vDiff">${state.vdiff ? renderDiff(state.vdiff) : '<h3>Сравнение</h3><p class="muted">Отметьте две версии и нажмите «Сравнить» — покажем добавленные / удалённые / изменённые файлы и изменения параметров ТЗ и геометрии.</p>'}</div></div></div>`;
  $('#vSave').onclick = async () => {
    const msg = await askText('Сохранить версию', 'Комментарий к версии', '', 'Сохранить');
    if (msg === null) return;
    try { await api('save_version', { id: state.pid, message: msg }); } catch (e) { alert(e.message); }
    await refreshProject(true);
  };
  $('#vCmpWork').onclick = async () => { const cur = meta.current_version || 0; state.vdiff = await api('diff_versions', { id: state.pid, a: cur, b: 'working' }); tabVersions(c); };
  $('#vCmp').onclick = async () => { const [a, b] = [...state.vsel].sort((x, y) => x - y); state.vdiff = await api('diff_versions', { id: state.pid, a, b }); tabVersions(c); };
  $('#vExport').onclick = exportProject;
  $('#vName').onclick = async () => {
    const n = await askText('Переименовать проект', 'Новое имя', meta.name || state.proj.title, 'Переименовать');
    if (!n) return; await api('rename_project', { id: state.pid, name: n }); await refreshProject(true); loadProjects();
  };
  c.querySelectorAll('[data-vsel]').forEach((b) => b.onclick = () => {
    const v = Number(b.dataset.vsel); state.vsel = state.vsel.includes(v) ? state.vsel.filter((x) => x !== v) : [...state.vsel, v].slice(-2); tabVersions(c);
  });
  c.querySelectorAll('[data-vback]').forEach((b) => b.onclick = async () => {
    const v = Number(b.dataset.vback);
    if (!confirm(`Откатить рабочую копию к v${v}? Будет создана новая версия; история не удаляется.`)) return;
    try { await api('checkout_version', { id: state.pid, version: v }); state.vdiff = null; } catch (e) { alert(e.message); }
    await refreshProject(true);
  });
}
async function exportProject() {
  const dest = await window.als.pickExport((state.proj.meta && state.proj.meta.name) || state.proj.title);
  if (!dest) return;
  try { const r = await api('export_project', { id: state.pid, dest }); alert(`Экспортировано: ${r.path}\n${r.files} файлов, ${r.versions} версий`); } catch (e) { alert(e.message); }
}
async function importProject() {
  const src = await window.als.pickImport();
  if (!src) return;
  try { const r = await api('import_project', { path: src }); await loadProjects(); await selectProject(r.id); showTab('versions'); } catch (e) { alert('Импорт: ' + e.message); }
}

async function tabAutonomy(c) {
  const cur = state.proj.autonomy;
  c.innerHTML = `<div class="card"><h3>Режим автономности оркестратора</h3><p class="muted">Применяется к следующему запуску / продолжению этого проекта.</p>
    <div class="mode-cards">${AUTONOMY.map(([k, n, d]) => `<div class="card mode ${k === cur ? 'sel' : ''}" data-mode="${k}"><h3>${n}</h3><p>${d}</p><code>${k}</code></div>`).join('')}</div>
    <div style="margin-top:14px;display:flex;gap:8px"><button class="btn btn-gold" id="aRerun">↻ Перезапустить пайплайн в этом режиме</button></div></div>`;
  c.querySelectorAll('[data-mode]').forEach((el) => el.onclick = async () => {
    await api('set_autonomy', { id: state.pid, autonomy: el.dataset.mode });
    await refreshProject(true);
  });
  $('#aRerun').onclick = () => rerunPipeline();
}

async function rerunPipeline() {
  const r = await api('rerun_pipeline', { id: state.pid, autonomy: state.proj.autonomy });
  await selectProject(r.id); showTab('overview');
}

function setupModal() {
  const m = $('#modal');
  $('#btnNew').onclick = () => m.classList.remove('hidden');
  $('#nCancel').onclick = () => m.classList.add('hidden');
  $('#nPick').onclick = async () => { const p = await window.als.pickInput(); if (p) { state.pickPath = p; $('#nFile').textContent = p; $('#nClear').classList.remove('hidden'); } };
  $('#nClear').onclick = () => { state.pickPath = null; $('#nFile').textContent = 'не выбран'; $('#nClear').classList.add('hidden'); };
  $('#nCreate').onclick = async () => {
    try {
      const r = await api('create_project', { goal: $('#nGoal').value, pipeline: $('#nPipeline').value, autonomy: $('#nAutonomy').value, upload_path: state.pickPath });
      m.classList.add('hidden'); state.tab = 'overview'; renderTabs(); await selectProject(r.id);
    } catch (e) { alert('Ошибка: ' + e.message); }
  };
  $('#btnContinue').onclick = async () => { await api('confirm', { id: state.pid, autonomy: state.proj.autonomy }); await refreshProject(true); };
  $('#btnRerun').onclick = () => rerunPipeline();
  $('#btnExport').onclick = exportProject;
  $('#btnImport').onclick = importProject;
  $('#btnFolder').onclick = () => window.als.openPath(`projects/${state.pid}`);
}

async function boot() {
  renderTabs(); setupModal();
  const info = await window.als.ready();
  if (info.error) { $('#content').innerHTML = `<div class="card"><h3>Python-бэкенд не запустился</h3><pre class="err">${esc(info.error)}\n${esc(info.log || '')}</pre></div>`; return; }
  $('#backendInfo').textContent = `Python ${info.python} · данные: ${info.data_dir}`;
  window.als.onBackendExit(async (code) => { $('#content').innerHTML = `<div class="card"><h3>Бэкенд завершился (код ${code})</h3><pre class="err">${esc(await window.als.log())}</pre></div>`; });
  await loadProjects();
  const first = state.projects.find((p) => p.status === 'done') || state.projects[0];
  if (first) await selectProject(first.id);
  setInterval(loadProjects, 5000);
}

window.__als = { selectProject, api, diff: async (a, b) => { state.vdiff = await api('diff_versions', { id: state.pid, a, b }); state.vsel = [a, b]; }, showTab: (t) => { const s = SOON.find((x) => x[0] === t); s ? showSoon(t) : showTab(t); } };
window.__alsReady = boot().then(() => true).catch((e) => { $('#content').innerHTML = `<pre class="err">${esc(e.stack || e)}</pre>`; return false; });
