/** Colores de marca usados como paleta para chips/avatares derivados de un nombre. */
export const PALETA_MARCA = ['#0e5fa8', '#a8710a', '#177a52', '#c93a4c', '#0a4879'];

/** Mismo nombre, mismo color siempre: útil para chips y avatares sin asignación manual. */
export function colorForName(name: string, paleta: readonly string[] = PALETA_MARCA): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return paleta[hash % paleta.length];
}

/** Iniciales (hasta 2) a partir de un nombre o frase, para avatares/chips. */
export function initialsOf(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((parte) => parte[0]?.toUpperCase() ?? '')
    .join('');
}
