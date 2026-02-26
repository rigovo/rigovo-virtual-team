# Rigovo Desktop (Tauri)

UI-first control plane for Rigovo virtual teams.

## What it provides

- Task ingestion inbox (plugin-driven)
- Approval queue for autonomy gates
- Cross-team workforce matrix (Team A/B/C role mapping)
- Live event stream and execution spotlight

## Run locally

1. Install dependencies:

```bash
cd apps/desktop
pnpm install
```

2. Install Rust toolchain (required by Tauri):

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source \"$HOME/.cargo/env\"
```

3. Start UI only:

```bash
pnpm dev
```

4. Start full desktop shell:

```bash
pnpm tauri dev
```

The UI polls these endpoints by default:

- `GET http://127.0.0.1:8787/v1/ui/inbox`
- `GET http://127.0.0.1:8787/v1/ui/approvals`
- `GET http://127.0.0.1:8787/v1/ui/workforce`
- `GET http://127.0.0.1:8787/v1/ui/events`

Override with:

```bash
VITE_RIGOVO_API=http://127.0.0.1:8787 pnpm dev
```

If API is unavailable, the UI automatically falls back to demo telemetry data.
