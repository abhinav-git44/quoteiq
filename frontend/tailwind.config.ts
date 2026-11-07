import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#0B1426", 900: "#13203A", 800: "#1E2A4A", 700: "#2B3A61", 600: "#3D4F7C" },
        ink: "#13203A",
        accent: { DEFAULT: "#4F5BD5", soft: "#EEF0FD" },
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"] },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
    },
  },
  plugins: [],
} satisfies Config;
