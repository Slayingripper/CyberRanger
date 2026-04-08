/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: 'var(--bg-primary)',
        surface: 'var(--bg-secondary)',
        surfaceHover: 'var(--bg-tertiary)',
        primary: 'var(--text-primary)',
        secondary: 'var(--text-secondary)',
        accent: 'var(--accent-primary)',
        accentHover: 'var(--accent-hover)',
        border: 'var(--border-color)',
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
