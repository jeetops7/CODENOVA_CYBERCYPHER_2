(() => {
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SEV = {CRITICAL:'#FF5C4D', HIGH:'#FF8A3D', MEDIUM:'#FFB340', LOW:'#9CC4FF'};
const STATUS = {IN_TRANSIT:'#DCE8FF', AT_CHECKPOINT:'#5EE0A0', DELAYED:'#FF5C4D', DELIVERED:'#8A93A6'};
const ENGINE_LABEL = {rules:'Offline', claude:'Claude', ollama:'Ollama'};

const STORE = 'sentinel.layers';
const layers = Object.assign({delayed: true, rerouted: true, normal: false, sea: true, air: true, rail: true, road: true},
  (() => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } })());
const LAYER_DEFS = [
  ['delayed', 'Delayed', '#FF5C4D'], ['rerouted', 'Rerouted', '#5EE0A0'], ['normal', 'On time', '#9CC4FF'],
  null, ['sea', 'Sea'], ['air', 'Air'], ['rail', 'Rail'], ['road', 'Road'],
];
const cls = (s) => (s.status === 'DELAYED' ? 'delayed' : s.mitigated ? 'rerouted' : 'normal');
let S = null, focusHub = null, picked = null, tab = 'incidents', fresh = false, flash = [], busy = false, query = '';

// ---------- globe ----------
const HOME = {lat: 24, lng: 15, altitude: 2.4};
const SIDE = {'Salt Lake Depot': 'l', 'Phoenix Hub': 'l', 'Denver Hub': 'l', 'Dallas Center': 'l', 'Louisville Hub': 'l', 'Chicago Transit': 'a', 'DC Connect': 'b', 'Rotterdam Gateway': 'l', 'Hamburg Port': 'a', 'London Thames Hub': 'l', 'Frankfurt Air Hub': 'b', 'Shenzhen Yantian': 'b', 'Hong Kong Air Hub': 'r', 'Busan Terminal': 'a', 'Mumbai Nhava Sheva': 'l', 'Panama Colon Hub': 'l', 'Long Beach Gateway': 'l', 'Atlanta Sort': 'r', 'Savannah Port': 'b'};
const hubPins = new Map(), cityPins = new Map();
const STROKE = {sea: 0.9, road: 0.7, rail: 0.8};
const ROUTES = {}, asked = new Set();


const world = Globe({animateIn: true, rendererConfig: {antialias: true, alpha: true, powerPreference: 'high-performance'}})($('#globe'))
  .globeImageUrl('vendor/earth-blue-marble.jpg')
  .bumpImageUrl('vendor/earth-topology.png')
  // sharp slippy-map imagery streamed per zoom level; the bundled texture is the offline fallback
  .globeTileEngineUrl((x, y, l) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${l}/${y}/${x}`)
  .backgroundColor('rgba(0,0,0,0)')
  .atmosphereColor('#8DB8FF').atmosphereAltitude(0.16)
  .pointOfView(HOME)
  .htmlLat('lat').htmlLng('lng').htmlAltitude(0.012)
  .htmlElement((d) => d.el)
  .arcStartLat((d) => d.a[0]).arcStartLng((d) => d.a[1]).arcEndLat((d) => d.b[0]).arcEndLng((d) => d.b[1])
  .arcAltitude((d) => d.alt).arcColor((d) => d.color).arcStroke(0.3)
  // sea / rail / road follow real surface routes; only air freight flies as arcs
  .pathPoints('pts').pathPointLat((p) => p[0]).pathPointLng((p) => p[1]).pathPointAlt(0.004).pathTransitionDuration(0)
  .pathColor((d) => d.color).pathStroke((d) => STROKE[d.mode] || 0.3)
  .pathDashLength((d) => (d.mode === 'rail' ? 0.012 : 1)).pathDashGap((d) => (d.mode === 'rail' ? 0.008 : 0)).pathDashAnimateTime(0)
  .arcDashLength(1).arcDashGap(0).arcDashAnimateTime(0)
  .ringColor((d) => (t) => `rgba(${d.rgb},${(1 - t) * 0.85})`).ringAltitude(0.009)
  .ringMaxRadius((d) => d.r).ringPropagationSpeed(1.6).ringRepeatPeriod((d) => d.period);

window.world = world;
const mat = world.globeMaterial();
mat.bumpScale = 3; mat.shininess = 8;
const ctl = world.controls();
ctl.autoRotate = true; ctl.autoRotateSpeed = 0.22; ctl.enableDamping = true; ctl.minDistance = 103;
ctl.addEventListener('start', () => { ctl.autoRotate = false; });
ctl.addEventListener('change', () => { const a = world.pointOfView().altitude; document.body.classList.toggle('near', a < 0.9); document.body.classList.toggle('mid', a < 1.9); document.body.classList.toggle('far', a > 0.85); });
world.renderer().setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
const fit = () => world.width(innerWidth).height(innerHeight);
addEventListener('resize', fit); fit();

// --- real-time night side: a shell over the globe that shows the night-lights
// texture only where the sun is below the horizon right now.
function subsolar(date = new Date()) {
  const rad = Math.PI / 180, d = date.getTime() / 86400000 + 2440587.5 - 2451545.0;
  const g = (357.529 + 0.98560028 * d) * rad;
  const L = (280.459 + 0.98564736 * d + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 3.6e-7 * d) * rad;
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)), dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (((280.46061837 + 360.98564736629 * d) % 360) + 360) % 360;
  let lng = ra / rad - gmst; lng = ((lng + 540) % 360) - 180;
  return {lat: dec / rad, lng};
}
const toVec = ({lat, lng}) => { // same convention three-globe uses for polar -> cartesian
  const phi = (90 - lat) * Math.PI / 180, th = (90 - lng) * Math.PI / 180;
  return [Math.sin(phi) * Math.cos(th), Math.cos(phi), Math.sin(phi) * Math.sin(th)];
};
function installNight(tries = 0) {
  let globeMesh = null;
  world.scene().traverse((o) => { if (o.material === mat && o.geometry && o.geometry.type === 'SphereGeometry' && !globeMesh) globeMesh = o; });
  if (!globeMesh) { if (tries < 40) setTimeout(() => installNight(tries + 1), 100); return; }
  const img = new Image();
  img.onload = () => {
    const tex = new mat.map.constructor(img);
    tex.colorSpace = mat.map.colorSpace; tex.anisotropy = 8; tex.needsUpdate = true;
    const m = new mat.constructor({map: tex, transparent: true, depthWrite: false, shininess: 0});
    const V3 = world.camera().position.constructor, sun = new V3();
    const setSun = () => { const v = toVec(subsolar()); sun.set(v[0], v[1], v[2]); };
    setSun(); setInterval(setSun, 60000);
    m.onBeforeCompile = (sh) => {
      sh.uniforms.sunDir = {value: sun};
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWN;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvWN = normalize(mat3(modelMatrix) * normal);');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform vec3 sunDir;\nvarying vec3 vWN;')
        .replace('#include <dithering_fragment>', `
          float sunDot = dot(normalize(vWN), normalize(sunDir));
          float night = 1.0 - smoothstep(-0.10, 0.12, sunDot);
          vec3 lights = diffuseColor.rgb * 1.9;
          gl_FragColor = vec4(lights * night + vec3(0.012, 0.022, 0.055) * night, night * 0.86);`);
    };
    m.customProgramCacheKey = () => 'sentinel-night';
    const shell = new globeMesh.constructor(new globeMesh.geometry.constructor(100, 90, 90), m);
    shell.rotation.copy(globeMesh.rotation); shell.scale.setScalar(1.0022); shell.renderOrder = 2; shell.raycast = () => {};
    globeMesh.parent.add(shell);
  };
  img.src = 'vendor/earth-night.jpg';
}
installNight();

// ---------- pins ----------
const tip = $('#tip');
addEventListener('mousemove', (e) => { tip.style.left = Math.min(e.clientX + 18, innerWidth - 280) + 'px'; tip.style.top = e.clientY + 18 + 'px'; });
function fly(lat, lng, altitude = 1.1) { ctl.autoRotate = false; world.pointOfView({lat, lng, altitude}, 1400); }

function pinEl(map, key, cls, lat, lng) {
  let o = map.get(key);
  if (!o) { o = {lat, lng, el: document.createElement('div')}; o.el.className = cls; map.set(key, o); }
  return o;
}
const WORST = ['DELAYED', 'AT_CHECKPOINT', 'IN_TRANSIT'];
function hubPinsData() {
  const out = [];
  for (const h of S.hubs) {
    const ships = S.shipments.filter((s) => s.warehouse_checkpoint === h.name && s.status !== 'DELIVERED');
    const worst = WORST.find((k) => ships.some((s) => s.status === k)) || 'IN_TRANSIT';
    const hit = S.events.some((e) => Math.abs(e.lat - h.lat) < .01 && Math.abs(e.lng - h.lng) < .01);
    const o = pinEl(hubPins, h.name, 'pin hub', h.lat, h.lng);
    o.el.className = `pin hub s-${worst.toLowerCase()}${hit ? ' hit' : ''} side-${SIDE[h.name] || 'r'}`;
    o.el.innerHTML = `<i></i><span class="lab">${esc(h.name)}${ships.length ? `<b>${ships.length}</b>` : ''}</span>`;
    o.el.onmouseenter = () => {
      tip.innerHTML = `<b>${esc(h.name)}</b><br>` + (ships.slice(0, 8).map((s) => `<span><i class="d" style="background:${STATUS[s.status]}"></i>${esc(s.shipment_id)} · ${esc(s.cargo || '')} · ${esc(s.mode || '')}</span>`).join('<br>') + (ships.length > 8 ? `<br><span>+${ships.length - 8} more</span>` : '') + '<br><span>Click to open the dashboard</span>');
      tip.style.opacity = 1;
      if (focusHub !== h.name) { focusHub = h.name; paintArcs(); }
    };
    o.el.onmouseleave = () => { tip.style.opacity = 0; if (focusHub === h.name) { focusHub = null; paintArcs(); } };
    o.el.onclick = () => openNode('hub', h.name);
    out.push(o);
  }
  return out;
}
function cityPinsData(drawn) {
  const active = new Set();
  for (const s of drawn) { active.add(s.origin); active.add(s.destination); }
  return S.cities.map((c) => {
    const o = pinEl(cityPins, c.name, 'pin city', c.lat, c.lng);
    o.el.className = 'pin city' + (active.has(c.name) ? ' active' : '');
    o.el.innerHTML = `<i></i><span class="lab">${esc(c.name.split(',')[0])}</span>`;
    o.el.onmouseenter = () => { tip.innerHTML = `<b>${esc(c.name)}</b><br><span>Click to open the city dashboard</span>`; tip.style.opacity = 1; };
    o.el.onmouseleave = () => { tip.style.opacity = 0; };
    o.el.onclick = () => openNode('city', c.name);
    return o;
  });
}
const gcDeg = (a, b) => {
  const r = Math.PI / 180, dl = (b[1] - a[1]) * r;
  return Math.acos(Math.min(1, Math.sin(a[0] * r) * Math.sin(b[0] * r) + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.cos(dl))) / r;
};
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)).join(',');

let pinSig = '';
function drawnShipments() {
  return S.shipments.filter((s) => s.from && s.to && s.status !== 'DELIVERED' &&
    (s.warehouse_checkpoint === focusHub || (layers[cls(s)] && layers[s.mode || 'road'])));
}
const ARC_COLOR = {delayed: 'rgba(255,92,77,.92)', rerouted: 'rgba(94,224,160,.92)', normal: 'rgba(156,196,255,.78)'};
function paintArcs() {
  const drawn = drawnShipments(), arcs = [], paths = [], missing = new Set();
  for (const s of drawn) {
    const focus = s.warehouse_checkpoint === focusHub, c = cls(s);
    const col = focus && c === 'normal' ? 'rgba(255,255,255,.95)' : ARC_COLOR[c];
    if (s.mode === 'air') {
      for (const [a, b] of [[s.from, s.hub], [s.hub, s.to]]) {
        const A = [a.lat, a.lng], B = [b.lat, b.lng];
        arcs.push({a: A, b: B, color: [col, col], alt: 0.025 + gcDeg(A, B) / 180 * 0.22, mode: 'air'});
      }
      continue;
    }
    const legs = ROUTES[s.route_key];
    if (!legs) { if (!asked.has(s.route_key)) missing.add(s.route_key); continue; }
    for (const leg of legs) if (leg.path && leg.path.length > 1) paths.push({pts: leg.path, color: col, mode: leg.mode});
  }
  world.arcsData(arcs);
  world.pathsData(paths);
  if (missing.size) fetchRoutes([...missing]);
  const cities = cityPinsData(drawn), sig = [...new Set(drawn.flatMap((d) => [d.origin, d.destination]))].sort().join('|');
  if (sig !== pinSig) { pinSig = sig; world.htmlElementsData([...cities, ...hubPinsData()]); }
}
async function fetchRoutes(keys) {
  keys.forEach((k) => asked.add(k));
  for (let i = 0; i < keys.length; i += 30) {
    try {
      Object.assign(ROUTES, await api('routes', {keys: keys.slice(i, i + 30)}));
    } catch { keys.slice(i, i + 30).forEach((k) => asked.delete(k)); }
  }
  paintArcs();
}
function paintLayers() {
  const live = S.shipments.filter((s) => s.status !== 'DELIVERED');
  const isStatus = (k) => k in ARC_COLOR;
  // status counts respect the enabled modes; mode counts respect the enabled statuses
  const count = (k) => live.filter((s) => (isStatus(k) ? cls(s) === k && layers[s.mode || 'road'] : (s.mode || 'road') === k && layers[cls(s)])).length;
  $('#layers').innerHTML = '<span class="lt">Routes</span>' + LAYER_DEFS.map((d) => {
    if (d === null) return '<span class="lsep"></span>';
    const n = count(d[0]);
    return `<button class="chipbtn ${layers[d[0]] ? 'on' : ''} ${n === 0 ? 'zero' : ''}" data-k="${d[0]}">${d[2] ? `<i style="background:${d[2]}"></i>` : ''}${d[1]}<em>${n}</em></button>`;
  }).join('');
}
function paintGlobe() {
  pinSig = ''; // hub pins re-render with fresh counts/status
  paintArcs();
  paintLayers();
  world.ringsData(S.events.map((e) => ({lat: e.lat, lng: e.lng, rgb: hex(SEV[e.severity] || SEV.LOW), r: e.severity === 'CRITICAL' ? 6 : 4.5, period: 1800}))
    .concat(flash.map((f) => ({...f, rgb: '94,224,160', r: 3, period: 1100}))));
}

// ---------- api ----------
async function api(path, body) {
  const r = await fetch('/api/' + path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return r.json();
}
async function act(path, body) {
  if (busy) return;
  setBusy(true);
  const before = S ? S.audit.length : 0, beforeInv = S ? S.investigations.length : 0;
  try {
    S = await api(path, body);
    const added = S.audit.slice(0, Math.max(0, S.audit.length - before));
    if (S.investigations.length > beforeInv) {
      fresh = true; tab = 'trace';
      const ev = S.investigations[0].event, geo = S.events.find((e) => e.event_id === ev.event_id);
      if (geo) fly(geo.lat, geo.lng);
      const byId = Object.fromEntries(S.shipments.map((s) => [s.shipment_id, s]));
      flash = added.map((a) => byId[a.shipment_id]).filter(Boolean).map((s) => ({lat: s.hub.lat, lng: s.hub.lng}));
      setTimeout(() => { flash = []; paintGlobe(); }, 7000);
    }
    if (path === 'reset') { flash = []; tab = 'incidents'; world.pointOfView(HOME, 1200); }
  } finally { setBusy(false); render(); if (dash.open) refreshDash(); }
}
function setBusy(b) {
  busy = b;
  document.querySelectorAll('.dock button').forEach((el) => (el.disabled = b));
  $('#btn-tick').textContent = b ? 'Agent working…' : 'Advance';
}

// ---------- render ----------
function render() {
  $('#tick').textContent = 'Tick ' + S.tick;
  $('#retrieval').textContent = 'RAG · ' + S.retrieval;
  const live = S.shipments.filter((s) => s.status !== 'DELIVERED');
  const delayed = live.filter((s) => s.status === 'DELAYED').length;
  $('#stats').innerHTML = [
    ['In network', live.length, ''], ['Delayed', delayed, delayed ? 'hot' : ''], ['Delivered', S.shipments.length - live.length, ''],
    ['Incidents', S.events.length, ''], ['Agent actions', S.audit.length, ''],
  ].map(([l, n, c]) => `<div class="stat ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

  if (!S.scenarios.some((e) => e.event_id === picked)) picked = S.scenarios.length ? S.scenarios[0].event_id : null;
  paintMenu();
  $('#btn-inject').disabled = busy || !S.scenarios.length;
  $('#engine').innerHTML = S.engines.map((e) => `<button data-e="${e}" class="${e === S.engine ? 'on' : ''}">${ENGINE_LABEL[e]}</button>`).join('');
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  paintGlobe();
  pane();
}

function pane() {
  const el = $('#pane');
  if (tab === 'incidents') el.innerHTML = incidents();
  else if (tab === 'trace') el.innerHTML = trace();
  else policyPane(el);
  fresh = false;
}

function incidents() {
  const cards = S.events.length ? [...S.events].reverse().map((e) => `
    <div class="inc" data-fly="${e.lat},${e.lng}">
      <div class="row"><span class="sev" style="background:${SEV[e.severity]};box-shadow:0 0 12px ${SEV[e.severity]}"></span><h4>${esc(e.type)}</h4>
        <span class="tag ${e.handled ? 'ok' : 'warn'}">${e.handled ? 'Resolved by agent' : 'Pending'}</span></div>
      <p>${esc(e.description)}</p><div class="ids">${esc(e.region || '')} · ${(e.affected_shipments || []).length} shipments · clears in ${e.ticks_left} ticks<br>${esc((e.affected_shipments || []).slice(0, 8).join(' · '))}${(e.affected_shipments || []).length > 8 ? ' …' : ''}</div></div>`).join('')
    : `<div class="empty"><b>All clear</b>No active disruptions on the network.<br>Advance the simulation or inject a scenario below.</div>`;
  const log = S.audit.length ? S.audit.slice(0, 10).map((a) => `<div class="log"><span class="tag ice">${esc(a.action)}</span><b>${esc(a.shipment_id)}</b><span>${esc(a.details)}</span></div>`).join('') : '';
  return `<div class="eyebrow">Active incidents</div>${cards}${log ? `<div class="eyebrow">Audit log</div>${log}` : ''}`;
}

function trace() {
  if (!S.investigations.length) return `<div class="empty"><b>No investigations yet</b>When a disruption appears the agent retrieves policies, reasons, and acts. Every step is recorded here.</div>`;
  return S.investigations.map((inv, idx) => {
    const risk = (inv.risk_level || '').toUpperCase();
    const steps = inv.steps.map((s, i) => {
      const search = s.tool === 'search_policy', rej = s.observation && s.observation.status === 'error';
      const cls = rej ? 'err' : (search || s.tool === 'get_shipment') ? '' : 'act';
      let ob = '';
      if (search) {
        const r = s.observation.results || [];
        ob = `<div class="ob">Retrieved ${r.length} policies · ${esc(s.observation.backend)}</div><div class="chips">${r.map((h) => `<span class="chip" title="${esc(h.text)}">${esc(h.rule_id)} · ${h.score.toFixed(2)}</span>`).join('')}</div>`;
      } else if (s.tool === 'finish') ob = `<div class="ob">${esc(s.args.summary || '')}</div>`;
      else ob = `<div class="ob">${rej ? 'Rejected: ' + esc(s.observation.message) : 'Applied'}</div>`;
      const delay = fresh && idx === 0 ? `style="animation-delay:${i * 110}ms"` : 'style="animation-duration:.01s"';
      return `<div class="st ${cls}" ${delay}><div class="th">${esc(s.thought)}</div><code class="call">${esc(s.tool)}(${esc(JSON.stringify(s.args).slice(0, 150))})</code>${ob}</div>`;
    }).join('');
    return `<div class="inv"><div class="hd"><h3>${esc(inv.event.type)}</h3>
      <span class="tag ${risk === 'LOW' ? 'ice' : risk === 'MEDIUM' ? 'warn' : 'red'}">${esc(inv.risk_level)}</span>
      <span class="tag">${esc(inv.brain)}</span><span class="tag ice">${inv.actions.length} actions</span></div>
      <div class="summary">${esc(inv.summary)}</div><div class="tl">${steps}</div></div>${idx < S.investigations.length - 1 ? '<div class="eyebrow">Earlier</div>' : ''}`;
  }).join('');
}

async function policyPane(el) {
  el.innerHTML = `<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="rgba(235,240,255,.5)" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    <input id="q" placeholder="Ask the knowledge base…" value="${esc(query)}" autocomplete="off"></div><div id="res"></div>`;
  const input = $('#q'), res = $('#res');
  const run = async () => {
    query = input.value;
    const d = query.trim() ? await api('search', {query}) : await api('policies');
    const rows = query.trim() ? d.results : d.rules.map((r) => ({rule_id: r.id, text: r.text, score: null}));
    res.innerHTML = `<div class="eyebrow">${query.trim() ? `Top matches · ${esc(d.backend)}` : 'All policies'}</div>` +
      rows.map((h) => `<div class="rule"><span class="id">${esc(h.rule_id)}</span><span>${esc(h.text)}</span>${h.score == null ? '' : `<span class="sc">${h.score.toFixed(2)}</span>`}</div>`).join('');
  };
  let t; input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 220); });
  run();
}


// ---------- location dashboard ----------
const dash = {open: false, kind: null, name: null, data: null, sort: {key: 'current_eta', dir: 1}, status: 'all', mode: 'all', q: '', expanded: new Set()};
const STATUS_LABEL = {IN_TRANSIT: 'In transit', AT_CHECKPOINT: 'At checkpoint', DELAYED: 'Delayed', DELIVERED: 'Delivered'};
const fmtDT = (iso) => new Date(iso).toLocaleString([], {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false});
function rel(iso, clock) {
  const h = (new Date(iso) - new Date(clock)) / 36e5, a = Math.abs(h);
  const t = a >= 48 ? `${Math.floor(a / 24)}d ${Math.round(a % 24)}h` : a >= 1 ? `${Math.floor(a)}h ${Math.round((a % 1) * 60)}m` : `${Math.round(a * 60)}m`;
  return h >= 0 ? `in ${t}` : `${t} ago`;
}
const modeBadge = (m) => `<span class="mb m-${m}">${m.toUpperCase()}</span>`;
const statusPill = (r) => `<span class="sp"><i style="background:${r.mitigated && r.status !== 'DELAYED' ? '#5EE0A0' : STATUS[r.status]}"></i>${r.mitigated && r.status !== 'DELAYED' ? 'Rerouted' : STATUS_LABEL[r.status]}</span>`;
const short = (n) => String(n).split(',')[0];

async function openNode(kind, name, doFly = true) {
  tip.style.opacity = 0;
  const same = dash.open && dash.name === name && dash.kind === kind;
  const res = await api('node', {kind, name});
  if (res.error) return;
  if (!same) Object.assign(dash, {sort: {key: 'current_eta', dir: 1}, status: 'all', mode: 'all', q: '', expanded: new Set()});
  Object.assign(dash, {open: true, kind, name, data: res});
  if (doFly) { ctl.autoRotate = false; world.pointOfView({lat: res.node.lat, lng: res.node.lng, altitude: 0.9}, 1200); }
  $('#dash').hidden = false;
  renderDash();
}
const refreshDash = () => dash.open && openNode(dash.kind, dash.name, false);
function closeDash() { dash.open = false; $('#dash').hidden = true; }

function renderDash() {
  const d = dash.data, n = d.node, k = d.kpis;
  $('#dhead').innerHTML = `<div class="t"><div class="kind">${esc(n.kind === 'hub' ? n.type + ' hub' : 'City')} · ${n.lat.toFixed(2)}°, ${n.lng.toFixed(2)}°</div>
      <h2>${esc(n.name)}</h2>
      <div class="sub">${k.total} shipments touch this ${n.kind === 'hub' ? 'hub' : 'city'} · simulated time ${esc(fmtDT(d.clock))}</div>
      ${d.nearby.length ? `<div class="near">${d.nearby.slice(0, 8).map((x) => `<button class="nchip" data-k="${x.kind}" data-n="${esc(x.name)}">${esc(x.kind === 'hub' ? x.name : short(x.name) + ' · city')}</button>`).join('')}</div>` : ''}</div>
      <button class="xbtn" id="dash-x" aria-label="Close">×</button>`;
  $('#dkpis').innerHTML = [
    ['Shipments', k.total, ''], ['In transit', k.in_transit + k.at_checkpoint, ''], ['Delayed', k.delayed, k.delayed ? 'hot' : ''],
    ['Rerouted by agent', k.rerouted, k.rerouted ? 'good' : ''], ['Delivered', k.delivered, ''],
    ['On-time', k.on_time_pct + '%', k.on_time_pct >= 90 ? 'good' : 'hot'], ['Avg delay', k.avg_delay_h + ' h', ''], ['Freight km', k.km.toLocaleString(), ''],
  ].map(([l, v, c]) => `<div class="dk ${c}"><div class="n">${v}</div><div class="l">${l}</div></div>`).join('');
  $('#dinc').innerHTML = d.incidents.length ? `<div class="eyebrow">Incidents affecting this ${n.kind}</div><div class="dinc">` + d.incidents.map((e) => `
      <div class="inc"><div class="row"><span class="sev" style="background:${SEV[e.severity]};box-shadow:0 0 12px ${SEV[e.severity]}"></span><h4>${esc(e.type)}</h4>
        <span class="tag ${e.active ? 'warn' : ''}">${e.active ? `Active · clears in ${e.ticks_left}` : 'Cleared'}</span></div>
      <p>${esc(e.description)}</p><div class="ids">${esc(e.location || e.region || '')} · ${e.affected_here} shipment${e.affected_here === 1 ? '' : 's'} here</div></div>`).join('') + '</div>'
    : '<div class="eyebrow">Incidents</div><div class="nodata">No active or recent incidents affecting this location.</div>';
  $('#dtools').innerHTML = `<label class="dsearch"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="dq" placeholder="Search ID, cargo, carrier, city…" value="${esc(dash.q)}" autocomplete="off"></label>
    <div class="grp" id="dstatus">${[['all', 'All'], ['delayed', 'Delayed'], ['rerouted', 'Rerouted'], ['transit', 'In transit'], ['delivered', 'Delivered']].map(([v, l]) => `<button data-v="${v}" class="${dash.status === v ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div class="grp" id="dmode">${['all', 'sea', 'air', 'rail', 'road'].map((v) => `<button data-v="${v}" class="${dash.mode === v ? 'on' : ''}">${v === 'all' ? 'All modes' : v[0].toUpperCase() + v.slice(1)}</button>`).join('')}</div>
    <span class="cnt" id="dcnt"></span>`;
  renderTable();
}

function visibleRows() {
  const q = dash.q.trim().toLowerCase();
  let rows = dash.data.shipments.filter((r) => {
    if (dash.status === 'delayed' && r.status !== 'DELAYED') return false;
    if (dash.status === 'rerouted' && !r.mitigated) return false;
    if (dash.status === 'transit' && !['IN_TRANSIT', 'AT_CHECKPOINT'].includes(r.status)) return false;
    if (dash.status === 'delivered' && r.status !== 'DELIVERED') return false;
    if (dash.mode !== 'all' && r.mode !== dash.mode) return false;
    return !q || `${r.shipment_id} ${r.cargo} ${r.carrier} ${r.origin} ${r.destination} ${r.warehouse_checkpoint} ${r.mode}`.toLowerCase().includes(q);
  });
  const {key, dir} = dash.sort;
  rows = [...rows].sort((a, b) => {
    const x = key === 'route' ? a.origin + a.destination : a[key], y = key === 'route' ? b.origin + b.destination : b[key];
    return (x > y ? 1 : x < y ? -1 : 0) * dir;
  });
  return rows;
}

function renderTable() {
  const rows = visibleRows(), clock = dash.data.clock;
  const cols = [['shipment_id', 'Shipment'], ['cargo', 'Cargo'], ['route', 'Route'], ['mode', 'Mode'], ['carrier', 'Carrier'], ['status', 'Status'],
    ['shipped_at', 'Shipped'], ['current_eta', 'ETA'], ['delay_h', 'vs plan'], ['progress', 'Progress'], ['incident_ids', 'Incident']];
  const head = cols.map(([k, l]) => `<th data-k="${k}" class="${dash.sort.key === k ? 'sorted' : ''}">${l}${dash.sort.key === k ? (dash.sort.dir > 0 ? ' ↑' : ' ↓') : ''}</th>`).join('');
  const body = rows.map((r) => {
    const open = dash.expanded.has(r.shipment_id), late = r.delay_h > 0;
    const inc = r.incident_ids.length ? `<span class="tag red">${esc(r.incident_ids.length > 1 ? r.incident_ids.length + ' active' : (dash.data.incidents.find((e) => e.event_id === r.incident_ids[0]) || {type: 'Active'}).type)}</span>` : r.history.length ? '<span class="tag">History</span>' : '<span class="delta ok">—</span>';
    return `<tr class="row ${open ? 'open' : ''}" data-id="${r.shipment_id}"><td class="id">${esc(r.shipment_id)}</td><td>${esc(r.cargo)}</td>
      <td class="route">${esc(short(r.origin))} → ${esc(short(r.destination))}<small>via ${esc(r.warehouse_checkpoint)}</small></td><td>${modeBadge(r.mode)}</td>
      <td class="m">${esc(r.carrier)}</td><td>${statusPill(r)}</td><td class="m">${esc(fmtDT(r.shipped_at))}</td>
      <td>${esc(fmtDT(r.current_eta))}<small style="display:block;color:var(--fg3);font-size:.68rem">${r.status === 'DELIVERED' ? 'delivered' : esc(rel(r.current_eta, clock))}</small></td>
      <td><span class="delta ${late ? 'late' : 'ok'}">${late ? '+' + r.delay_h + ' h' : 'on plan'}</span></td>
      <td><span class="pbar ${late ? 'late' : ''}"><b style="width:${Math.round(r.progress * 100)}%"></b></span> <span class="delta ok">${Math.round(r.progress * 100)}%</span></td><td>${inc}</td></tr>${open ? `<tr class="xrow"><td colspan="11">${detail(r, clock)}</td></tr>` : ''}`;
  }).join('');
  $('#dtable').innerHTML = rows.length ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>` : '<div class="empty"><b>No shipments match</b>Try a different filter or search.</div>';
  $('#dcnt').textContent = `${rows.length} of ${dash.data.shipments.length}`;
}

function detail(r, clock) {
  const stops = [r.legs[0].from, ...r.legs.map((l) => l.to)], total = r.km || 1, pos = r.progress * total;
  let acc = 0, nowLeg = -1;
  r.legs.forEach((l, i) => { if (nowLeg < 0 && acc + l.km >= pos) nowLeg = i; acc += l.km; });
  let cum = 0;
  const route = stops.map((st, i) => {
    const done = i === 0 || cum <= pos + 1;
    const html = `<div class="stop ${done ? 'done' : ''}">${esc(st)}<small>${i === 0 ? 'origin' : i === stops.length - 1 ? 'destination' : 'checkpoint'}</small></div>`;
    const leg = r.legs[i];
    const legHtml = leg ? `<div class="legrow">${modeBadge(leg.mode)}<span>${leg.km.toLocaleString()} km</span>${i === nowLeg && r.status !== 'DELIVERED' ? `<span class="now">Now · ${Math.round(r.progress * 100)}% of journey</span>` : ''}</div>` : '';
    cum += leg ? leg.km : 0;
    return html + legHtml;
  }).join('');
  const hist = r.history.length ? r.history.map((h) => `<div class="hi"><b><span class="sev" style="background:${SEV[h.severity]}"></span>${esc(h.event)}<span class="tag ${h.active ? 'warn' : ''}" style="margin-left:auto">${h.active ? 'Active' : 'Cleared'}</span></b>
      <div>${h.actions.length ? h.actions.map((a) => `<span class="tag ice">${esc(a.action)}</span> ${esc(a.details)}`).join('<br>') : 'Monitored; no action needed on this shipment.'}</div></div>`).join('')
    : '<div class="nodata">No incidents recorded for this shipment.</div>';
  const remaining = r.status === 'DELIVERED' ? 'Delivered' : rel(r.current_eta, clock);
  return `<div class="xd"><div><h5>Route taken · ${r.km.toLocaleString()} km</h5><div class="stops">${route}</div></div>
    <div><h5>Timing</h5><div class="tgrid"><span>Shipped</span><span>${esc(fmtDT(r.shipped_at))}</span><span>Planned ETA</span><span>${esc(fmtDT(r.planned_eta))}</span>
      <span>Current ETA</span><span>${esc(fmtDT(r.current_eta))}</span><span>Remaining</span><span>${esc(remaining)}</span><span>Delay vs plan</span><span>${r.delay_h > 0 ? '+' + r.delay_h + ' h' : 'none'}</span>
      <span>SLA</span><span>${r.sla_hours} h</span><span>Priority</span><span>${r.priority ? 'P' + r.priority : 'Standard'}</span><span>Carrier</span><span>${esc(r.carrier)}</span></div></div>
    <div><h5>Incidents &amp; agent actions</h5><div class="hist">${hist}</div></div></div>`;
}

$('#dash').addEventListener('click', (e) => {
  if (e.target.id === 'scrim' || e.target.closest('#dash-x')) return closeDash();
  const chip = e.target.closest('.nchip'); if (chip) return openNode(chip.dataset.k, chip.dataset.n);
  const th = e.target.closest('th[data-k]');
  if (th) { const k = th.dataset.k; dash.sort = {key: k, dir: dash.sort.key === k ? -dash.sort.dir : 1}; return renderTable(); }
  const gs = e.target.closest('#dstatus button'); if (gs) { dash.status = gs.dataset.v; return renderDash(); }
  const gm = e.target.closest('#dmode button'); if (gm) { dash.mode = gm.dataset.v; return renderDash(); }
  const row = e.target.closest('tr.row');
  if (row) {
    const id = row.dataset.id, opening = !dash.expanded.has(id);
    opening ? dash.expanded.add(id) : dash.expanded.delete(id); renderTable();
    if (opening) document.querySelector(`tr.row[data-id="${id}"]`)?.scrollIntoView({block: 'start', behavior: 'smooth'});
  }
});
$('#dash').addEventListener('input', (e) => { if (e.target.id === 'dq') { dash.q = e.target.value; renderTable(); } });
addEventListener('keydown', (e) => { if (e.key === 'Escape' && dash.open) closeDash(); });

// ---------- events ----------
$('#layers').addEventListener('click', (e) => {
  const b = e.target.closest('.chipbtn'); if (!b) return;
  layers[b.dataset.k] = !layers[b.dataset.k];
  try { localStorage.setItem(STORE, JSON.stringify(layers)); } catch {}
  paintLayers(); paintArcs();
});
$('#tabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { tab = b.dataset.tab; render(); } });
$('#pane').addEventListener('click', (e) => { const c = e.target.closest('[data-fly]'); if (c) { const [la, ln] = c.dataset.fly.split(',').map(Number); fly(la, ln); } });
$('#btn-tick').onclick = () => act('tick', {});
$('#btn-inject').onclick = () => { if (picked) act('inject', {event_id: picked}); };

// ---------- scenario picker (compact, searchable) ----------
function paintMenu() {
  const cur = S.scenarios.find((e) => e.event_id === picked);
  $('#pick-label').textContent = cur ? `${cur.type} · ${cur.location}` : 'No scenarios left';
  const q = $('#msearch').value.trim().toLowerCase();
  const rows = S.scenarios.filter((e) => `${e.type} ${e.region} ${e.location} ${e.severity}`.toLowerCase().includes(q));
  $('#mlist').innerHTML = rows.length ? rows.map((e) => `<button class="mi ${e.event_id === picked ? 'on' : ''}" data-id="${e.event_id}">
      <span class="sev" style="background:${SEV[e.severity]}"></span><span class="mt">${esc(e.type)}</span><span class="mr">${esc(e.location)}</span></button>`).join('')
    : '<div class="mnone">No matches</div>';
}
const menu = $('#menu');
const closeMenu = () => { menu.hidden = true; };
$('#pick-btn').onclick = (e) => {
  e.stopPropagation();
  menu.hidden = !menu.hidden;
  if (!menu.hidden) { $('#msearch').value = ''; paintMenu(); $('#msearch').focus(); }
};
$('#msearch').addEventListener('input', paintMenu);
$('#msearch').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeMenu();
  if (e.key === 'Enter') { const f = $('#mlist .mi'); if (f) f.click(); }
});
$('#mlist').addEventListener('click', (e) => {
  const b = e.target.closest('.mi'); if (!b) return;
  picked = b.dataset.id; closeMenu(); paintMenu();
});
menu.addEventListener('click', (e) => e.stopPropagation());
document.addEventListener('click', closeMenu);
let auto = null;
$('#btn-auto').onclick = () => {
  if (auto) { clearInterval(auto); auto = null; } else { auto = setInterval(() => { if (!busy) act('tick', {}); }, 6000); if (!busy) act('tick', {}); }
  $('#btn-auto').classList.toggle('on', !!auto);
  $('#btn-auto').textContent = auto ? 'Auto · on' : 'Auto';
};
$('#btn-reset').onclick = () => act('reset', {});
$('#engine').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) act('engine', {engine: b.dataset.e}); });

api('state').then((s) => { S = s; render(); });
})();
