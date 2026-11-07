import test from 'node:test';
import assert from 'node:assert/strict';
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
