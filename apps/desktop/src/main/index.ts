import { app, BrowserWindow, dialog, ipcMain, nativeImage, shell } from "electron";
import { join, resolve, relative } from "node:path";
import { homedir } from "node:os";
import { ChildProcess, execSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, statSync } from "node:fs";

/* ------------------------------------------------------------------ */
/*  Engine lifecycle – same semantics as the old Tauri Rust backend   */
/* ------------------------------------------------------------------ */

let engineProcess: ChildProcess | null = null;
let _lastEngineError = "";

interface EngineStatus {
  running: boolean;
  pid: number | null;
  apiUrl: string;
}

interface RuntimeConfig {
  electronSandbox: boolean;
  worktreeMode: "project" | "git_worktree";
  worktreeRoot: string;
}

const SAFE_ENGINE_HOSTS = new Set([
  "127.0.0.1",
  "localhost",
  "::1",
]);
const hasElectronRuntime = Boolean(app && typeof app.whenReady === "function");

function sanitizeEngineHost(raw?: string): string {
  const host = String(raw ?? "127.0.0.1").trim().toLowerCase();
  return SAFE_ENGINE_HOSTS.has(host) ? host : "127.0.0.1";
}

function sanitizeEnginePort(raw?: number): number {
  if (typeof raw !== "number" || !Number.isInteger(raw)) return 8787;
  if (raw < 1 || raw > 65535) return 8787;
  return raw;
}

/**
 * Default workspace directory when the user hasn't selected a folder or cloned a repo.
 * Similar to how Claude Code uses ~/.claude — Rigovo uses ~/.rigovo/workspace.
 * Auto-creates the directory on first access.
 */
function defaultWorkspace(): string {
  const ws = join(homedir(), ".rigovo", "workspace");
  if (!existsSync(ws)) {
    mkdirSync(ws, { recursive: true });
  }
  return ws;
}

const ALLOWED_EXTERNAL_PROTOCOLS = new Set([
  "https:",
  "http:",
  "vscode:",
  "cursor:",
  "zed:",
  "windsurf:",
  "phpstorm:",
  "idea:",
]);

function isSafeExternalUrl(raw: string): boolean {
  try {
    const u = new URL(raw);
    return ALLOWED_EXTERNAL_PROTOCOLS.has(u.protocol);
  } catch {
    return false;
  }
}

/* ── Anti-flooding: global external URL rate limiter ── */
// HARD protection against runaway browser tab flooding.
// Rules:
//   1. Same URL can only be opened once per 60 seconds
//   2. Max 3 external opens per 60 seconds total (burst limit)
//   3. During app shutdown, block ALL external opens
//   4. NEVER open more than 10 unique URLs per session

const _urlOpenHistory: Map<string, number> = new Map();
const _globalOpenTimes: number[] = [];
let _appShuttingDown = false;
let _sessionOpenCount = 0;
const MAX_SESSION_OPENS = 10;

function canOpenExternalUrl(url: string): boolean {
  if (_appShuttingDown) return false;

  // Hard session cap — no app should ever need to open 10+ browser tabs
  if (_sessionOpenCount >= MAX_SESSION_OPENS) {
    console.warn("[rigovo] HARD BLOCK: session limit reached (" + MAX_SESSION_OPENS + " opens). url:", url);
    return false;
  }

  const now = Date.now();

  // Rule 1: Same URL blocked for 60 seconds
  const lastOpen = _urlOpenHistory.get(url);
  if (lastOpen && now - lastOpen < 60_000) {
    console.warn("[rigovo] Blocked duplicate URL open (cooldown 60s):", url);
    return false;
  }

  // Rule 2: Max 3 opens in any 60-second window
  while (_globalOpenTimes.length > 0 && now - _globalOpenTimes[0] > 60_000) {
    _globalOpenTimes.shift();
  }
  if (_globalOpenTimes.length >= 3) {
    console.warn("[rigovo] Blocked external URL open (burst limit 3/60s):", url);
    return false;
  }

  // Record this open
  _urlOpenHistory.set(url, now);
  _globalOpenTimes.push(now);
  _sessionOpenCount++;

  return true;
}

function parseBoolEnv(name: string, defaultValue: boolean): boolean {
  const raw = String(process.env[name] ?? "").trim().toLowerCase();
  if (!raw) return defaultValue;
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

function runtimeConfig(): RuntimeConfig {
  const worktreeModeRaw = String(process.env.RIGOVO_WORKTREE_MODE ?? "project").trim().toLowerCase();
  const worktreeMode = worktreeModeRaw === "git_worktree" ? "git_worktree" : "project";
  return {
    electronSandbox: parseBoolEnv("RIGOVO_DESKTOP_ELECTRON_SANDBOX", true),
    worktreeMode,
    worktreeRoot: String(process.env.RIGOVO_WORKTREE_ROOT ?? "").trim(),
  };
}

function engineStatus(host = "127.0.0.1", port = 8787): EngineStatus {
  if (engineProcess && engineProcess.exitCode === null) {
    return { running: true, pid: engineProcess.pid ?? null, apiUrl: `http://${host}:${port}` };
  }
  engineProcess = null;
  return { running: false, pid: null, apiUrl: `http://${host}:${port}` };
}

function startEngine(
  host = "127.0.0.1",
  port = 8787,
  projectDir?: string
): EngineStatus {
  const status = engineStatus(host, port);
  if (status.running) return status;

  const rigovoBin = String(process.env.RIGOVO_BIN ?? "rigovo").trim() || "rigovo";
  const args = ["serve", "--host", host, "--port", String(port)];
  let safeProjectDir: string | undefined;
  const candidate = projectDir ? String(projectDir).trim() : "";
  if (candidate && candidate !== ".") {
    try {
      const stats = statSync(candidate);
      if (stats.isDirectory()) {
        safeProjectDir = candidate;
      }
    } catch {
      safeProjectDir = undefined;
    }
  }
  // Fall back to ~/.rigovo/workspace when no folder is selected
  if (!safeProjectDir) {
    safeProjectDir = defaultWorkspace();
  }
  args.push("--project", safeProjectDir);
  const opts: { cwd?: string } = { cwd: safeProjectDir };
  const runtime = runtimeConfig();

  _lastEngineError = "";
  engineProcess = spawn(rigovoBin, args, {
    ...opts,
    env: {
      ...process.env,
      RIGOVO_WORKTREE_MODE: runtime.worktreeMode,
      RIGOVO_WORKTREE_ROOT: runtime.worktreeRoot,
    },
    stdio: ["ignore", "ignore", "pipe"],
    detached: false
  });

  // Capture stderr so startup failures are surfaced to the UI
  const stderrChunks: string[] = [];
  engineProcess.stderr?.on("data", (chunk: Buffer) => {
    const text = chunk.toString("utf8");
    stderrChunks.push(text);
    // Keep last 4 KB — enough to diagnose any startup error
    const joined = stderrChunks.join("");
    if (joined.length > 4096) {
      stderrChunks.splice(0, stderrChunks.length, joined.slice(-4096));
    }
    _lastEngineError = stderrChunks.join("").trim();
  });

  engineProcess.on("error", (err: Error) => {
    _lastEngineError = `Failed to start engine process: ${err.message}`;
    engineProcess = null;
  });
  engineProcess.on("exit", (code: number | null) => {
    if (code !== 0 && code !== null) {
      const stderr = stderrChunks.join("").trim();
      _lastEngineError = stderr
        ? `Engine exited (code ${code}):\n${stderr}`
        : `Engine process exited unexpectedly (code ${code}). Check that the 'rigovo' binary is installed and your API keys are configured.`;
    }
    engineProcess = null;
  });

  return engineStatus(host, port);
}

function stopEngine(): EngineStatus {
  if (engineProcess && engineProcess.exitCode === null) {
    engineProcess.kill();
  }
  engineProcess = null;
  return { running: false, pid: null, apiUrl: "http://127.0.0.1:8787" };
}

/* ------------------------------------------------------------------ */
/*  Project file scanner                                              */
/* ------------------------------------------------------------------ */

const SCAN_EXCLUDE = new Set([
  "node_modules", ".git", ".hg", ".svn",
  "__pycache__", ".venv", "venv", "env",
  "dist", "build", ".next", ".nuxt", ".output",
  ".rigovo", ".rigour", ".turbo", ".cache",
  "coverage", ".nyc_output", "tmp", ".tmp",
]);

interface WalkOpts { root: string; dir: string; results: string[]; depth: number; maxDepth: number; maxFiles: number }

function walkProjectFiles(opts: WalkOpts): void {
  const { root, dir, results, depth, maxDepth, maxFiles } = opts;
  if (depth > maxDepth || results.length >= maxFiles) return;
  let entries: ReturnType<typeof readdirSync>;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (results.length >= maxFiles) break;
    if (entry.name.startsWith(".") && entry.name !== ".env") continue;
    if (SCAN_EXCLUDE.has(entry.name)) continue;
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      walkProjectFiles({ root, dir: fullPath, results, depth: depth + 1, maxDepth, maxFiles });
    } else if (entry.isFile()) {
      results.push(relative(root, fullPath));
    }
  }
}

/* ------------------------------------------------------------------ */
/*  IPC handlers                                                      */
/* ------------------------------------------------------------------ */

function registerIpc(): void {
  ipcMain.handle("engine:status", () => engineStatus());
  ipcMain.handle("engine:runtime-config", () => runtimeConfig());

  ipcMain.handle(
    "engine:start",
    (_event, args: { host?: string; port?: number; projectDir?: string }) =>
      startEngine(
        sanitizeEngineHost(args?.host),
        sanitizeEnginePort(args?.port),
        args?.projectDir
      )
  );

  ipcMain.handle("engine:stop", () => stopEngine());
  ipcMain.handle("engine:last-error", () => _lastEngineError);

  // Open URL in system browser (for WorkOS AuthKit redirect flow).
  // Protected by global anti-flooding limiter.
  ipcMain.handle("shell:open-external", (_event, url: string) => {
    if (!isSafeExternalUrl(url)) {
      throw new Error("Blocked unsafe external URL");
    }
    if (!canOpenExternalUrl(url)) {
      return;
    }
    return shell.openExternal(url);
  });

  // List files in a project directory (for @ mention autocomplete)
  ipcMain.handle("fs:list-project-files", (_event, projectPath: string) => {
    try {
      const stats = statSync(projectPath);
      if (!stats.isDirectory()) return [];
      const results: string[] = [];
      walkProjectFiles({ root: projectPath, dir: projectPath, results, depth: 0, maxDepth: 5, maxFiles: 800 });
      return results;
    } catch {
      return [];
    }
  });

  // Folder picker dialog — user selects a project directory
  ipcMain.handle("dialog:open-folder", async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? BrowserWindow.getAllWindows()[0], {
      title: "Select Project Folder",
      properties: ["openDirectory"],
      buttonLabel: "Open Project",
    });
    if (result.canceled || !result.filePaths.length) return null;
    const folderPath = result.filePaths[0];
    try {
      const stats = statSync(folderPath);
      if (!stats.isDirectory()) {
        throw new Error("Selected path is not a directory");
      }
    } catch (err) {
      throw new Error(`Invalid folder path: ${err instanceof Error ? err.message : String(err)}`);
    }
    return folderPath;
  });

  // Git clone — shallow-clone a remote repo to a local destination
  ipcMain.handle("git:clone", async (_event, url: string, destDir: string) => {
    return new Promise<string>((resolve, reject) => {
      if (!url || !url.trim()) {
        reject(new Error("Repository URL cannot be empty"));
        return;
      }
      if (!destDir || !destDir.trim()) {
        reject(new Error("Destination directory cannot be empty"));
        return;
      }

      const stderr: string[] = [];
      const proc = spawn("git", ["clone", "--depth=1", url, destDir], {
        stdio: ["ignore", "ignore", "pipe"],
        detached: false,
      });

      const timeoutId = setTimeout(() => {
        proc.kill();
        reject(new Error("Git clone operation timed out (>60s)"));
      }, 60000);

      proc.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk.toString("utf8")));
      proc.on("close", (code) => {
        clearTimeout(timeoutId);
        if (code === 0) {
          resolve(destDir);
        } else {
          const errorMsg = stderr.join("").trim();
          const detail = errorMsg || `Process exited with code ${code}`;
          reject(new Error(`Git clone failed: ${detail}`));
        }
      });
      proc.on("error", (err) => {
        clearTimeout(timeoutId);
        reject(new Error(`Failed to spawn git process: ${err.message}`));
      });
    });
  });

  // Pick a parent directory for git clone destination
  ipcMain.handle("dialog:pick-clone-dest", async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? BrowserWindow.getAllWindows()[0], {
      title: "Choose Clone Destination",
      properties: ["openDirectory", "createDirectory"],
      buttonLabel: "Clone Here",
    });
    if (result.canceled || !result.filePaths.length) return null;
    const destPath = result.filePaths[0];
    try {
      const stats = statSync(destPath);
      if (!stats.isDirectory()) {
        throw new Error("Selected path is not a directory");
      }
    } catch (err) {
      throw new Error(`Invalid destination path: ${err instanceof Error ? err.message : String(err)}`);
    }
    return destPath;
  });
}

/* ------------------------------------------------------------------ */
/*  Window                                                            */
/* ------------------------------------------------------------------ */

function createWindow(): void {
  const runtime = runtimeConfig();
  const isDev = Boolean(process.env.ELECTRON_RENDERER_URL);

  const iconPath = (() => {
    const baseDirs = [
      join(__dirname, "../../resources"),
      join(app.getAppPath(), "resources"),
      resolve(process.cwd(), "resources"),
    ];
    const candidates: string[] = [];
    for (const dir of baseDirs) {
      candidates.push(join(dir, "icon.png"));
      if (process.platform === "win32") {
        candidates.push(join(dir, "icon.ico"));
      }
      if (process.platform === "darwin") {
        candidates.push(join(dir, "icon.icns"));
      }
    }
    for (const c of candidates) {
      try {
        if (existsSync(c) && statSync(c).isFile()) {
          console.log("[rigovo] icon found:", c);
          return c;
        }
      } catch { /* skip */ }
    }
    console.warn("[rigovo] no icon found. tried:", candidates);
    return undefined;
  })();

  if (iconPath && process.platform === "darwin" && app.dock) {
    try {
      const img = nativeImage.createFromPath(iconPath);
      if (!img.isEmpty()) {
        app.dock.setIcon(img);
        console.log("[rigovo] dock icon set from:", iconPath);
      } else {
        console.warn("[rigovo] dock icon image is empty:", iconPath);
      }
    } catch (e) {
      console.warn("[rigovo] dock icon failed:", e);
    }
  }

  const mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    title: "Rigovo Control Plane",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 14, y: 14 },
    ...(iconPath ? { icon: iconPath } : {}),
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: runtime.electronSandbox
    }
  });

  // Open external links in user's browser, not the Electron window.
  // Protected by global anti-flooding limiter (max 3/60s, dedup 60s, session cap 10).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url) && canOpenExternalUrl(url)) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  // Block navigation to external URLs inside the Electron window.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const allowed = isDev && process.env.ELECTRON_RENDERER_URL
      ? url.startsWith(process.env.ELECTRON_RENDERER_URL)
      : url.startsWith("file://");
    if (!allowed) {
      console.warn("[rigovo] Blocked in-window navigation to:", url);
      event.preventDefault();
    }
  });

  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

/* ------------------------------------------------------------------ */
/*  Port cleanup — free stale ports before starting                   */
/* ------------------------------------------------------------------ */

function killPort(port: number): void {
  const safePort = Math.trunc(Math.abs(port));
  if (!Number.isFinite(safePort) || safePort < 1 || safePort > 65535) return;

  try {
    if (process.platform === "win32") {
      const out = execSync(
        `netstat -ano | findstr :${String(safePort)} | findstr LISTENING`,
        { encoding: "utf8", timeout: 3000, windowsHide: true },
      );
      const pids = new Set(
        out.trim().split("\n")
          .map((l) => l.trim().split(/\s+/).pop())
          .filter((p): p is string => !!p && /^\d+$/.test(p)),
      );
      for (const pid of pids) {
        try { execSync(`taskkill /PID ${pid} /F`, { timeout: 3000, windowsHide: true }); } catch { /* ignore */ }
      }
    } else {
      const out = execSync(
        `lsof -ti :${String(safePort)}`,
        { encoding: "utf8", timeout: 3000 },
      ).trim();
      const pids = out.split("\n").filter((p) => /^\d+$/.test(p.trim()));
      for (const pid of pids) {
        try { process.kill(Number(pid), "SIGKILL"); } catch { /* ignore */ }
      }
    }
  } catch {
    // Port was not in use or kill failed — safe to ignore
  }
}

/* ------------------------------------------------------------------ */
/*  App lifecycle                                                     */
/* ------------------------------------------------------------------ */

async function bootstrapDesktop(): Promise<void> {
  if (!hasElectronRuntime) {
    console.error("Electron runtime is unavailable in this process.");
    return;
  }

  const isDev = Boolean(process.env.ELECTRON_RENDERER_URL);

  if (!isDev) {
    killPort(8787);
  }

  app.setName("Rigovo Virtual Team");

  await app.whenReady();
  registerIpc();
  createWindow();

  // Auto-updater REMOVED — was causing browser tab flooding.
  // Will re-add once we have proper GitHub releases published.

  // IPC: get current app version (still works without auto-updater)
  ipcMain.handle("app:version", () => app.getVersion());

  // IPC: get default workspace path (~/.rigovo/workspace)
  ipcMain.handle("app:defaultWorkspace", () => defaultWorkspace());

  // Stub IPC handlers so renderer doesn't crash calling removed auto-updater
  ipcMain.handle("update:install", () => { /* no-op */ });
  ipcMain.handle("update:check", () => ({ available: false, version: app.getVersion() }));

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

if (hasElectronRuntime) {
  void bootstrapDesktop().catch((err: unknown) => {
    console.error("Failed to initialize Electron app", err);
    app.exit(1);
  });

  app.on("before-quit", () => {
    _appShuttingDown = true;
  });

  app.on("window-all-closed", () => {
    _appShuttingDown = true;
    stopEngine();
    if (process.platform !== "darwin") app.quit();
  });
}
