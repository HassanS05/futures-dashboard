import type { Config } from "tailwindcss";

/**
 * HR5 Invest design system.
 * Dark-first, deep navy canvas, electric-cyan/violet accents, financial
 * green/red semantics. Tuned for a premium "trading terminal" feel.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#070A12", // app background
        surface: "#0E1320", // cards
        "surface-2": "#151B2C", // elevated
        border: "#1E2638",
        muted: "#7A86A1",
        text: "#E6EAF2",
        accent: { DEFAULT: "#3DD7E0", soft: "#1B9CA3" }, // electric cyan
        violet: { DEFAULT: "#8B7BFF", soft: "#5B4FD6" },
        gold: "#E8B765",
        up: "#2FD08A",
        down: "#FF5C72",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 30px -12px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(61,215,224,0.25), 0 0 24px -6px rgba(61,215,224,0.35)",
      },
      backgroundImage: {
        "grid-faint":
          "linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)",
        "accent-grad": "linear-gradient(135deg, #3DD7E0 0%, #8B7BFF 100%)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-soft": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out both",
        shimmer: "shimmer 1.6s infinite",
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
