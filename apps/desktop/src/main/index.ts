import { app, BrowserWindow, dialog, ipcMain, nativeImage, shell } from "electron";
import { join, resolve, relative } from "node:path";
import { ChildProcess, execSync, spawn } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";

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
    // Validate that the selected path is actually a directory
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
      // Validate inputs
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
    // Validate that the selected path is a directory
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

  // Resolve icon path — works in both dev (source tree) and production (resources)
  // On macOS, BrowserWindow `icon` is ignored for the dock — must use app.dock.setIcon()
  // IMPORTANT: .icns files often fail with nativeImage.createFromPath() (returns empty),
  // so we always prefer .png for the dock icon on macOS. .icns is only used as a last resort.
  const iconPath = (() => {
    // Prefer .png on macOS (nativeImage reads it reliably); .icns often loads as empty.
    // On Windows use .ico, on Linux use .png.
    const baseDirs = [
      join(__dirname, "../../resources"),
      join(app.getAppPath(), "resources"),
      resolve(process.cwd(), "resources"),
    ];
    const candidates: string[] = [];
    for (const dir of baseDirs) {
      // Always try .png first — it works reliably on all platforms with nativeImage
      candidates.push(join(dir, "icon.png"));
      if (process.platform === "win32") {
        candidates.push(join(dir, "icon.ico"));
      }
      // .icns as last resort (electron-builder uses it for DMG, but nativeImage often can't read it)
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

  // macOS dock icon — must be set explicitly (BrowserWindow icon doesn't affect dock)
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
/*  Port cleanup — free stale ports before starting                   */
/* ------------------------------------------------------------------ */

function killPort(port: number): void {
  // Sanitise port to a strict integer to prevent command injection
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
      // Use spawn-safe approach: get PIDs first, then kill individually
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
    // eslint-disable-next-line no-console
    console.error("Electron runtime is unavailable in this process.");
    return;
  }

  const isDev = Boolean(process.env.ELECTRON_RENDERER_URL);

  // In production: free port 8787 if occupied by a stale process from a previous run.
  // In dev mode: skip — the e2e script manages the API process externally; killing
  // it here would cause demo-mode fallback in the renderer (API unreachable).
  if (!isDev) {
    killPort(8787);
  }

  // Set app name before anything else — this controls the macOS dock tooltip
  // and the app menu title.  In production electron-builder sets it from
  // package.json productName, but in dev mode Electron defaults to "Electron".
  app.setName("Rigovo Virtual Team");

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
