/* ------------------------------------------------------------------ */
/*  AuthScreen — light themed sign-in / sign-up                        */
/* ------------------------------------------------------------------ */
interface AuthScreenProps {
  onSignIn: () => void;
  onSignUp: () => void;
  waiting: boolean;
  onCancel: () => void;
  message: string;
  apiStatus: boolean | null;
}

export default function AuthScreen({ onSignIn, onSignUp, waiting, onCancel, message, apiStatus }: AuthScreenProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6" style={{ background: "var(--ui-bg)" }}>
      <section className="card w-full max-w-sm text-center animate-fadeup">
        {/* Logo */}
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl text-2xl font-bold text-white shadow-lg" style={{ background: "var(--ui-text)" }}>
          R
        </div>
        <h1 className="text-xl font-bold text-[var(--ui-text)]">Welcome to Rigovo</h1>
        <p className="mt-1.5 text-sm text-[var(--ui-text-muted)]">Your virtual engineering team.</p>

        {waiting ? (
          <div className="mt-8 space-y-3">
            <div className="mx-auto h-9 w-9 animate-spin rounded-full border-[3px] border-[var(--ui-border)] border-t-[var(--ui-text)]" />
            <p className="text-sm text-[var(--ui-text-muted)]">Completing sign-in in your browser...</p>
            <button type="button" className="ghost-btn text-xs" onClick={onCancel}>Cancel</button>
          </div>
        ) : (
          <div className="mt-8 flex flex-col gap-3">
            <button type="button" className="primary-btn w-full py-3 text-base" onClick={onSignIn}>
              Sign in
            </button>
            <button type="button" className="ghost-btn w-full" onClick={onSignUp}>
              Create account
            </button>
          </div>
        )}

        {message && <p className="mt-4 text-sm text-rose-600">{message}</p>}

        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-[var(--ui-text-muted)]">
          <span className={`h-2 w-2 rounded-full ${
            apiStatus === null ? "bg-[var(--ui-text-subtle)]" : apiStatus ? "bg-emerald-500" : "bg-rose-500"
          }`} />
          {apiStatus === null ? "Checking..." : apiStatus ? "Connected" : "API unreachable"}
        </div>
      </section>
    </div>
  );
}
