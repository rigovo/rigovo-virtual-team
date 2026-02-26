import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { join } from "node:path";
import { ChildProcess, spawn } from "node:child_process";
import { is } from "@electron-toolkit/utils";

/* ------------------------------------------------------------------ */
/*  Engine lifecycle – same semantics as the old Tauri Rust backend   */
/* ------------------------------------------------------------------ */

let engineProcess: ChildProcess | null = null;

interface EngineStatus {
  running: boolean;
  pid: number | null;
  apiUrl: string;
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
  projectDir?: string,
  rigovoBin = "rigovo"
): EngineStatus {
  const status = engineStatus(host, port);
  if (status.running) return status;

  const args = ["serve", "--host", host, "--port", String(port)];
  const opts: { cwd?: string } = {};
  if (projectDir) opts.cwd = projectDir;

  engineProcess = spawn(rigovoBin, args, {
    ...opts,
    stdio: "ignore",
    detached: false
  });

  engineProcess.on("error", () => {
    engineProcess = null;
  });
  engineProcess.on("exit", () => {
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
/*  IPC handlers                                                      */
/* ------------------------------------------------------------------ */

function registerIpc(): void {
  ipcMain.handle("engine:status", () => engineStatus());

  ipcMain.handle(
    "engine:start",
    (_event, args: { host?: string; port?: number; projectDir?: string; rigovoBin?: string }) =>
      startEngine(args.host, args.port, args.projectDir, args.rigovoBin)
  );

  ipcMain.handle("engine:stop", () => stopEngine());

  // Open URL in system browser (for WorkOS AuthKit redirect flow)
  ipcMain.handle("shell:open-external", (_event, url: string) => {
    return shell.openExternal(url);
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
}

/* ------------------------------------------------------------------ */
/*  Window                                                            */
/* ------------------------------------------------------------------ */

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    title: "Rigovo Control Plane",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false
    }
  });

  // Open external links in user's browser, not the Electron window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Dev mode → Vite dev server HMR
  // Production → static files from out/renderer/
  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

/* ------------------------------------------------------------------ */
/*  App lifecycle                                                     */
/* ------------------------------------------------------------------ */

app.whenReady().then(() => {
  registerIpc();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  // Kill engine subprocess before quitting
  stopEngine();
  if (process.platform !== "darwin") app.quit();
});
