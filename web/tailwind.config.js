/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Soehne",
          "Avenir Next",
          "Helvetica Neue",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Arial",
          "sans-serif"
        ],
        serif: [
          "Tiempos Text",
          "Iowan Old Style",
          "Times New Roman",
          "serif"
        ]
      }
    }
  },
  plugins: []
};
