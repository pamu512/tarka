/**
 * Rasterizes the full Tarka lockup to high-resolution transparent PNGs (4×).
 * Run: node scripts/export-tarka-brand.mjs (requires `sharp`).
 */
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "../public/brand");
mkdirSync(outDir, { recursive: true });

const W = 800;
const H = 688;

function fullLockupSvg(hex) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 200 172">
  <g fill="${hex}" font-family="system-ui, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif">
    <g transform="translate(80, 2)">
      <path d="M3 10.5h12.75v4.25H3V10.5z"/>
      <path d="M17.75 10.5h8.75v40H17.75v-40z"/>
      <path d="M26.5 10.5C33 8 39.5 12 39 17.5 38.5 21.5 33 23 26.5 21V10.5z"/>
    </g>
    <text x="100" y="84" text-anchor="middle" font-size="21" font-weight="800" letter-spacing="0.2em">TARKA</text>
    <text x="100" y="106" text-anchor="middle" font-size="10" font-weight="400">Prove every signal.</text>
  </g>
</svg>`;
}

const markSvg = (hex) => `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <g transform="translate(312, 252) scale(10)">
    <g fill="${hex}">
      <path d="M3 10.5h12.75v4.25H3V10.5z"/>
      <path d="M17.75 10.5h8.75v40H17.75v-40z"/>
      <path d="M26.5 10.5C33 8 39.5 12 39 17.5 38.5 21.5 33 23 26.5 21V10.5z"/>
    </g>
  </g>
</svg>`;

async function main() {
  await sharp(Buffer.from(fullLockupSvg("#0f172a")))
    .png({ compressionLevel: 9 })
    .toFile(join(outDir, "tarka-logo-on-light-bg.png"));

  await sharp(Buffer.from(fullLockupSvg("#ffffff")))
    .png({ compressionLevel: 9 })
    .toFile(join(outDir, "tarka-logo-on-dark-bg.png"));

  await sharp(Buffer.from(markSvg("#0f172a")))
    .png({ compressionLevel: 9 })
    .toFile(join(outDir, "tarka-mark-on-light-bg.png"));

  await sharp(Buffer.from(markSvg("#ffffff")))
    .png({ compressionLevel: 9 })
    .toFile(join(outDir, "tarka-mark-on-dark-bg.png"));

  console.log("Wrote PNGs to public/brand/");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
