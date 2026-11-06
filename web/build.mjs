// Bundle web/src/app.js -> web/dist/ (static site for GitHub Pages / Android WebView).
import { build } from 'esbuild';
import { cpSync, mkdirSync, rmSync } from 'fs';

rmSync('dist', { recursive: true, force: true });
mkdirSync('dist/assets', { recursive: true });
await build({
  entryPoints: ['src/app.js'],
  bundle: true,
  format: 'esm',
  minify: true,
  outfile: 'dist/assets/app.js',
  target: ['es2020'],
});
cpSync('index.html', 'dist/index.html');
cpSync('style.css', 'dist/style.css');
cpSync('manifest.webmanifest', 'dist/manifest.webmanifest');
console.log('built web/dist');
