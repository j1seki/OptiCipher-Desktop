import { encryptImage, decryptImage, verifyImage, entropyReport, adjacentCorrelation, npcr, uaci, histogram } from './core.js';
import { encodePNG } from './png.js';
import { loadImage } from './image-formats.js';

const $ = id => document.getElementById(id);
const yieldToUI = () => new Promise(r => setTimeout(r, 0));

const tabs = document.querySelectorAll('.tabs button');
tabs.forEach(b => b.addEventListener('click', () => {
  tabs.forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
  $('tab-' + b.dataset.tab).classList.remove('hidden');
}));

function wireDrop(dropId, inputId, maxFiles = Infinity) {
  const drop = $(dropId), input = $(inputId);
  const selection = document.createElement('span');
  selection.className = 'selection';
  selection.setAttribute('aria-live', 'polite');
  selection.textContent = 'No images selected';
  drop.append(selection);
  let files = [];
  let tooMany = false;
  const select = source => {
    files = [...source];
    tooMany = files.length > maxFiles;
    selection.textContent = tooMany ? `Choose up to ${maxFiles} images.`
      : files.map(file => file.name).join(', ') || 'No images selected';
  };
  input.addEventListener('change', () => {
    select(input.files);
    input.value = '';
  });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('over');
    select(e.dataTransfer.files);
  });
  return () => {
    if (tooMany) throw new Error(`Choose up to ${maxFiles} images.`);
    if (!files.length) throw new Error('Add at least one image.');
    return files;
  };
}
const getEncryptFiles = wireDrop('drop-encrypt', 'files-encrypt');
const getDecryptFiles = wireDrop('drop-decrypt', 'files-decrypt');
const getVerifyFiles = wireDrop('drop-verify', 'files-verify');
const getAnalyzeFiles = wireDrop('drop-analyze', 'files-analyze', 2);

function addOutput(out, inputName, name, { data, width, height, channels }) {
  const url = URL.createObjectURL(new Blob([encodePNG(data, width, height, channels)], { type: 'image/png' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.textContent = name;
  const img = document.createElement('img');
  img.src = url;
  img.alt = `Preview of ${name}`;
  const item = addMessage(out, `${inputName} → `);
  item.append(link, img);
}
function addMessage(out, message, variant = '') {
  const item = document.createElement('div');
  item.className = `item ${variant}`;
  item.textContent = message;
  out.append(item);
  return item;
}

function wireRun(mode, run) {
  const button = $('run-' + mode);
  const out = $('out-' + mode);
  const label = button.textContent;
  button.addEventListener('click', async () => {
    button.disabled = true;
    button.textContent = 'Working…';
    for (const link of out.querySelectorAll('a[download]')) URL.revokeObjectURL(link.href);
    out.replaceChildren();
    try {
      await run(out);
    } catch (error) {
      addMessage(out, error.message, 'err');
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });
}

async function processFiles(out, files, process) {
  for (const file of files) {
    try {
      await yieldToUI();
      await process(await loadImage(file));
    } catch (error) {
      addMessage(out, `${file.name}: ${error.message}`, 'err');
    }
  }
}

function stem(name) { return name.replace(/\.[^.]+$/, ''); }
$('iter-encrypt').addEventListener('input', e => $('iter-out').textContent = e.target.value);

wireRun('encrypt', async out => {
  const files = getEncryptFiles();
  const pass = $('pass-encrypt').value;
  if (!pass || pass !== $('pass2-encrypt').value) throw new Error('Enter matching passphrases.');
  const iter = Number($('iter-encrypt').value);
  await processFiles(out, files, async ({ pixels, width, height, channels, name }) => {
    const result = await encryptImage(pixels, width, height, channels, pass, iter);
    addOutput(out, name, stem(name) + '_encrypted.png', result);
  });
});

wireRun('decrypt', async out => {
  const files = getDecryptFiles();
  const pass = $('pass-decrypt').value;
  if (!pass) throw new Error('Enter a passphrase.');
  await processFiles(out, files, async ({ pixels, width, height, channels, name }) => {
    const result = await decryptImage(pixels, width, height, channels, pass);
    addOutput(out, name, stem(name).replace(/_encrypted$/, '') + '_decrypted.png', result);
  });
});

wireRun('verify', async out => {
  const pass = $('pass-verify').value || null;
  await processFiles(out, getVerifyFiles(), async ({ pixels, width, height, channels, name }) => {
    const v = await verifyImage(pixels, width, height, channels, pass);
    const info = v.iterations ? ` (v${v.version}, ${v.width}×${v.height}, ${v.channels}ch, strip ${v.stripRows}, ${v.iterations} iters)` : '';
    const variant = v.authenticated ? 'ok' : v.status === 'unauthenticated' ? '' : 'err';
    addMessage(out, `${name}: [${v.status}] ${v.message}${info}`, variant);
  });
});

wireRun('analyze', async out => {
  const canvas = $('hist');
  const ctx = canvas.getContext('2d');
  canvas.hidden = true;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const files = getAnalyzeFiles();
  const a = await loadImage(files[0]);
  const ent = entropyReport(a.pixels, a.width, a.height, a.channels);
  let txt = `${a.name}: entropy mean ${ent.mean.toFixed(4)} bits/byte`;
  for (let c = 0; c < a.channels; c++) {
    const corr = adjacentCorrelation(a.pixels, a.width, a.height, a.channels, c);
    txt += ` · ch${c} corr H ${corr.horizontal.toFixed(3)} V ${corr.vertical.toFixed(3)} D ${corr.diagonal.toFixed(3)}`;
  }
  addMessage(out, txt);
  // Histogram of channel 0
  const h = histogram(a.pixels, a.width, a.height, a.channels, 0);
  const max = Math.max(...h);
  ctx.fillStyle = '#4da3ff';
  const barWidth = canvas.width / h.length;
  h.forEach((value, i) => {
    const barHeight = value / max * (canvas.height - 10);
    ctx.fillRect(i * barWidth, canvas.height - barHeight, barWidth, barHeight);
  });
  canvas.hidden = false;
  if (files.length === 2) {
    const b = await loadImage(files[1]);
    if (a.width !== b.width || a.height !== b.height || a.channels !== b.channels) {
      throw new Error('NPCR and UACI require matching dimensions and channel counts.');
    }
    addMessage(out, `NPCR ${npcr(a.pixels, b.pixels).toFixed(2)}% · UACI ${uaci(a.pixels, b.pixels).toFixed(2)}%`);
  }
});
