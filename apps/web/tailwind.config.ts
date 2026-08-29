import type { Config } from "tailwindcss";

// Palette de centre de commandement : sobre, contrastee, lisible en projection.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: { DEFAULT: "#0a0e14", panel: "#111721", raised: "#18202c" },
        edge: "#232d3d",
        ink: { DEFAULT: "#e6edf7", muted: "#8b9bb4", dim: "#5a6b84" },
        state: {
          healthy: "#3fb950",
          executing: "#58a6ff",
          risk: "#f0a020",
          recovering: "#a371f7",
          blocked: "#f85149",
          failed: "#f85149",
          completed: "#3fb950",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      animation: { pulseSoft: "pulseSoft 2s ease-in-out infinite" },
      keyframes: {
        pulseSoft: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
      },
    },
  },
  plugins: [],
};

export default config;
