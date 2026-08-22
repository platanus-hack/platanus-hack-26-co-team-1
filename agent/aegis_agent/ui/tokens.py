"""El sistema de diseno de Aegis, en un solo lugar.

Las superficies de Aegis no viven todas en el mismo stack: el front principal es
Angular con Tailwind, y la pagina de bloqueo y el panel son HTML que arma
Python, porque tienen que funcionar sin build, sin red y dentro de un proxy.

Eso no puede significar dos sistemas de diseno. Cuando cada superficie eligio su
propia paleta, el resultado fue que la persona veia una marca en la landing y
otra distinta en el momento que mas importa: cuando algo se bloquea. La pagina
de bloqueo llego a ser gris oscura mientras el producto era claro y calido.

Asi que esto es el espejo de `frontend/tailwind.config.js`. **Si un color cambia
alla, cambia aca.** Los nombres son los mismos a proposito, para que la
correspondencia se pueda revisar de un vistazo.
"""

from __future__ import annotations

# Espejo exacto de theme.extend.colors.aegis en tailwind.config.js
BG = "#f8f6f1"
SURFACE = "#ffffff"
SURFACE2 = "#f2f0ea"
SURFACE3 = "#e9e6dd"
BORDER = "#e2ded2"
BORDERLIGHT = "#cfc9b8"
TEXT = "#22221d"
DIM = "#66645a"
FAINT = "#96927f"
ACCENT = "#0e5fa8"
ACCENTDEEP = "#0a4879"
AMBER = "#a8710a"
HIGHLIGHT = "#ffcf3d"
RED = "#c93a4c"
GREEN = "#177a52"

# theme.extend.boxShadow.panel
SOMBRA_PANEL = "0 0 0 1px rgba(34,34,29,0.05), 0 2px 6px rgba(34,34,29,0.05)"

# Switzer se sirve desde el front y aca no esta disponible: la pagina de bloqueo
# tiene que renderizar sin red, dentro de un proxy que acaba de cortar una
# conexion. Inter cubre los dos roles y el stack degrada al sistema.
FUENTE = (
    "'Inter','Segoe UI',system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif"
)
FUENTE_MONO = "ui-monospace,'Cascadia Mono',Consolas,'SF Mono',monospace"

# Base compartida: lo que en el front son `body`, los titulos y las clases
# .aegis-card / .aegis-label. Se repite el minimo indispensable para que las dos
# paginas se vean iguales sin arrastrar Tailwind.
BASE_CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;background:{BG};color:{TEXT};
font-family:{FUENTE};letter-spacing:-0.011em;
-webkit-font-smoothing:antialiased}}
h1,h2,h3{{letter-spacing:-0.02em;font-weight:600;margin:0}}
a{{color:{ACCENT};text-decoration:none}}
a:hover{{color:{ACCENTDEEP}}}
.aegis-card{{background:{SURFACE};border:1px solid {BORDER};
border-radius:16px;box-shadow:{SOMBRA_PANEL}}}
.aegis-label{{font-size:11px;font-weight:500;text-transform:uppercase;
letter-spacing:0.13em;color:{FAINT}}}
::selection{{background:rgba(14,95,168,0.16);color:{TEXT}}}
::-webkit-scrollbar{{width:10px;height:10px}}
::-webkit-scrollbar-track{{background:{BG}}}
::-webkit-scrollbar-thumb{{background:#ddd8c9;border-radius:999px}}
::-webkit-scrollbar-thumb:hover{{background:{BORDERLIGHT}}}
"""

# El escudo de la marca, el mismo trazo que usa el front.
ESCUDO_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3 4.5 6v5.5c0 4.5 3.2 8.3 7.5 9.5 4.3-1.2 7.5-5 7.5-9.5V6L12 3Z"></path>'
    '<path d="m9.2 12 2 2 3.6-3.8"></path></svg>'
)
