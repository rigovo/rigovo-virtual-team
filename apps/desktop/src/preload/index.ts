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
  /** Open a folder picker. Returns the absolute path of the selected folder, or null if cancelled. */
  openFolder: () => Promise<string | null>;
  listProjectFiles: (projectPath: string) => Promise<string[]>;
  /** Shallow-clone a git repo to destDir. Resolves with the absolute destination path on success. */
  gitClone: (url: string, destDir: string) => Promise<string>;
  /** Open a folder picker for choosing clone destination parent. Returns the absolute path or null if cancelled. */
  pickCloneDest: () => Promise<string | null>;
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
};

contextBridge.exposeInMainWorld("electronAPI", Object.freeze(api));
