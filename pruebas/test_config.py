"""Tarea 1.2: configuración global, proyectos, ubicaciones, ejecutables por ruta absoluta y `orq proyecto nuevo`.

Specs: proyectos (todos los escenarios), estado-cowork ("Carpeta de Cowork fuera de la raíz de estado") y
adaptadores-agente ("Nombre suelto", "PATH engañoso", "Ruta absoluta válida").
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

from ayudantes import PruebaOrq, foto

from orquestador import config as cfg
from orquestador import proyectos as proy
from orquestador import inicio


class PruebaRaizDeEstado(PruebaOrq):
    def test_raiz_por_defecto_en_userprofile_y_crea_proyectos(self):
        c = cfg.cargar_config()
        self.assertEqual(c.raiz, self.home / ".orquestador")
        self.escribir_config()  # sin "raiz_estado"
        self.assertFalse((self.raiz / "proyectos").exists())
        contexto = inicio.iniciar()
        try:
            self.assertTrue((self.home / ".orquestador" / "proyectos").is_dir())
        finally:
            contexto.cerrar()

    def test_orq_raiz_y_argumento_mandan(self):
        os.environ["ORQ_RAIZ"] = str(self.tmp / "otra")
        self.assertEqual(cfg.cargar_config().raiz, self.tmp / "otra")
        self.assertEqual(cfg.cargar_config(raiz=self.tmp / "tercera").raiz, self.tmp / "tercera")

    def test_raiz_dentro_de_un_repo_registrado(self):
        repo = self.crear_repo("repo-demo")
        raiz = repo / "estado"
        (raiz / "proyectos" / "demo").mkdir(parents=True)
        (raiz / "proyectos" / "demo" / "proyecto.json").write_text(
            json.dumps({"nombre": "demo", "repo": str(repo), "agentes_permitidos": ["cc"]}), encoding="utf-8")
        antes = foto(self.tmp)
        with self.assertRaises(cfg.ErrorConfig) as error:
            inicio.iniciar(raiz=raiz)
        self.assertIn("demo", str(error.exception))
        self.assertEqual(foto(self.tmp), antes, "no debe escribir nada")

    def test_raiz_dentro_de_un_worktree(self):
        repo = self.crear_repo("repo")
        worktree = self.tmp / "wt-login"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../repo/.git/worktrees/wt-login", encoding="utf-8")
        self.escribir_proyecto("demo", repo)
        c = cfg.cargar_config(raiz=self.raiz)
        c.raiz = worktree / "estado"
        with self.assertRaises(cfg.ErrorConfig):
            cfg.validar_ubicaciones(c, proy.cargar_proyectos(cfg.cargar_config(raiz=self.raiz)))


class PruebaCarpetaCowork(PruebaOrq):
    def test_cowork_por_defecto(self):
        self.assertEqual(cfg.cargar_config().cowork_raiz, self.home / "Orquestador-Cowork")

    def test_cowork_dentro_de_la_raiz_es_error_sin_escribir(self):
        self.escribir_config(cowork_raiz=str(self.raiz / "cowork"))
        antes = foto(self.tmp)
        with self.assertRaises(cfg.ErrorConfig):
            inicio.iniciar()
        self.assertEqual(foto(self.tmp), antes)

    def test_raiz_dentro_de_cowork_es_error(self):
        self.escribir_config(cowork_raiz=str(self.home))
        with self.assertRaises(cfg.ErrorConfig):
            inicio.iniciar()

    def test_cowork_dentro_de_un_repo_es_error(self):
        repo = self.crear_repo("repo")
        self.escribir_config(cowork_raiz=str(repo / "cowork"))
        self.escribir_proyecto("demo", repo)
        with self.assertRaises(cfg.ErrorConfig) as error:
            inicio.iniciar()
        self.assertIn("demo", str(error.exception))


class PruebaEjecutables(PruebaOrq):
    def test_ruta_absoluta_valida(self):
        partes, motivo = cfg.resolver_ejecutable(sys.executable)
        self.assertIsNone(motivo)
        self.assertEqual(partes, [sys.executable])

    def test_lista_con_ruta_absoluta(self):
        partes, motivo = cfg.resolver_ejecutable([sys.executable, "falso.py", "--como", "cc"])
        self.assertIsNone(motivo)
        self.assertEqual(partes, [sys.executable, "falso.py", "--como", "cc"])

    def test_nombre_suelto_no_disponible(self):
        self.escribir_config(agentes={"cc": {"ejecutable": "claude", "habilitado": True}})
        agente = cfg.cargar_config().agentes["cc"]
        self.assertFalse(agente.disponible)
        self.assertEqual(agente.motivo, "el ejecutable debe ser una ruta absoluta")

    def test_ruta_inexistente_no_disponible(self):
        self.escribir_config(agentes={"cc": {"ejecutable": str(self.tmp / "no" / "claude.exe")}})
        agente = cfg.cargar_config().agentes["cc"]
        self.assertFalse(agente.disponible)
        self.assertIn("no existe", agente.motivo)

    def test_path_enganoso_no_se_consulta(self):
        engano = self.tmp / "engano"
        engano.mkdir()
        (engano / "claude.exe").write_bytes(b"falso")
        (engano / "git.exe").write_bytes(b"falso")
        verdadero = self.tmp / "bin" / "claude.exe"
        verdadero.parent.mkdir()
        verdadero.write_bytes(b"verdadero")
        self.escribir_config(agentes={"cc": {"ejecutable": str(verdadero)}})
        path_original = os.environ.get("PATH", "")
        os.environ["PATH"] = str(engano) + os.pathsep + path_original
        try:
            c = cfg.cargar_config()
            self.assertEqual(c.agentes["cc"].ejecutable, [str(verdadero)])
            self.assertTrue(c.agentes["cc"].disponible)
            # Con un nombre suelto tampoco se usa el del PATH.
            self.escribir_config(agentes={"cc": {"ejecutable": "claude.exe"}}, herramientas={"git": "git"})
            c = cfg.cargar_config()
            self.assertIsNone(c.agentes["cc"].ejecutable)
            self.assertIsNone(c.git)
            self.assertEqual(c.git_motivo, "el ejecutable debe ser una ruta absoluta")
        finally:
            os.environ["PATH"] = path_original

    def test_git_obligatorio_para_iniciar(self):
        self.escribir_config(herramientas={"git": "git"})
        with self.assertRaises(cfg.ErrorConfig) as error:
            inicio.iniciar()
        self.assertIn("git", str(error.exception))


class PruebaProyectos(PruebaOrq):
    def test_proyecto_valido(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo)
        lista = proy.cargar_proyectos(cfg.cargar_config())
        self.assertEqual([p.nombre for p in lista if p.activo], ["demo"])
        p = lista[0]
        self.assertEqual(p.base, "main")
        self.assertEqual(p.carpeta_worktrees, repo.parent)
        self.assertTrue(p.gate_por_defecto)
        self.assertFalse(p.red_permitida)

    def test_nombre_que_no_coincide_se_ignora(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("otro", repo, carpeta="demo")
        lista = proy.cargar_proyectos(cfg.cargar_config())
        self.assertFalse(lista[0].activo)
        self.assertIn("no coincide", " ".join(lista[0].errores))

    def test_nombre_invalido(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("Demo_X", repo)
        self.assertFalse(proy.cargar_proyectos(cfg.cargar_config())[0].activo)

    def test_repo_inexistente_no_afecta_a_los_demas(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("bueno", repo)
        self.escribir_proyecto("malo", self.tmp / "no-existe")
        sin_git = self.tmp / "sin-git"
        sin_git.mkdir()
        self.escribir_proyecto("sin-git", sin_git)
        por_nombre = {p.nombre: p for p in proy.cargar_proyectos(cfg.cargar_config())}
        self.assertTrue(por_nombre["bueno"].activo)
        self.assertFalse(por_nombre["malo"].activo)
        self.assertFalse(por_nombre["sin-git"].activo)
        self.assertIn("repo", " ".join(por_nombre["malo"].errores))

    def test_error_queda_en_el_registro(self):
        self.escribir_config()
        self.escribir_proyecto("malo", self.tmp / "no-existe")
        contexto = inicio.iniciar()
        try:
            texto = (self.raiz / "registro.log").read_text(encoding="utf-8")
            self.assertIn("malo", texto)
        finally:
            contexto.cerrar()

    def test_limite_mayor_que_el_global(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo, limites={"por_agente": {"cc": 3}, "global": 5})
        p = proy.cargar_proyectos(cfg.cargar_config())[0]
        self.assertTrue(p.activo)
        self.assertEqual(p.limite_por_agente["cc"], 1)
        self.assertEqual(p.limite_global, 2)
        self.assertTrue(any("límite" in a for a in p.advertencias))

    def test_limite_menor_se_respeta(self):
        repo = self.crear_repo()
        self.escribir_config(limites={"global": 4, "por_agente": {"cc": 3}})
        self.escribir_proyecto("demo", repo, limites={"por_agente": {"cc": 2}, "global": 1})
        p = proy.cargar_proyectos(cfg.cargar_config())[0]
        self.assertEqual((p.limite_por_agente["cc"], p.limite_global), (2, 1))

    def test_intento_de_permitir_git_push(self):
        repo = self.crear_repo()
        self.escribir_config()
        for regla in ("Bash(git push *)", "Bash(git *)", "PowerShell(git commit -m *)", "Bash", "Bash(*)",
                      "Read(~/.ssh/**)", "Read(//**/.env)", "Edit(~/.embudo/**)"):
            with self.subTest(regla=regla):
                self.escribir_proyecto("demo", repo, permisos={"permitir_extra": [regla]})
                p = proy.cargar_proyectos(cfg.cargar_config())[0]
                self.assertFalse(p.activo)
                self.assertIn("denegación obligatoria", " ".join(p.errores))

    def test_permiso_extra_inofensivo_y_denegacion_extra(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo, permisos={"permitir_extra": ["Bash(npm test)"],
                                                       "denegar_extra": ["Bash(docker *)"]})
        p = proy.cargar_proyectos(cfg.cargar_config())[0]
        self.assertTrue(p.activo, p.errores)
        self.assertEqual(p.denegar_extra, ["Bash(docker *)"])

    def test_agente_no_configurado(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo, agentes_permitidos=["codex"])
        p = proy.cargar_proyectos(cfg.cargar_config())[0]
        self.assertFalse(p.activo)

    def test_estado_separado_por_proyecto(self):
        repo_a, repo_b = self.crear_repo("a"), self.crear_repo("b")
        self.escribir_config()
        self.escribir_proyecto("a", repo_a)
        self.escribir_proyecto("b", repo_b)
        por_nombre = {p.nombre: p for p in proy.cargar_proyectos(cfg.cargar_config())}
        self.assertEqual(por_nombre["a"].ruta_tareas, self.raiz / "proyectos" / "a" / "tareas.json")
        self.assertEqual(por_nombre["b"].ruta_tareas, self.raiz / "proyectos" / "b" / "tareas.json")
        self.assertEqual(por_nombre["a"].carpeta_cowork, self.cowork / "a")


class PruebaProyectoNuevo(PruebaOrq):
    def test_crea_proyecto_y_carpetas_de_cowork(self):
        repo = self.crear_repo("mi-repo")
        self.escribir_config()
        salida = proy.proyecto_nuevo(cfg.cargar_config(), "demo", repo)
        datos = json.loads((self.raiz / "proyectos" / "demo" / "proyecto.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["nombre"], "demo")
        self.assertEqual(datos["repo"], str(repo))
        self.assertFalse(datos["red"]["permitida"])
        self.assertTrue(datos["gate_por_defecto"])
        carpeta = self.home / "Orquestador-Cowork" / "demo"
        self.assertEqual(sorted(x.name for x in carpeta.iterdir()), ["entrada", "respuestas", "salida"])
        self.assertIn("demo", salida)

    def test_no_pisa_un_proyecto_existente(self):
        repo = self.crear_repo()
        self.escribir_config()
        proy.proyecto_nuevo(cfg.cargar_config(), "demo", repo)
        with self.assertRaises(cfg.ErrorConfig):
            proy.proyecto_nuevo(cfg.cargar_config(), "demo", repo)

    def test_repo_que_no_es_git(self):
        carpeta = self.tmp / "no-git"
        carpeta.mkdir()
        self.escribir_config()
        antes = foto(self.tmp)
        with self.assertRaises(cfg.ErrorConfig):
            proy.proyecto_nuevo(cfg.cargar_config(), "demo", carpeta)
        self.assertEqual(foto(self.tmp), antes)

    def test_sugerencias_sin_path(self):
        en_perfil = self.home / ".local" / "bin" / "claude.exe"
        en_perfil.parent.mkdir(parents=True)
        en_perfil.write_bytes(b"x")
        en_path = self.tmp / "solo-en-path"
        en_path.mkdir()
        (en_path / "claude.exe").write_bytes(b"x")
        path_original = os.environ.get("PATH", "")
        os.environ["PATH"] = str(en_path) + os.pathsep + path_original
        try:
            sugerencias = proy.sugerir_ejecutables()
        finally:
            os.environ["PATH"] = path_original
        self.assertIn(str(en_perfil), sugerencias["cc"])
        self.assertNotIn(str(en_path / "claude.exe"), sugerencias["cc"])

    def test_cli_proyecto_nuevo(self):
        import subprocess
        repo = self.crear_repo("repo-cli")
        self.escribir_config()
        from ayudantes import RAIZ_REPO
        r = subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), "proyecto", "nuevo", "demo", "--repo",
                            str(repo)], capture_output=True, text=True, encoding="utf-8", env=os.environ.copy(),
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.raiz / "proyectos" / "demo" / "proyecto.json").is_file())


if __name__ == "__main__":
    unittest.main()
