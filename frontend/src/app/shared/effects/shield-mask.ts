/**
 * Máscara SVG con la silueta del escudo de Aegis (borde ligeramente
 * desenfocado), compartida por los efectos que necesitan recortar su
 * contenido a esa forma (halftone-shield, shape-blur).
 */
export const SHIELD_MASK =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cfilter id='b'%3E%3CfeGaussianBlur stdDeviation='2.4'/%3E%3C/filter%3E%3Cpath d='M50 4l38 14v29c0 25-17 43-38 53-21-10-38-28-38-53V18L50 4z' fill='white' filter='url(%23b)'/%3E%3C/svg%3E\")";
