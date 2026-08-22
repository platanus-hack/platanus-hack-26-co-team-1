/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,ts}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'sans-serif'],
        display: ['Switzer', 'Inter', 'ui-sans-serif', 'sans-serif'],
      },
      colors: {
        aegis: {
          bg: '#f8f6f1',
          surface: '#ffffff',
          surface2: '#f2f0ea',
          surface3: '#e9e6dd',
          border: '#e2ded2',
          borderlight: '#cfc9b8',
          text: '#22221d',
          dim: '#66645a',
          faint: '#96927f',
          accent: '#0e5fa8',
          accentdeep: '#0a4879',
          amber: '#a8710a',
          highlight: '#ffcf3d',
          red: '#c93a4c',
          green: '#177a52',
        },
      },
      boxShadow: {
        panel: '0 0 0 1px rgba(34,34,29,0.05), 0 2px 6px rgba(34,34,29,0.05)',
        glow: '0 0 0 8px rgba(14,95,168,0.08), 0 24px 48px -16px rgba(14,95,168,0.45)',
      },
      keyframes: {
        pulseGlow: {
          '0%, 100%': { opacity: 0.5 },
          '50%': { opacity: 0.85 },
        },
        riseIn: {
          '0%': { opacity: 0, transform: 'translateY(14px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
      },
      animation: {
        pulseGlow: 'pulseGlow 7s ease-in-out infinite',
        riseIn: 'riseIn 0.6s cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
};
