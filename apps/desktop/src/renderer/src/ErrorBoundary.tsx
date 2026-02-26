import React from "react";

type Props = {
  children: React.ReactNode;
};

type State = {
  hasError: boolean;
  message: string;
};

export class ErrorBoundary extends React.Component<Props, State> {
  public constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || "Unknown UI error" };
  }

  public componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Keep logs in devtools/tauri console for diagnosis.
    // eslint-disable-next-line no-console
    console.error("Rigovo desktop UI crashed", error, info);
  }

  public render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-50 px-6 py-10 text-slate-900">
          <div className="mx-auto max-w-2xl rounded-xl border border-rose-200 bg-white p-6 shadow">
            <p className="font-mono text-xs uppercase tracking-wider text-rose-700">UI Recovery Mode</p>
            <h1 className="mt-2 text-2xl font-semibold">Desktop app hit a runtime error</h1>
            <p className="mt-2 text-sm text-slate-600">{this.state.message}</p>
            <button
              type="button"
              className="mt-4 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
              onClick={() => window.location.reload()}
            >
              Reload App
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
