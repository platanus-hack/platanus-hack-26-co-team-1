"""Lo que la suite tiene que apagar antes de importar cualquier test.

Va aca --y no en `aislamiento.py`-- porque este archivo se ejecuta al importar
el paquete, o sea SIEMPRE, incluso cuando alguien corre un solo test con
`python -m unittest tests.test_x`. Un helper que hay que acordarse de llamar
protege solo a los tests que se acordaron.

`AEGIS_AVISO`: el aviso del sistema lanza un PowerShell suelto por cada bloqueo.
Sin esto, correr la suite le llena la pantalla de notificaciones a quien la
corre, y los tests que pasan por `_deny` --que son varios-- lo disparan cada uno.
"""

import os

os.environ.setdefault("AEGIS_AVISO", "0")
