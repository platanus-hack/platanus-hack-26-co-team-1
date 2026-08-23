#!/usr/bin/env bash
#
# Publica todo en el repo de la hackaton. Un solo comando, a proposito.
#
#   bash packaging/publicar.sh
#
# El codigo se desarrolla en el repo personal y se sube al de la organizacion
# cuando el equipo decide, no en cada commit. Esto hace las cuatro cosas que
# hay que hacer, en el orden en que hay que hacerlas, para que a la hora de
# presentar nadie tenga que acordarse de una secuencia.
#
# Es idempotente: correrlo dos veces no rompe nada.

set -euo pipefail

ORG="platanus-hack/platanus-hack-26-co-team-1"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

INSTALADOR="dist/Aegis-windows.zip"
MODELO="dist/Aegis-modelo-local.zip"

echo "==> 1/4  Comprobando que no se suba nada a medias"
if [ -n "$(git status --porcelain)" ]; then
  echo "    Hay cambios sin commitear. Commitealos o guardalos antes de publicar."
  git status --short | head -10
  exit 1
fi
if [ ! -f "$INSTALADOR" ]; then
  echo "    Falta $INSTALADOR. Corre:  python packaging/build_windows.py --probar"
  exit 1
fi
echo "    OK: arbol limpio y el instalador existe"

echo "==> 2/4  Subiendo el codigo"
# --force porque el repo de la organizacion quedo en el andamiaje mientras se
# desarrollaba, asi que su historia no es un ancestro de esta.
git push "https://github.com/$ORG.git" HEAD:main --force
echo "    OK: $(git rev-parse --short HEAD)"

echo "==> 3/4  Publicando el instalador"
NOTAS="packaging/notas-release.md"
if gh release view v0.1.0 --repo "$ORG" >/dev/null 2>&1; then
  gh release upload v0.1.0 "$INSTALADOR" --repo "$ORG" --clobber
else
  gh release create v0.1.0 "$INSTALADOR" --repo "$ORG" \
    --title "Aegis 0.1.0 para Windows" \
    ${NOTAS:+--notes-file "$NOTAS"}
fi
echo "    OK: $(du -h "$INSTALADOR" | cut -f1)"

echo "==> 4/4  Publicando el modelo local (opcional)"
# Va aparte del instalador y no adentro: son 880 MB contra 109, y la mayoria de
# la gente quiere probar el producto antes de decidir si le paga esa descarga.
# El agente lo baja cuando la empresa lo prende desde el panel.
if [ -f "$MODELO" ]; then
  gh release upload v0.1.0 "$MODELO" --repo "$ORG" --clobber
  echo "    OK: $(du -h "$MODELO" | cut -f1)"
else
  echo "    (no esta $MODELO, se omite)"
fi

echo
echo "Listo:"
echo "  codigo      https://github.com/$ORG"
echo "  descarga    https://github.com/$ORG/releases/latest"
echo "  panel       https://aegis-panel.onrender.com"
echo
echo "Comprobalo sin credenciales:"
echo "  curl -sIL https://aegis-panel.onrender.com/descargar | head -1"
