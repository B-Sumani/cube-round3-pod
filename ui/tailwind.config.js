/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cream: "var(--cream)",
        teal: "var(--teal)",
        peach: "var(--peach)",
        mustard: "var(--mustard)",
        charcoal: "var(--charcoal)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        card: "var(--card)",
        verdict: {
          pass: "var(--verdict-pass)",
          fail: "var(--verdict-fail)",
          uncertain: "var(--verdict-uncertain)",
        },
      },
      fontFamily: {
        serif: ['"Young Serif"', '"DM Serif Display"', "Georgia", "serif"],
        sans: ['"DM Sans"', "Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        hard: "4px 4px 0 var(--ink)",
        "hard-sm": "2px 2px 0 var(--ink)",
        "hard-lg": "6px 6px 0 var(--ink)",
        "hard-fail": "4px 4px 0 #D64545",
      },
      borderRadius: {
        card: "14px",
      },
    },
  },
  plugins: [],
}
