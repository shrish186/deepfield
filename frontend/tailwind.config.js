/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        ink: {
          950: "#06070b",
          900: "#0a0c12",
          800: "#0f121a",
          700: "#161a24",
          600: "#1e2330",
        },
        accent: {
          DEFAULT: "#7c6cff",
          glow: "#a78bfa",
          cyan: "#38e8ff",
        },
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(124,108,255,0.25), 0 8px 40px -8px rgba(124,108,255,0.45)",
        "glow-cyan": "0 0 40px -10px rgba(56,232,255,0.5)",
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 20px 60px -30px rgba(0,0,0,0.8)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        shimmer: {
          "0%": { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "200% 50%" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-10px)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out both",
        "fade-in": "fade-in 0.6s ease-out both",
        shimmer: "shimmer 6s linear infinite",
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
        float: "float 8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
