import { contextBridge, ipcRenderer } from "electron";

export interface ElectronAPI {
  engineStatus: () => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  engineRuntimeConfig: () => Promise<{
    electronSandbox: boolean;
    worktreeMode: "project" | "git_worktree";
    worktreeRoot: string;
  }>;
  startEngine: (args: {
    host?: string;
    port?: number;
    projectDir?: string;
  }) => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  stopEngine: () => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  engineLastError: () => Promise<string>;
  openExternal: (url: string) => Promise<void>;
  openFolder: () => Promise<string | null>;
  listProjectFiles: (projectPath: string) => Promise<string[]>;
  gitClone: (url: string, destDir: string) => Promise<string>;
  pickCloneDest: () => Promise<string | null>;
  appVersion: () => Promise<string>;
  defaultWorkspace: () => Promise<string>;
  // Auto-updater stubs (removed — kept for API compatibility)
  checkForUpdate: () => Promise<{ available: boolean; version: string }>;
  installUpdate: () => Promise<void>;
  onUpdateAvailable: (callback: (info: { version: string; releaseDate?: string }) => void) => void;
  onUpdateDownloaded: (callback: (info: { version: string }) => void) => void;
}

const api: ElectronAPI = {
  engineStatus: () => ipcRenderer.invoke("engine:status"),
  engineRuntimeConfig: () => ipcRenderer.invoke("engine:runtime-config"),
  startEngine: (args) => ipcRenderer.invoke("engine:start", args),
  stopEngine: () => ipcRenderer.invoke("engine:stop"),
  engineLastError: () => ipcRenderer.invoke("engine:last-error"),
  openExternal: (url: string) => ipcRenderer.invoke("shell:open-external", url),
  openFolder: () => ipcRenderer.invoke("dialog:open-folder"),
  listProjectFiles: (projectPath: string) => ipcRenderer.invoke("fs:list-project-files", projectPath),
  gitClone: (url: string, destDir: string) => ipcRenderer.invoke("git:clone", url, destDir),
  pickCloneDest: () => ipcRenderer.invoke("dialog:pick-clone-dest"),
  appVersion: () => ipcRenderer.invoke("app:version"),
  defaultWorkspace: () => ipcRenderer.invoke("app:defaultWorkspace"),
  checkForUpdate: () => ipcRenderer.invoke("update:check"),
  installUpdate: () => ipcRenderer.invoke("update:install"),
  onUpdateAvailable: (callback) => ipcRenderer.on("update:available", (_e, info) => callback(info)),
  onUpdateDownloaded: (callback) => ipcRenderer.on("update:downloaded", (_e, info) => callback(info)),
};

contextBridge.exposeInMainWorld("electronAPI", Object.freeze(api));
