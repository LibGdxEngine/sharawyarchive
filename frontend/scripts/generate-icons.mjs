/**
 * generate-icons.mjs
 *
 * Generates all site icons and PWA icons from public/icon.png using sharp.
 *
 * Run: npm run generate-icons (or node scripts/generate-icons.mjs)
 */

import sharp from "sharp";
import { promises as fs } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, "..");
const publicDir = path.join(rootDir, "public");
const appDir = path.join(rootDir, "src", "app");
const iconsDir = path.join(publicDir, "icons");

const sourceIconPath = path.join(publicDir, "icon.png");

await fs.mkdir(iconsDir, { recursive: true });
await fs.mkdir(appDir, { recursive: true });

const sourceBuffer = await fs.readFile(sourceIconPath);

/**
 * Creates a valid multi-resolution ICO file containing PNG streams for sizes [16, 32, 48].
 */
async function generateIco(inputBuf, sizes = [16, 32, 48]) {
  const pngBuffers = await Promise.all(
    sizes.map((s) => sharp(inputBuf).resize(s, s).png().toBuffer())
  );

  const headerSize = 6;
  const dirEntrySize = 16;
  const numImages = sizes.length;
  let offset = headerSize + numImages * dirEntrySize;

  const header = Buffer.alloc(headerSize);
  header.writeUInt16LE(0, 0); // Reserved
  header.writeUInt16LE(1, 2); // ICO format
  header.writeUInt16LE(numImages, 4);

  const dirEntries = [];
  for (let i = 0; i < numImages; i++) {
    const size = sizes[i];
    const pngBuf = pngBuffers[i];
    const entry = Buffer.alloc(dirEntrySize);
    entry.writeUInt8(size >= 256 ? 0 : size, 0); // Width
    entry.writeUInt8(size >= 256 ? 0 : size, 1); // Height
    entry.writeUInt8(0, 2); // Color palette
    entry.writeUInt8(0, 3); // Reserved
    entry.writeUInt16LE(1, 4); // Color planes
    entry.writeUInt16LE(32, 6); // Bits per pixel
    entry.writeUInt32LE(pngBuf.length, 8); // PNG size
    entry.writeUInt32LE(offset, 12); // PNG offset
    dirEntries.push(entry);
    offset += pngBuf.length;
  }

  return Buffer.concat([header, ...dirEntries, ...pngBuffers]);
}

// 1. Standard PNG sizes for public/icons
const iconsToGenerate = [
  { dest: path.join(iconsDir, "icon-192.png"), size: 192 },
  { dest: path.join(iconsDir, "icon-512.png"), size: 512 },
  { dest: path.join(publicDir, "apple-touch-icon.png"), size: 180 },
  { dest: path.join(appDir, "icon.png"), size: 32 },
];

for (const { dest, size } of iconsToGenerate) {
  await sharp(sourceBuffer).resize(size, size).png().toFile(dest);
  const stat = await fs.stat(dest);
  console.log(`✓ ${path.relative(rootDir, dest)} (${size}×${size}, ${(stat.size / 1024).toFixed(1)} KB)`);
}

// 2. Maskable icons (padded inside background color if needed, or resized)
const maskableIcons = [
  { dest: path.join(iconsDir, "icon-maskable-192.png"), size: 192 },
  { dest: path.join(iconsDir, "icon-maskable-512.png"), size: 512 },
];

for (const { dest, size } of maskableIcons) {
  const padding = Math.round(size * 0.1);
  const innerSize = size - padding * 2;
  const resizedInner = await sharp(sourceBuffer).resize(innerSize, innerSize).png().toBuffer();

  await sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: { r: 26, g: 107, b: 74, alpha: 1 }, // #1a6b4a
    },
  })
    .composite([{ input: resizedInner, top: padding, left: padding }])
    .png()
    .toFile(dest);

  const stat = await fs.stat(dest);
  console.log(`✓ ${path.relative(rootDir, dest)} (maskable ${size}×${size}, ${(stat.size / 1024).toFixed(1)} KB)`);
}

// 3. ICO files (public/favicon.ico & src/app/favicon.ico)
const icoBuf = await generateIco(sourceBuffer);
const icoPaths = [
  path.join(publicDir, "favicon.ico"),
  path.join(appDir, "favicon.ico"),
];

for (const dest of icoPaths) {
  await fs.writeFile(dest, icoBuf);
  console.log(`✓ ${path.relative(rootDir, dest)} (Multi-resolution ICO, ${(icoBuf.length / 1024).toFixed(1)} KB)`);
}

console.log("All website icons successfully generated from public/icon.png!");
