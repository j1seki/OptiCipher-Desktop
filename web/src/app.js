import { encryptImage, decryptImage, verifyImage, entropyReport, adjacentCorrelation, npcr, uaci, histogram } from './core.js';
import { encodePNG, decodePNG } from './png.js';

const $ = id => document.getElementById(id);
const yieldToUI = () => new Promise(r => setTimeout(r, 0));

document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
  $('tab-' + b.dataset.tab).classList.remove('hidden');
}));

function wireDrop(dropId, inputId) {
  const drop = $(dropId), input = $(inputId);
  input.addEventListener('change', () => input._files = [...input.files]);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); input._files = [...e.dataTransfer.files]; });
  return () => input._files || [];
}
const getEncryptFiles = wireDrop('drop-encrypt', 'files-encrypt');
const getDecryptFiles = wireDrop('drop-decrypt', 'files-decrypt');
const getVerifyFiles = wireDrop('drop-verify', 'files-verify');
const getAnalyzeFiles = wireDrop('drop-analyze', 'files-analyze');

async function loadImage(file) {
  const buf = new Uint8Array(await file.arrayBuffer());
  if (file.type === 'image/png' || file.name.toLowerCase().endsWith('.png')) {
    try { return { ...decodePNG(buf), name: file.name }; } catch (e) { /* fall through to canvas */ }
  }
  // Canvas fallback for JPEG/WebP/interlaced etc. (note: premultiplies alpha —
  // fine for opaque photos; exact PNG path above is used when possible).
  const blob = new Blob([buf], { type: file.type || 'image/png' });
  const bmp = await createImageBitmap(blob);
  const c = document.createElement('canvas'); c.width = bmp.width; c.height = bmp.height;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0);
  const d = ctx.getImageData(0, 0, bmp.width, bmp.height);
  // Canvas is RGBA; if every alpha is 255, drop to RGB like Pillow-on-opaque.
  let opaque = true; for (let i = 3; i < d.data.length; i += 4) if (d.data[i] !== 255) { opaque = false; break; }
  if (opaque) {
    const px = new Uint8Array(bmp.width * bmp.height * 3);
    for (let i = 0, j = 0; i < d.data.length; i += 4, j += 3) { px[j] = d.data[i]; px[j + 1] = d.data[i + 1]; px[j + 2] = d.data[i + 2]; }
    return { pixels: px, width: bmp.width, height: bmp.height, channels: 3, name: file.name };
  }
  return { pixels: new Uint8Array(d.data.buffer, d.data.byteOffset, d.data.byteLength), width: bmp.width, height: bmp.height, channels: 4, name: file.name };
}

function download(name, pngBytes) {
  const url = URL.createObjectURL(new Blob([pngBytes], { type: 'image/png' }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.textContent = '⬇ ' + name; return a;
}
function preview(data, width, height, channels) {
  const png = encodePNG(data, width, height, channels);
  const img = document.createElement('img');
  img.src = URL.createObjectURL(new Blob([png], { type: 'image/png' }));
  return img;
}
function stem(name) { return name.replace(/\.[^.]+$/, ''); }
function setBusy(btn, busy, label) { btn.disabled = busy; btn.textContent = busy ? 'Working…' : label; }

$('iter-encrypt').addEventListener('input', e => $('iter-out').textContent = e.target.value);

$('run-encrypt').addEventListener('click', async () => {
  const btn = $('run-encrypt'); setBusy(btn, true, 'Encrypt');
  const out = $('out-encrypt'); out.innerHTML = '';
  try {
    const pass = $('pass-encrypt').value;
    if (!pass || pass !== $('pass2-encrypt').value) throw new Error('Passphrases do not match or are empty.');
    const iter = Number($('iter-encrypt').value);
    for (const f of getEncryptFiles()) {
      try {
        await yieldToUI();
        const img = await loadImage(f);
        const enc = await encryptImage(img.pixels, img.width, img.height, img.channels, pass, iter);
        const png = encodePNG(enc.data, enc.width, enc.height, enc.channels);
        const item = document.createElement('div'); item.className = 'item';
        item.append(document.createTextNode(`${f.name} → `), download(stem(f.name) + '_encrypted.png', png), preview(enc.data, enc.width, enc.height, enc.channels));
        out.append(item);
      } catch (e) { const d = document.createElement('div'); d.className = 'item err'; d.textContent = `${f.name}: ${e.message}`; out.append(d); }
    }
  } catch (e) { out.innerHTML = `<div class="item err">${e.message}</div>`; }
  setBusy(btn, false, 'Encrypt');
});

$('run-decrypt').addEventListener('click', async () => {
  const btn = $('run-decrypt'); setBusy(btn, true, 'Decrypt');
  const out = $('out-decrypt'); out.innerHTML = '';
  try {
    const pass = $('pass-decrypt').value;
    for (const f of getDecryptFiles()) {
      try {
        await yieldToUI();
        const img = await loadImage(f);
        const dec = await decryptImage(img.pixels, img.width, img.height, img.channels, pass);
        const png = encodePNG(dec.data, dec.width, dec.height, dec.channels);
        const item = document.createElement('div'); item.className = 'item';
        item.append(document.createTextNode(`${f.name} → `), download(stem(f.name) + '_decrypted.png', png), preview(dec.data, dec.width, dec.height, dec.channels));
        out.append(item);
      } catch (e) { const d = document.createElement('div'); d.className = 'item err'; d.textContent = `${f.name}: ${e.message}`; out.append(d); }
    }
  } catch (e) { out.innerHTML = `<div class="item err">${e.message}</div>`; }
  setBusy(btn, false, 'Decrypt');
});

$('run-verify').addEventListener('click', async () => {
  const btn = $('run-verify'); setBusy(btn, true, 'Verify integrity');
  const out = $('out-verify'); out.innerHTML = '';
  try {
    const pass = $('pass-verify').value || null;
    for (const f of getVerifyFiles()) {
      try {
        const img = await loadImage(f);
        const v = await verifyImage(img.pixels, img.width, img.height, img.channels, pass);
        const d = document.createElement('div'); d.className = 'item ' + (v.status === 'verified' ? 'ok' : '');
        d.textContent = `${f.name}: [${v.status}] ${v.message}` + (v.iterations ? ` (v${v.version}, ${v.width}×${v.height}, ${v.channels}ch, strip ${v.stripRows}, ${v.iterations} iters)` : '');
        out.append(d);
      } catch (e) { const d = document.createElement('div'); d.className = 'item err'; d.textContent = `${f.name}: ${e.message}`; out.append(d); }
    }
  } catch (e) { out.innerHTML = `<div class="item err">${e.message}</div>`; }
  setBusy(btn, false, 'Verify integrity');
});

$('run-analyze').addEventListener('click', async () => {
  const btn = $('run-analyze'); setBusy(btn, true, 'Run analysis');
  const out = $('out-analyze'); out.innerHTML = '';
  try {
    const imgs = [];
    for (const f of getAnalyzeFiles()) imgs.push(await loadImage(f));
    if (!imgs.length) throw new Error('Add at least one image.');
    const a = imgs[0];
    const ent = entropyReport(a.pixels, a.width, a.height, a.channels);
    const d = document.createElement('div'); d.className = 'item';
    let txt = `${a.name}: entropy mean ${ent.mean.toFixed(4)} bits/byte`;
    for (let c = 0; c < a.channels; c++) {
      const corr = adjacentCorrelation(a.pixels, a.width, a.height, a.channels, c);
      txt += ` · ch${c} corr H ${corr.horizontal.toFixed(3)} V ${corr.vertical.toFixed(3)} D ${corr.diagonal.toFixed(3)}`;
    }
    d.textContent = txt; out.append(d);
    if (imgs.length >= 2) {
      const b = imgs[1];
      if (a.width !== b.width || a.height !== b.height || a.channels !== b.channels) throw new Error('NPCR/UACI needs two images of identical size.');
      const d2 = document.createElement('div'); d2.className = 'item';
      d2.textContent = `NPCR ${npcr(a.pixels, b.pixels).toFixed(2)}% · UACI ${uaci(a.pixels, b.pixels).toFixed(2)}%`;
      out.append(d2);
    }
    // Histogram of channel 0
    const h = histogram(a.pixels, a.width, a.height, a.channels, 0);
    const cv = $('hist'), ctx = cv.getContext('2d'); ctx.clearRect(0, 0, cv.width, cv.height);
    const max = Math.max(...h);
    ctx.fillStyle = '#4da3ff';
    for (let i = 0; i < 256; i++) { const bh = (h[i] / max) * (cv.height - 10); ctx.fillRect(i * (cv.width / 256), cv.height - bh, cv.width / 256, bh); }
  } catch (e) { out.innerHTML = `<div class="item err">${e.message}</div>`; }
  setBusy(btn, false, 'Run analysis');
});
