import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/renderer/index.html", "./src/renderer/src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#4f46e5",
          light: "#6366f1",
          dark: "#4338ca",
          glow: "rgba(79,70,229,0.15)",
        },
        base: "#0f172a",
        surface: "#1e293b",
        card: "#273549",
        elevated: "#334155",
        muted: "#94a3b8",
      },
      fontFamily: {
        sans: [
          "Inter", "SF Pro Display", "SF Pro Text",
          "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"
        ],
        mono: [
          "JetBrains Mono", "SF Mono", "Menlo", "ui-monospace", "monospace"
        ]
      },
      keyframes: {
        fadeup: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateX(-8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" }
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(79,70,229,0)" },
          "50%": { boxShadow: "0 0 12px 4px rgba(79,70,229,0.25)" }
        },
        "typing-bounce": {
          "0%, 80%, 100%": { transform: "translateY(0)" },
          "40%": { transform: "translateY(-4px)" }
        },
        "border-pulse": {
          "0%, 100%": { borderColor: "rgba(255,255,255,0.05)" },
          "50%": { borderColor: "rgba(79,70,229,0.3)" }
        },
        "glow-enter": {
          "0%": { boxShadow: "0 0 20px 8px rgba(79,70,229,0.3)" },
          "100%": { boxShadow: "0 0 0 0 rgba(79,70,229,0)" }
        },
        spin: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" }
        }
      },
      animation: {
        fadeup: "fadeup 340ms ease both",
        "slide-in": "slide-in 280ms ease both",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "typing-1": "typing-bounce 1.2s ease-in-out infinite",
        "typing-2": "typing-bounce 1.2s ease-in-out 0.15s infinite",
        "typing-3": "typing-bounce 1.2s ease-in-out 0.3s infinite",
        "border-pulse": "border-pulse 2s ease-in-out infinite",
        "glow-enter": "glow-enter 600ms ease-out both",
        spin: "spin 1s linear infinite"
      }
    }
  },
  plugins: []
};

export default config;
