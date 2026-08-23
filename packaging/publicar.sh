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

# El COMPLETO y no el liviano: es el unico que se publica.
#
# El liviano se retiro porque no ve los datos de empresa -lo que no tiene forma
# de credencial-, que es justo lo que el producto promete cuidar. Quien lo
# probaba no se enteraba de que estaba a medias: bloquea claves y pasa por alto
# "el margen con Alpina quedo en 4%". Ofrecer los dos era ofrecer una version
# que falla en silencio, y la mayoria elige por peso.
#
# El modelo tampoco se publica aparte: viaja adentro (ver 4/4).
INSTALADOR="dist/Aegis-windows-completo.zip"

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

echo "==> 4/4  Comprobando que lo que se subio traiga el modelo"
# El modelo ya NO va aparte: viaja adentro del instalador. Iba separado cuando
# habia dos paquetes, y el liviano se retiro porque no ve los datos de empresa
# --lo que no tiene forma de credencial-- que es justo lo que el producto
# promete cuidar. Quien probaba el liviano no se enteraba de que estaba a medias.
#
# Lo que queda aca es la comprobacion, no la subida: un instalador de ~110 MB
# es el liviano compilado por error, y publicarlo se ve exactamente igual que
# publicar el bueno hasta que alguien lo instala y no lo protege.
_bytes=$(wc -c < "$INSTALADOR")
if [ "$_bytes" -lt 500000000 ]; then
  echo "    ATENCION: $INSTALADOR pesa $(du -h "$INSTALADOR" | cut -f1)."
  echo "    Eso es el paquete SIN modelo. Recompila sin AEGIS_COMPLETO=0:"
  echo "        python packaging/build_windows.py --probar"
  exit 1
fi
echo "    OK: $(du -h "$INSTALADOR" | cut -f1), con el modelo adentro"

echo
echo "Listo:"
echo "  codigo      https://github.com/$ORG"
echo "  descarga    https://github.com/$ORG/releases/latest"
echo "  panel       https://aegis-panel.onrender.com"
echo
echo "Comprobalo sin credenciales:"
echo "  curl -sIL https://aegis-panel.onrender.com/descargar | head -1"
