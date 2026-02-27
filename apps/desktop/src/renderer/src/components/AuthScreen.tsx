/* ------------------------------------------------------------------ */
/*  AuthScreen — Rigovo sign-in/sign-up, Warm Ink theme               */
/* ------------------------------------------------------------------ */

/** Rigovo brand mark — target/crosshair with checkmark, dark navy bg.
 *  Recreated as inline SVG from the official app icon.
 */
function RigovoLogo({ size = 64 }: { size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Rigovo logo"
      role="img"
    >
      {/* Dark navy rounded background */}
      <rect width="64" height="64" rx="16" fill="#0D1117" />

      {/* Outer ring */}
      <circle cx="32" cy="32" r="20" stroke="#3B82F6" strokeWidth="1.5" opacity="0.7" />

      {/* Inner filled circle (blue gradient) */}
      <circle cx="32" cy="32" r="12" fill="url(#rg-grad)" />

      {/* Center checkmark circle */}
      <circle cx="32" cy="32" r="7" fill="#1D4ED8" />

      {/* Checkmark */}
      <path
        d="M27.5 32.5l3 3 6-6"
        stroke="#FFFFFF"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Crosshair notches — top */}
      <line x1="32" y1="8"  x2="32" y2="12" stroke="#3B82F6" strokeWidth="1.5" strokeLinecap="round" />
      {/* bottom */}
      <line x1="32" y1="52" x2="32" y2="56" stroke="#3B82F6" strokeWidth="1.5" strokeLinecap="round" />
      {/* left */}
      <line x1="8"  y1="32" x2="12" y2="32" stroke="#3B82F6" strokeWidth="1.5" strokeLinecap="round" />
      {/* right */}
      <line x1="52" y1="32" x2="56" y2="32" stroke="#3B82F6" strokeWidth="1.5" strokeLinecap="round" />

      {/* Gap lines to ring — inner crosshair guides */}
      <line x1="32" y1="14" x2="32" y2="18" stroke="#3B82F6" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      <line x1="32" y1="46" x2="32" y2="50" stroke="#3B82F6" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      <line x1="14" y1="32" x2="18" y2="32" stroke="#3B82F6" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      <line x1="46" y1="32" x2="50" y2="32" stroke="#3B82F6" strokeWidth="1" strokeLinecap="round" opacity="0.5" />

      <defs>
        <radialGradient id="rg-grad" cx="50%" cy="38%" r="60%" fx="50%" fy="38%">
          <stop offset="0%"   stopColor="#60A5FA" />
          <stop offset="100%" stopColor="#1E40AF" />
        </radialGradient>
      </defs>
    </svg>
  );
}

interface AuthScreenProps {
  onSignIn: () => void;
  onSignUp: () => void;
  waiting: boolean;
  onCancel: () => void;
  message: string;
  apiStatus: boolean | null;
}

export default function AuthScreen({
  onSignIn,
  onSignUp,
  waiting,
  onCancel,
  message,
  apiStatus,
}: AuthScreenProps) {
  const statusClass =
    apiStatus === null ? "checking" : apiStatus ? "connected" : "disconnected";
  const statusLabel =
    apiStatus === null ? "Checking connection…" : apiStatus ? "Connected" : "API unreachable";

  return (
    <div className="auth-screen">
      <div className="auth-card">
        {/* Logo */}
        <div className="auth-logo">
          <div className="auth-logo-icon">
            <RigovoLogo size={64} />
          </div>
        </div>

        <h1 className="auth-title">Welcome to Rigovo</h1>
        <p className="auth-subtitle">
          Your virtual engineering team.<br />
          Sign in to start working with your agents.
        </p>

        {waiting ? (
          /* Waiting for browser OAuth redirect */
          <div className="auth-waiting">
            {message ? (
              /* Auth failed or timed out — show error with retry */
              <>
                <div className="auth-error" role="alert" style={{ marginBottom: 16 }}>
                  {message}
                </div>
                <button type="button" className="auth-primary-btn" onClick={() => { onCancel(); }}>
                  Try again
                </button>
              </>
            ) : (
              <>
                <div className="auth-waiting-spinner" aria-label="Loading" />
                <p className="auth-waiting-text">
                  Completing sign-in in your browser…<br />
                  Switch back here once you&apos;re done.
                </p>
                <button type="button" className="auth-cancel-btn" onClick={onCancel}>
                  Cancel
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="auth-actions">
            <button
              type="button"
              className="auth-primary-btn"
              onClick={onSignIn}
              aria-label="Sign in to Rigovo"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="15" height="15" aria-hidden="true">
                <path d="M10 3h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3" />
                <path d="M7 11l4-3-4-3" />
                <path d="M11 8H3" />
              </svg>
              Sign in
            </button>

            <div className="auth-divider">or</div>

            <button
              type="button"
              className="auth-secondary-btn"
              onClick={onSignUp}
              aria-label="Create a Rigovo account"
            >
              Create account
            </button>
          </div>
        )}

        {/* Error message — only shown when NOT in waiting state (waiting state handles its own errors) */}
        {!waiting && message && (
          <div className="auth-error" role="alert">
            {message}
          </div>
        )}

        {/* Connection status */}
        <div className="auth-status">
          <span className={`auth-status-dot ${statusClass}`} aria-hidden="true" />
          <span>{statusLabel}</span>
        </div>
      </div>
    </div>
  );
}
