import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { join, relative } from "node:path";
import { ChildProcess, spawn } from "node:child_process";
import { readdirSync, statSync } from "node:fs";

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
  if (projectDir) {
    const candidate = String(projectDir).trim();
    try {
      const stats = statSync(candidate);
      if (stats.isDirectory()) {
        safeProjectDir = candidate;
      }
    } catch {
      safeProjectDir = undefined;
    }
  }
  if (safeProjectDir) {
    args.push("--project", safeProjectDir);
  }
  const opts: { cwd?: string } = {};
  if (safeProjectDir) opts.cwd = safeProjectDir;
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

function walkProjectFiles(
  root: string,
  dir: string,
  results: string[],
  depth: number,
  maxDepth: number,
  maxFiles: number,
): void {
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
      walkProjectFiles(root, fullPath, results, depth + 1, maxDepth, maxFiles);
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

  // Open URL in system browser (for WorkOS AuthKit redirect flow)
  ipcMain.handle("shell:open-external", (_event, url: string) => {
    if (!isSafeExternalUrl(url)) {
      throw new Error("Blocked unsafe external URL");
    }
    return shell.openExternal(url);
  });

  // List files in a project directory (for @ mention autocomplete)
  ipcMain.handle("fs:list-project-files", (_event, projectPath: string) => {
    try {
      const stats = statSync(projectPath);
      if (!stats.isDirectory()) return [];
      const results: string[] = [];
      walkProjectFiles(projectPath, projectPath, results, 0, 5, 800);
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
    return result.filePaths[0];
  });

  // Git clone — shallow-clone a remote repo to a local destination
  ipcMain.handle("git:clone", async (_event, url: string, destDir: string) => {
    return new Promise<string>((resolve, reject) => {
      const stderr: string[] = [];
      const proc = spawn("git", ["clone", "--depth=1", url, destDir], {
        stdio: ["ignore", "ignore", "pipe"],
        detached: false,
      });
      proc.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk.toString("utf8")));
      proc.on("close", (code) => {
        if (code === 0) resolve(destDir);
        else reject(new Error(`git clone failed (code ${code}): ${stderr.join("").trim()}`));
      });
      proc.on("error", reject);
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
    return result.filePaths[0];
  });
}

/* ------------------------------------------------------------------ */
/*  Window                                                            */
/* ------------------------------------------------------------------ */

function createWindow(): void {
  const runtime = runtimeConfig();
  const isDev = Boolean(process.env.ELECTRON_RENDERER_URL);
  const mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    title: "Rigovo Control Plane",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 14, y: 14 },
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: runtime.electronSandbox
    }
  });

  // Open external links in user's browser, not the Electron window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Dev mode → Vite dev server HMR
  // Production → static files from out/renderer/
  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

/* ------------------------------------------------------------------ */
/*  App lifecycle                                                     */
/* ------------------------------------------------------------------ */

async function bootstrapDesktop(): Promise<void> {
  if (!hasElectronRuntime) {
    // eslint-disable-next-line no-console
    console.error("Electron runtime is unavailable in this process.");
    return;
  }
  await app.whenReady();
  registerIpc();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

if (hasElectronRuntime) {
  void bootstrapDesktop().catch((err: unknown) => {
    // eslint-disable-next-line no-console
    console.error("Failed to initialize Electron app", err);
    app.exit(1);
  });

  app.on("window-all-closed", () => {
    // Kill engine subprocess before quitting
    stopEngine();
    if (process.platform !== "darwin") app.quit();
  });
}
