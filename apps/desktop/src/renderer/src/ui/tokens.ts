export const UI_LABELS = {
  runtimeLocal: "Local",
  runtimeCloud: "Cloud",
  defaultPermissions: "Default permissions",
  defaultEffort: "Standard",
} as const;

export type WorkspaceControls = {
  runtime: string;
  permissions: string;
  model: string;
  effort: string;
};

export function buildPermissionLabel(minTrustLevel?: string): string {
  if (!minTrustLevel) {
    return UI_LABELS.defaultPermissions;
  }
  return `${UI_LABELS.defaultPermissions} (${minTrustLevel})`;
}

