// The Zwans desktop app: a window around `zwans serve`.
//
// It runs the Zwans installed from this checkout, on a free port, from the checkout's folder
// (so the server finds its .env and eval reports), and stops it on quit. Everything you see
// is the web UI in web/out; the one native thing it adds is a folder picker (preload.cjs).

const { app, BrowserWindow, dialog, ipcMain, screen, shell } = require("electron");
const { execFileSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const CONDA_ROOTS = [
  "/opt/homebrew/Caskroom/miniforge/base",
  path.join(os.homedir(), "miniforge3"),
  path.join(os.homedir(), "miniconda3"),
  path.join(os.homedir(), "anaconda3"),
];
const READY_TIMEOUT_MS = 30_000;
const STOP_TIMEOUT_MS = 3_000;
const LOG_CHARS = 4_000; // of the server's output, kept to show if it fails
const SHOWING_PX = 100; // how much of a restored window must be on a screen to grab it

let window = null;
let server = null;
let origin = null; // the server's address, the only place the window may go
let log = "";
let quitting = false;

/** The checkout: written into a packed app (`npm run pack`), or the folder above this one. */
function checkout() {
  try {
    return fs.readFileSync(path.join(__dirname, "checkout.txt"), "utf8").trim();
  } catch {
    return path.resolve(__dirname, "..");
  }
}

function boundsFile() {
  return path.join(app.getPath("userData"), "window.json");
}

/** The window's size from last time, and its place too if that is still on a screen. */
function savedBounds() {
  try {
    const { x, y, width, height } = JSON.parse(fs.readFileSync(boundsFile(), "utf8"));
    if (![x, y, width, height].every(Number.isFinite)) return {};
    const area = screen.getDisplayMatching({ x, y, width, height }).workArea;
    const reachable =
      x + width > area.x + SHOWING_PX &&
      x < area.x + area.width - SHOWING_PX &&
      y >= area.y &&
      y < area.y + area.height - SHOWING_PX;
    return reachable ? { x, y, width, height } : { width, height };
  } catch {
    return {}; // no file yet, or not one of ours
  }
}

function saveBounds() {
  if (!window || window.isDestroyed()) return;
  try {
    // The size it returns to, not a maximized or full-screen one.
    fs.writeFileSync(boundsFile(), JSON.stringify(window.getNormalBounds()));
  } catch {
    // Next time it opens at the default size.
  }
}

/** The PATH of a login shell: an app started from the Dock gets only a minimal one, and the
 * agent's commands need the same tools as in a terminal. */
function loginPath() {
  const shellPath = process.env.SHELL || "/bin/zsh";
  try {
    const output = execFileSync(shellPath, ["-ilc", 'printf "\\n%s" "$PATH"'], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 5_000,
    });
    return output.split("\n").pop();
  } catch {
    return process.env.PATH ?? "";
  }
}

/** The zwans program: $ZWANS_BIN, then a conda env named zwans, then PATH. */
function findZwans(searchPath) {
  const candidates = [
    process.env.ZWANS_BIN,
    ...CONDA_ROOTS.map((root) => path.join(root, "envs", "zwans", "bin", "zwans")),
    ...searchPath.split(path.delimiter).map((folder) => path.join(folder, "zwans")),
  ];
  return candidates.find((file) => file && fs.existsSync(file)) ?? null;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.on("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function keepLog(chunk) {
  log = (log + chunk).slice(-LOG_CHARS);
}

/** What the server has printed, without the token in its address line. */
function shownLog() {
  return log.replace(/#token=\S+/g, "").trim();
}

/** Start the server and resolve with its address and token once it answers. */
async function startServer() {
  const searchPath = loginPath();
  const zwans = findZwans(searchPath);
  if (!zwans) {
    throw new Error(`Couldn't find zwans. Install it (pip install -e .) or set ZWANS_BIN.`);
  }
  const port = await freePort();
  log = "";
  const child = spawn(zwans, ["serve", "--port", String(port)], {
    cwd: checkout(),
    env: { ...process.env, PATH: [path.dirname(zwans), searchPath].join(path.delimiter) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server = child;
  child.stderr.on("data", (chunk) => keepLog(String(chunk)));
  const address = new Promise((resolve) => {
    let printed = "";
    child.stdout.on("data", (chunk) => {
      keepLog(String(chunk));
      printed += chunk;
      const match = printed.match(/(http:\/\/\S+?)\/#token=(\S+)/);
      if (match) resolve({ url: match[1], token: match[2] });
    });
  });
  child.on("exit", (code) => {
    if (server === child) server = null;
    if (!quitting && origin) serverDied(code);
  });

  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`zwans serve exited with ${child.exitCode}.`);
    try {
      const health = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (health.ok) return await address;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("zwans serve didn't start in time.");
}

function stopServer() {
  const child = server;
  if (!child) return Promise.resolve();
  return new Promise((resolve) => {
    const force = setTimeout(() => child.kill("SIGKILL"), STOP_TIMEOUT_MS);
    child.once("exit", () => {
      clearTimeout(force);
      resolve();
    });
    child.kill("SIGINT"); // like Ctrl+C, so `zwans serve` cleans up after itself
  });
}

async function open() {
  origin = null;
  await window.loadFile(path.join(__dirname, "starting.html"));
  let address;
  try {
    address = await startServer();
  } catch (error) {
    await stopServer();
    return failed(error.message);
  }
  origin = new URL(address.url).origin;
  await window.loadURL(`${address.url}/#token=${address.token}`);
}

async function failed(message) {
  const detail = shownLog();
  const { response } = await dialog.showMessageBox(window, {
    type: "error",
    message: "Zwans couldn't start",
    detail: detail ? `${message}\n\n${detail}` : message,
    buttons: ["Try again", "Quit"],
  });
  if (response === 0) open();
  else app.quit();
}

function serverDied(code) {
  failed(`The Zwans server stopped unexpectedly (exit code ${code}).`);
}

function openOutside(url) {
  const { protocol } = new URL(url);
  if (protocol === "http:" || protocol === "https:") shell.openExternal(url);
}

/** Links in the agent's replies open in the browser; this window stays on the server. */
function keepWindowHome(contents) {
  contents.setWindowOpenHandler(({ url }) => {
    openOutside(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (origin && new URL(url).origin === origin) return;
    event.preventDefault();
    openOutside(url);
  });
}

function createWindow() {
  const mac = process.platform === "darwin";
  window = new BrowserWindow({
    width: 1320,
    height: 880,
    ...savedBounds(),
    minWidth: 900,
    minHeight: 600,
    title: "Zwans",
    // On macOS: no title bar, the window buttons over the sidebar, and the desktop blurred
    // behind the page (the web UI leaves room for the buttons when it sees the app).
    ...(mac && {
      titleBarStyle: "hiddenInset",
      trafficLightPosition: { x: 22, y: 24 },
      vibrancy: "under-window",
      visualEffectState: "followWindow",
      backgroundColor: "#00000000",
    }),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  keepWindowHome(window.webContents);
  window.on("page-title-updated", (event) => event.preventDefault());
  window.on("close", saveBounds);
  window.on("closed", () => {
    window = null;
  });
  open();
}

ipcMain.handle("pick-folder", async (event) => {
  if (!origin || new URL(event.senderFrame.url).origin !== origin) return null;
  const result = await dialog.showOpenDialog(window, {
    properties: ["openDirectory", "createDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app.whenReady().then(createWindow);
  // Closing the window ends the app: the sessions live in its server.
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    quitting = true;
    if (!server) return;
    event.preventDefault();
    stopServer().then(() => app.quit());
  });
}
