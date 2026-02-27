import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/renderer/index.html", "./src/renderer/src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#1a1a1a",
          light: "#3b3b3b",
          dark: "#0a0a0a",
          glow: "rgba(0,0,0,0.06)",
        },
        accent: {
          DEFAULT: "#0d0d0d",
          muted: "#6b6b6b",
        },
        base: "#0a0a0a",
        surface: "#f5f5f4",
        card: "#ffffff",
        elevated: "#ffffff",
        muted: "#8b8b8b",
        border: {
          DEFAULT: "rgba(0,0,0,0.08)",
          strong: "rgba(0,0,0,0.14)",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "SF Pro Text",
          "system-ui",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "SF Mono",
          "Menlo",
          "ui-monospace",
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],       // 11px
        xs: ["0.75rem", { lineHeight: "1.125rem" }],         // 12px
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],        // 13px
        base: ["0.875rem", { lineHeight: "1.375rem" }],      // 14px
        lg: ["0.9375rem", { lineHeight: "1.5rem" }],         // 15px
        xl: ["1.0625rem", { lineHeight: "1.625rem" }],       // 17px
        "2xl": ["1.25rem", { lineHeight: "1.75rem" }],       // 20px
        "3xl": ["1.5rem", { lineHeight: "2rem" }],           // 24px
      },
      borderRadius: {
        "4xl": "2rem",
      },
      boxShadow: {
        soft: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)",
        card: "0 2px 8px rgba(0,0,0,0.04), 0 0 1px rgba(0,0,0,0.06)",
        elevated: "0 8px 24px rgba(0,0,0,0.06), 0 0 1px rgba(0,0,0,0.08)",
        input: "0 2px 6px rgba(0,0,0,0.03)",
        "input-focus": "0 0 0 3px rgba(0,0,0,0.06)",
      },
      keyframes: {
        fadeup: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateX(-6px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        spin: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
      },
      animation: {
        fadeup: "fadeup 280ms ease both",
        "slide-in": "slide-in 220ms ease both",
        "fade-in": "fade-in 200ms ease both",
        spin: "spin 1s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
