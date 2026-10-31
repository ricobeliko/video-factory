import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webuiRoot = path.resolve(__dirname, '..');
const srcDir = path.join(webuiRoot, 'src');
const lockFile = path.join(webuiRoot, 'package-lock.json');
const distDir = path.join(webuiRoot, 'dist');
const stampFile = path.join(distDir, 'BUILD_STAMP.json');

function getAllFiles(dir, fileList = []) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    if (file.startsWith('.')) continue;
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      getAllFiles(fullPath, fileList);
    } else {
      fileList.push(fullPath);
    }
  }
  return fileList;
}

export function computeBuildStamp() {
  // 1. src_hash
  const allFiles = getAllFiles(srcDir);
  const fileEntries = [];
  for (const f of allFiles) {
    const relPath = path.relative(srcDir, f).replace(/\\/g, '/');
    let content = fs.readFileSync(f);
    // Normalize CRLF to LF
    content = Buffer.from(content.toString('latin1').replace(/\r\n/g, '\n'), 'latin1');
    const fHash = crypto.createHash('sha256').update(content).digest('hex');
    fileEntries.push(`${relPath}:${fHash}`);
  }
  fileEntries.sort();
  const manifest = Buffer.from(fileEntries.join('\n'), 'utf-8');
  const srcHash = crypto.createHash('sha256').update(manifest).digest('hex');

  // 2. package_lock_hash
  let lockRaw = fs.readFileSync(lockFile);
  lockRaw = Buffer.from(lockRaw.toString('latin1').replace(/\r\n/g, '\n'), 'latin1');
  const lockHash = crypto.createHash('sha256').update(lockRaw).digest('hex');

  // 3. vite_version
  const lockData = JSON.parse(lockRaw.toString('utf-8'));
  const viteVersion =
    lockData.packages?.['node_modules/vite']?.version ||
    lockData.dependencies?.vite?.version ||
    '';

  // 4. combined_hash
  const combinedRaw = Buffer.from(`${srcHash}:${lockHash}:${viteVersion}`, 'utf-8');
  const combinedHash = crypto.createHash('sha256').update(combinedRaw).digest('hex');

  return {
    src_hash: srcHash,
    package_lock_hash: lockHash,
    vite_version: viteVersion,
    combined_hash: combinedHash,
    built_at: new Date().toISOString(),
  };
}

export function writeBuildStamp() {
  if (!fs.existsSync(distDir)) {
    fs.mkdirSync(distDir, { recursive: true });
  }
  const stamp = computeBuildStamp();
  fs.writeFileSync(stampFile, JSON.stringify(stamp, null, 2) + '\n', 'utf-8');
  console.log(`[BUILD_STAMP] Generated ${stampFile} (combined_hash=${stamp.combined_hash})`);
  return stamp;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeBuildStamp();
}
