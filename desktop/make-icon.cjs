// Builds the desktop app's icon (icon.icns, and icon.png for the Dock while developing) from
// the logo in brand/. Run it again when the logo changes:
//
//   node desktop/make-icon.cjs
//
// It needs a Mac (iconutil) and `npm ci` done in web/, since it borrows sharp from there.
//
// macOS draws an app's shape smaller than the icon's canvas, 824 px on 1024, so that icons
// of different shapes look the same size in the Dock. The logo's own files fill the canvas,
// which is right for a favicon but would make Zwans look bigger than its neighbours.

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const sharp = require(path.join(__dirname, "..", "web", "node_modules", "sharp"));

const CANVAS = 1024;
const SHAPE = 824;
const LOGO = path.join(__dirname, "..", "brand", "zwans-icon-dark.svg");

async function main() {
  const shape = await sharp(fs.readFileSync(LOGO)).resize(SHAPE, SHAPE).png().toBuffer();
  const margin = (CANVAS - SHAPE) / 2;
  const clear = { r: 0, g: 0, b: 0, alpha: 0 };
  const icon = await sharp({ create: { width: CANVAS, height: CANVAS, channels: 4, background: clear } })
    .composite([{ input: shape, left: margin, top: margin }])
    .png()
    .toBuffer();

  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zwans-icon-"));
  const iconset = path.join(folder, "icon.iconset");
  fs.mkdirSync(iconset);
  for (const size of [16, 32, 128, 256, 512]) {
    for (const scale of [1, 2]) {
      const name = `icon_${size}x${size}${scale === 2 ? "@2x" : ""}.png`;
      await sharp(icon).resize(size * scale, size * scale).png().toFile(path.join(iconset, name));
    }
  }
  execFileSync("iconutil", ["-c", "icns", iconset, "-o", path.join(__dirname, "icon.icns")]);
  await sharp(icon).resize(512, 512).png().toFile(path.join(__dirname, "icon.png"));
  fs.rmSync(folder, { recursive: true });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
