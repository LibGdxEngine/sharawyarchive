/**
 * generate-icons.mjs
 *
 * Generates PWA icons using sharp (no canvas, no native bindings beyond sharp's own).
 *
 * SVG mark: the Arabic letter ش on the accent color background (#1a6b4a),
 * with generous safe-zone padding to work as a maskable icon.
 *
 * Run: node scripts/generate-icons.mjs
 */

import sharp from "sharp";
import { promises as fs } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "..", "public");
const iconsDir = path.join(publicDir, "icons");

await fs.mkdir(iconsDir, { recursive: true });

// Design tokens
const BG_COLOR = "#1a6b4a"; // accent (forest green) — used as app identity colour for icons
const TEXT_COLOR = "#ffffff";

/**
 * Build an SVG string with the letter ش centred.
 *
 * @param {number} size    Canvas size in px
 * @param {number} padding Safe-zone padding fraction for maskable icons (0 = none)
 */
function buildSvg(size, padding = 0) {
  const safePad = Math.round(size * padding);
  const innerSize = size - safePad * 2;
  const fontSize = Math.round(innerSize * 0.55);
  const cx = size / 2;
  const cy = size / 2;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="${BG_COLOR}" rx="${Math.round(size * 0.12)}"/>
  <text
    x="${cx}"
    y="${cy}"
    text-anchor="middle"
    dominant-baseline="central"
    font-family="sans-serif"
    font-size="${fontSize}"
    font-weight="bold"
    fill="${TEXT_COLOR}"
  >ش</text>
</svg>`;
}

/** Build maskable variant: white circle background, icon inside safe zone */
function buildMaskableSvg(size) {
  const padding = 0.1; // 10% safe zone per spec recommendation
  const safePad = Math.round(size * padding);
  const innerSize = size - safePad * 2;
  const fontSize = Math.round(innerSize * 0.55);
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <circle cx="${cx}" cy="${cy}" r="${radius}" fill="${BG_COLOR}"/>
  <text
    x="${cx}"
    y="${cy}"
    text-anchor="middle"
    dominant-baseline="central"
    font-family="sans-serif"
    font-size="${fontSize}"
    font-weight="bold"
    fill="${TEXT_COLOR}"
  >ش</text>
</svg>`;
}

const icons = [
  { name: "icon-192.png", size: 192, maskable: false },
  { name: "icon-512.png", size: 512, maskable: false },
  { name: "icon-maskable-192.png", size: 192, maskable: true },
  { name: "icon-maskable-512.png", size: 512, maskable: true },
];

for (const { name, size, maskable } of icons) {
  const svg = maskable ? buildMaskableSvg(size) : buildSvg(size);
  const dest = path.join(iconsDir, name);
  await sharp(Buffer.from(svg))
    .png()
    .toFile(dest);
  const stat = await fs.stat(dest);
  console.log(`✓ ${name}  (${size}×${size}, ${(stat.size / 1024).toFixed(1)} KB)`);
}

console.log("Icons generated successfully.");
