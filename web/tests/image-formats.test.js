import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { GOOGLE_PHOTOS_EXTENSIONS } from '../src/image-format-list.js';

test('web importer advertises every Google Photos backup photo extension', () => {
  for (const ext of ['.jpg', '.jpeg', '.heic', '.heif', '.png', '.webp', '.gif', '.avif']) {
    assert.ok(GOOGLE_PHOTOS_EXTENSIONS.includes(ext), `missing ${ext}`);
  }
});

test('web importer includes common Google Photos camera RAW extensions', () => {
  for (const ext of ['.dng', '.cr2', '.cr3', '.nef', '.arw', '.raf', '.rw2', '.orf']) {
    assert.ok(GOOGLE_PHOTOS_EXTENSIONS.includes(ext), `missing ${ext}`);
  }
});

test('bundled AVIF decoder loads its WASM beside the module', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'opticipher-web-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const bundle = join(directory, 'site', 'assets', 'formats.mjs');
  await build({
    entryPoints: [fileURLToPath(new URL('../src/image-formats.js', import.meta.url))],
    outfile: bundle,
    bundle: true,
    format: 'esm',
    assetNames: 'assets/[name]-[hash]',
    loader: { '.wasm': 'file' },
  });
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(new URL(url).protocol, 'file:');
    return new Response(await readFile(new URL(url)), { headers: { 'Content-Type': 'application/wasm' } });
  });
  if (!globalThis.ImageData) {
    globalThis.ImageData = class ImageData {
      constructor(data, width, height) {
        Object.assign(this, { data, width, height });
      }
    };
    t.after(() => { delete globalThis.ImageData; });
  }

  // A 24 × 20 RGB gradient encoded locally for this test.
  const avif = Buffer.from(
    'AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADrbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAAAAAAAOcGl0bQAAAAAAAQAAAB5pbG9jAAAAAEQAAAEAAQAAAAEAAAETAAAAWgAAAChpaW5mAAAAAAABAAAAGmluZmUCAAAAAAEAAGF2MDFDb2xvcgAAAABqaXBycAAAAEtpcGNvAAAAFGlzcGUAAAAAAAAAGAAAABQAAAAQcGl4aQAAAAADCAgIAAAADGF2MUOBAAwAAAAAE2NvbHJuY2x4AAEADQAGgAAAABdpcG1hAAAAAAAAAAEAAQQBAoMEAAAAYm1kYXQSAAoJGBEvNogIaDQgMksUx4eGZQIIIJ5QAAAARdOuCEPqwC9YRVt/eecU3Lq7gM6JWm4wAhHS62RvXRkv/i1yQL3TWHbFbTZ4lXHiak8+T9d7cSW1IrRYKsM=',
    'base64',
  );
  const { loadImage } = await import(pathToFileURL(bundle));
  const decoded = await loadImage(new File([avif], 'gradient.avif', { type: 'image/avif' }));
  assert.deepEqual([decoded.width, decoded.height, decoded.channels], [24, 20, 3]);
  assert.equal(decoded.pixels.length, 24 * 20 * 3);
});
