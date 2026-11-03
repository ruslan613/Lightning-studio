// 3D-просмотр из cad3d/geometry.json (мм; z вниз от потолка). three.js локально (vendor/).
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

let current = null;

export function disposeViewer() {
  if (!current) return;
  cancelAnimationFrame(current.raf);
  current.ro.disconnect();
  current.renderer.dispose();
  current.renderer.domElement.remove();
  current = null;
}

function part(geom, name) { return (geom.parts || []).find((p) => p.name === name || p.type === name); }

export function mountViewer(el, geom) {
  disposeViewer();
  const W = el.clientWidth || 800, H = el.clientHeight || 500;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  } catch (e) {
    el.insertAdjacentHTML('beforeend', `<div class="viewer-hud">WebGL недоступен: ${e.message}</div>`);
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, W / H, 1, 20000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  scene.add(new THREE.HemisphereLight(0xfff2d8, 0x221a10, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(1500, 1800, 1200); scene.add(key);
  const rim = new THREE.DirectionalLight(0xffd9a0, 1.0); rim.position.set(-1400, 600, -1200); scene.add(rim);

  const brass = new THREE.MeshStandardMaterial({ color: 0xc9a45c, metalness: 0.9, roughness: 0.28 });
  const crystal = new THREE.MeshPhysicalMaterial({ color: 0xeaf4ff, metalness: 0, roughness: 0.05, transmission: 0.6, transparent: true, opacity: 0.75, ior: 1.5, thickness: 8, clearcoat: 1 });
  const matFor = (m) => (/crystal|glass/.test(m || '') ? crystal : brass);
  const root = new THREE.Group(); scene.add(root);
  // geometry: (x, y, z_down) → three: (x, z, y)
  const P = (x, y, z) => new THREE.Vector3(x, z, y);

  const dims = geom.dimensions_mm || {};
  const canopy = part(geom, 'ceiling_canopy') || part(geom, 'disk');
  const rod = part(geom, 'suspension_rod') || part(geom, 'cylinder');
  const ring = part(geom, 'main_ring') || part(geom, 'torus_ring');
  const pend = part(geom, 'crystal_pendant') || part(geom, 'prism');
  const sock = part(geom, 'led_holder') || part(geom, 'socket');
  const leds = (geom.led_layout && geom.led_layout.positions) || [];
  const counts = {};

  let y = 0;
  if (canopy) {
    const d = canopy.dims_mm.diameter || 180, h = canopy.dims_mm.height || 25;
    const m = new THREE.Mesh(new THREE.CylinderGeometry(d / 2, d / 2 * 0.85, h, 64), matFor(canopy.material));
    m.position.y = -h / 2; root.add(m); y = -h; counts['Чаша (canopy)'] = 1;
  }
  const ringZ = leds.length ? leds[0].z : -((rod && rod.dims_mm.length) || 300);
  if (rod) {
    const d = rod.dims_mm.diameter || 16, L = Math.abs(ringZ) - Math.abs(y);
    const m = new THREE.Mesh(new THREE.CylinderGeometry(d / 2, d / 2, L, 24), matFor(rod.material));
    m.position.y = y - L / 2; root.add(m); counts['Штанга'] = 1;
  }
  let ringR = 0;
  if (ring) {
    const D = ring.dims_mm.diameter || dims.diameter || 1000, prof = ring.dims_mm.profile || 40;
    ringR = D / 2 - prof;
    const tor = new THREE.Mesh(new THREE.TorusGeometry(ringR, prof / 2, 32, 160), matFor(ring.material));
    tor.rotation.x = Math.PI / 2; tor.position.y = ringZ; root.add(tor);
    const inner = new THREE.Mesh(new THREE.TorusGeometry(ringR * 0.45, prof / 3.5, 24, 100), matFor(ring.material));
    inner.rotation.x = Math.PI / 2; inner.position.y = ringZ + prof * 1.5; root.add(inner);
    // спицы
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      const s = new THREE.Mesh(new THREE.CylinderGeometry(5, 5, ringR, 10), matFor(ring.material));
      s.rotation.z = Math.PI / 2; s.rotation.y = -a;
      s.position.set(Math.cos(a) * ringR / 2, ringZ, Math.sin(a) * ringR / 2); root.add(s);
    }
    counts['Кольцо (torus)'] = 1;
  }
  // LED-точки + патроны
  const ledMat = new THREE.MeshBasicMaterial({ color: 0xffd58a });
  const ledGeo = new THREE.SphereGeometry(14, 16, 12);
  const sockH = (sock && sock.dims_mm.height) || 40, sockD = (sock && sock.dims_mm.diameter) || 30;
  const sockGeo = new THREE.CylinderGeometry(sockD / 2, sockD / 2.6, sockH, 20);
  leds.forEach((p, i) => {
    const v = P(p.x, p.y, p.z);
    const s = new THREE.Mesh(sockGeo, brass); s.position.copy(v).add(new THREE.Vector3(0, sockH / 2, 0)); root.add(s);
    const l = new THREE.Mesh(ledGeo, ledMat); l.position.copy(v).add(new THREE.Vector3(0, sockH + 12, 0)); root.add(l);
    if (i % 4 === 0) { const pl = new THREE.PointLight(0xffc878, 0.6, 900, 1.5); pl.position.copy(l.position); root.add(pl); }
  });
  if (leds.length) counts['LED-точки'] = leds.length;
  // хрустальные подвески
  if (pend) {
    const n = pend.qty || 24, L = pend.dims_mm.length || 200, w = pend.dims_mm.width || 18;
    const pg = new THREE.OctahedronGeometry(w * 0.9, 0); pg.scale(1, L / (w * 1.8) * 0.55, 1);
    const R = ringR || (dims.diameter || 800) / 2.2;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const tier = i % 2; const r = R * (tier ? 0.92 : 1.0); const drop = L * (tier ? 0.9 : 0.55);
      const chain = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, drop, 6), brass);
      chain.position.set(Math.cos(a) * r, ringZ - drop / 2, Math.sin(a) * r); root.add(chain);
      const c = new THREE.Mesh(pg, crystal); c.position.set(Math.cos(a) * r, ringZ - drop - L * 0.25, Math.sin(a) * r); c.rotation.y = a; root.add(c);
    }
    // центральный каскад
    for (let k = 0; k < 7; k++) {
      const c = new THREE.Mesh(pg, crystal); c.position.set(0, ringZ - 40 - k * L * 0.4, 0); c.scale.setScalar(1.3 - k * 0.1); root.add(c);
    }
    counts['Хрустальные подвески'] = n;
  }
  if (!canopy && !ring && !leds.length) {
    const bb = geom.bbox_mm || { x: 600, y: 50, z: 40 };
    const m = new THREE.Mesh(new THREE.BoxGeometry(bb.x || 600, bb.z || 40, bb.y || 50), brass); root.add(m);
    counts['Корпус'] = 1;
  }
  // пол-сетка
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
  const grid = new THREE.GridHelper(Math.max(size.x, size.z) * 2, 24, 0x5a4a2a, 0x2a2418);
  grid.position.y = box.min.y - 60; scene.add(grid);
  const maxDim = Math.max(size.x, size.y, size.z);
  camera.position.set(center.x + maxDim * 1.1, center.y + maxDim * 0.45, center.z + maxDim * 1.25);
  controls.target.copy(center); controls.update();
  controls.autoRotate = true; controls.autoRotateSpeed = 0.8;
  renderer.domElement.addEventListener('pointerdown', () => { controls.autoRotate = false; });

  const legend = document.createElement('div'); legend.className = 'legend';
  legend.innerHTML = Object.entries(counts).map(([k, v]) => `${k}: <b>${v}</b>`).join('<br>');
  el.appendChild(legend);

  const ro = new ResizeObserver(() => {
    const w = el.clientWidth, h = el.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  });
  ro.observe(el);
  const loop = () => { current.raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  current = { renderer, ro, raf: 0 };
  loop();
}
