/* ------------------------------------------------------------------ */
/*  AuthScreen — dark themed sign-in / sign-up                         */
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
    <div className="flex min-h-screen items-center justify-center p-6" style={{ background: "#0f172a" }}>
      <section className="card w-full max-w-sm text-center animate-fadeup">
        {/* Logo */}
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl text-2xl font-bold text-white shadow-lg bg-brand">
          R
        </div>
        <h1 className="text-xl font-bold text-slate-100">Welcome to Rigovo</h1>
        <p className="mt-1.5 text-sm text-slate-400">Your virtual engineering team.</p>

        {waiting ? (
          <div className="mt-8 space-y-3">
            <div className="mx-auto h-9 w-9 animate-spin rounded-full border-[3px] border-slate-700 border-t-brand" />
            <p className="text-sm text-slate-400">Completing sign-in in your browser...</p>
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

        {message && <p className="mt-4 text-sm text-rose-400">{message}</p>}

        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-slate-500">
          <span className={`h-2 w-2 rounded-full ${
            apiStatus === null ? "bg-slate-600" : apiStatus ? "bg-emerald-500" : "bg-rose-400"
          }`} />
          {apiStatus === null ? "Checking..." : apiStatus ? "Connected" : "API unreachable"}
        </div>
      </section>
    </div>
  );
}
