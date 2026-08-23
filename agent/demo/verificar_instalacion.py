"""Comprueba la instalacion con el Chrome del sistema.

Sin argumento de proxy (lo toma del registro) y sin ignore_https_errors: si la
pagina carga, es porque la CA quedo bien confiada y el proxy esta en medio.
"""

from playwright.sync_api import sync_playwright

CASOS = [
    ("https://chatgpt.com/", "bloqueado", "no esta aprobado"),
    ("https://gemini.google.com/", "bloqueado", "no esta aprobado"),
    ("https://example.com/", "permitido", "Example Domain"),
]

with sync_playwright() as p:
    navegador = p.chromium.launch(channel="chrome", headless=True)
    pagina = navegador.new_context().new_page()
    for url, esperado, marca in CASOS:
        try:
            pagina.goto(url, wait_until="domcontentloaded", timeout=25000)
            ok = marca in pagina.content()
            print(f"{url:35} {esperado:10} -> {'OK' if ok else 'FALLO'}")
        except Exception as error:
            print(f"{url:35} {esperado:10} -> ERROR {type(error).__name__}: {str(error)[:90]}")
    navegador.close()
