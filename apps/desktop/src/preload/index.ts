import { contextBridge, ipcRenderer } from "electron";

export interface ElectronAPI {
  engineStatus: () => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  startEngine: (args: {
    host?: string;
    port?: number;
    projectDir?: string;
    rigovoBin?: string;
  }) => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  stopEngine: () => Promise<{ running: boolean; pid: number | null; apiUrl: string }>;
  openExternal: (url: string) => Promise<void>;
  openFolder: () => Promise<string | null>;
}

const api: ElectronAPI = {
  engineStatus: () => ipcRenderer.invoke("engine:status"),
  startEngine: (args) => ipcRenderer.invoke("engine:start", args),
  stopEngine: () => ipcRenderer.invoke("engine:stop"),
  openExternal: (url: string) => ipcRenderer.invoke("shell:open-external", url),
  openFolder: () => ipcRenderer.invoke("dialog:open-folder"),
};

contextBridge.exposeInMainWorld("electronAPI", api);
