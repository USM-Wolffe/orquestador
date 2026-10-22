"""Tarea 3.1: redacción de secretos (spec eventos-actividad, "Secreto en un comando"). Todos los valores son
sintéticos o ejemplos públicos de documentación."""
from __future__ import annotations

import unittest

from orquestador import redaccion

R = "[REDACTADO]"


class PruebaPatrones(unittest.TestCase):
    def assertRedacta(self, texto, secreto, conservar=None):
        resultado = redaccion.redactar(texto)
        self.assertNotIn(secreto, resultado)
        self.assertIn(R, resultado)
        if conservar:
            self.assertIn(conservar, resultado)
        return resultado

    def test_anthropic(self):
        self.assertRedacta("export K=sk-ant-api03-AbCdEf0123456789_xyzXYZ-abc && run", "AbCdEf0123456789",
                           conservar="run")

    def test_openai(self):
        self.assertRedacta("clave sk-proj-abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123")

    def test_github_token(self):
        self.assertRedacta("git clone https://ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "@x",
                           "a1B2c3D4e5F6g7H8i9J0")

    def test_github_pat(self):
        self.assertRedacta("token github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz", "11ABCDEFG0123456789")

    def test_aws_access_key(self):
        self.assertRedacta("aws configure set aws_access_key_id AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE",
                           conservar="aws configure")

    def test_slack(self):
        self.assertRedacta("curl -d token=xoxb-123456789012-abcdefghijklmnop", "xoxb-123456789012")

    def test_llave_pem(self):
        pem = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAsintetico0123456789\nabcdef==\n"
               "-----END RSA PRIVATE KEY-----")
        resultado = self.assertRedacta(f"echo '{pem}' > id_rsa", "MIIEowIBAAKCAQEAsintetico")
        self.assertNotIn("abcdef==", resultado)

    def test_llave_pem_sin_cierre(self):
        self.assertRedacta("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA", "b3BlbnNzaC1rZXktdjEAAAA")

    def test_cabecera_authorization(self):
        resultado = self.assertRedacta("curl -H 'Authorization: Basic dXNlcjpwYXNzd29yZA==' https://x",
                                       "dXNlcjpwYXNzd29yZA==")
        self.assertIn("Authorization", resultado)

    def test_bearer(self):
        self.assertRedacta("Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef")

    def test_asignaciones(self):
        for texto, secreto in (("password=hunter2xyz", "hunter2xyz"), ("TOKEN: tok_sintetico_123", "tok_sintetico_123"),
                               ('api_key="clave-sintetica-1"', "clave-sintetica-1"),
                               ("secret = valor-secreto-2", "valor-secreto-2")):
            with self.subTest(texto=texto):
                self.assertRedacta(texto, secreto)

    def test_jwt(self):
        jwt = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
               "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
        self.assertRedacta(f"cookie={jwt}", "dozjgNryP4J3jVmNHl0w5N")

    def test_patron_extra_del_proyecto(self):
        resultado = redaccion.redactar("cliente CL-998877 aprobado", extra=[r"CL-\d{6}"])
        self.assertEqual(resultado, f"cliente {R} aprobado")

    def test_texto_sin_secretos_no_cambia(self):
        for texto in ("py -3.12 -m unittest discover -s pruebas", "git diff --stat", "edita app.py",
                      "la palabra token sola no es un secreto"):
            with self.subTest(texto=texto):
                self.assertEqual(redaccion.redactar(texto), texto)

    def test_truncar(self):
        self.assertEqual(redaccion.truncar("abc", 10), "abc")
        largo = redaccion.truncar("x" * 100, 20)
        self.assertEqual(len(largo), 20)
        self.assertTrue(largo.endswith(redaccion.MARCA_TRUNCADO))


if __name__ == "__main__":
    unittest.main()
