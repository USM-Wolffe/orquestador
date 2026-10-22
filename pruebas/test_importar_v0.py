"""Tarea 8.2: `orq importar-v0` (spec compatibilidad-v0): simula por defecto, aplica con `--aplicar`, deja el
origen intacto (contenido y fechas) y la sesión importada se retoma. Carpeta v0 sintética."""
from __future__ import annotations

import contextlib
import io
import json
import unittest

from ayudantes import PruebaOrq, foto

import orq as cli

SESION_LOGIN = "11111111-2222-4333-8444-555555555555"


class PruebaImportarV0(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.instalar()
        self.v0 = self.tmp / "puente-v0"
        pendientes = self.v0 / "trabajos" / "pendientes"
        pendientes.mkdir(parents=True)
        (self.v0 / "trabajos" / "hechos").mkdir()
        (self.v0 / "trabajos" / "hechos" / "viejo.md").write_text("respuesta anterior", encoding="utf-8")
        (self.v0 / "registro.log").write_text("2026-10-20T10:00:00-03:00 puente iniciado\n", encoding="utf-8")
        (self.v0 / "sesiones.json").write_text(json.dumps({
            "login": SESION_LOGIN, "otro-repo:pagos": "22222222-3333-4444-8555-666666666666", "Malo": "x"}),
            encoding="utf-8")
        (pendientes / "t1.json").write_text(json.dumps(
            {"id": "t1", "tipo": "cc", "cambio": "login", "prompt": "#guion: ok\nSigue con el login."}),
            encoding="utf-8")
        (pendientes / "t2.json").write_text(json.dumps(
            {"id": "t2", "tipo": "git", "cambio": "login", "acciones": ["commit"], "mensaje": "cambio"}),
            encoding="utf-8")
        self.origen = foto(self.v0)

    def importar(self, *extra):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = cli.main(["importar-v0", "--desde", str(self.v0), "--proyecto", "demo", *extra])
        return codigo, salida.getvalue()

    def test_simulacion(self):
        antes = foto(self.raiz, self.cowork)
        codigo, texto = self.importar()
        self.assertEqual(codigo, 0, texto)
        self.assertIn(f"sesión del cambio login → {SESION_LOGIN}", texto)
        self.assertIn("trabajo t1 (cambio login)", texto)
        self.assertIn("omitido: sesión 'otro-repo:pagos'", texto)
        self.assertIn("omitido: trabajo t2.json", texto)
        self.assertIn("Simulación: no se escribió nada", texto)
        self.assertEqual(foto(self.raiz, self.cowork), antes)
        self.assertEqual(foto(self.v0), self.origen)

    def test_importacion_aplicada_y_sesion_retomada(self):
        codigo, texto = self.importar("--aplicar")
        self.assertEqual(codigo, 0, texto)
        self.assertEqual(foto(self.v0), self.origen, "la carpeta del v0 cambió")
        sesiones = json.loads((self.raiz / "proyectos" / "demo" / "sesiones.json").read_text(encoding="utf-8"))
        self.assertEqual(sesiones, {"login|cc": SESION_LOGIN})
        self.assertTrue((self.cowork / "demo" / "entrada" / "v0-t1.json").exists())
        self.assertFalse((self.cowork / "demo" / "entrada" / "v0-t2.json").exists())
        orq = self.orquestador()
        self.esperar(orq, lambda: self.lanzamientos(), timeout=60, mensaje="t1 lanzada")
        t = self.tarea(orq, "t1")
        self.assertEqual((t["agente"], t["cambio"]), ("cc", "login"))
        argv = self.lanzamientos()[0]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], SESION_LOGIN)
        acuses = [json.loads(r.read_text(encoding="utf-8")) for r in (self.cowork / "demo" / "respuestas").iterdir()]
        self.assertIn("v0", json.dumps(acuses, ensure_ascii=False))
        # "Trabajo v0 corre en el v1": adaptador cc en wt-login y el texto en la salida de Cowork.
        self.esperar(orq, lambda: self.tarea(orq, "t1")["estado"] == "hecha", timeout=60, mensaje="t1 hecha")
        self.assertTrue(self.lanzamientos()[0]["cwd"].replace("\\", "/").endswith("/wt-login"))
        resultado = self.cowork / "demo" / "salida" / "resultados" / "t1.md"
        self.assertEqual(resultado.read_text(encoding="utf-8"), "Listo: edité app.py y las pruebas pasan.")

    def test_no_aplica_con_orq_correr_andando(self):
        self.orquestador()  # toma el candado de la raíz de estado
        antes = foto(self.raiz / "proyectos" / "demo", self.cowork / "demo" / "entrada")
        codigo, texto = self.importar("--aplicar")
        self.assertEqual(codigo, 1)
        self.assertIn("error", texto)
        self.assertEqual(foto(self.raiz / "proyectos" / "demo", self.cowork / "demo" / "entrada"), antes)


if __name__ == "__main__":
    unittest.main()
