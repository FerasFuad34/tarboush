/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        arabic: ['"IBM Plex Sans Arabic"', '"Noto Naskh Arabic"', 'Tahoma', 'sans-serif']
      }
    }
  },
  plugins: []
}
