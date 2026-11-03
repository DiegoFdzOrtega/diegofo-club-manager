"""
estadio_orm/conector.py
Conector de bajo nivel para "diegofo | estadio" (el mismo del RA2, con lastrowid).
El ORM lo usa por debajo para mandar el SQL que genera.

Se usa igual que los conectores "de verdad" (sqlite3, mysql-connector, PyMySQL),
que siguen el estándar DB-API de Python (PEP 249):

    from estadio_orm import conector

    conexion = conector.conectar("datos_club", "motor/estadio.exe")
    cursor = conexion.cursor()
    cursor.execute("SELECT * FROM jugadores WHERE goles > ?", (5,))
    for fila in cursor.fetchall():
        print(fila)
    cursor.close()
    conexion.close()

Cómo funciona por dentro:
  el conector arranca el programa estadio.exe en modo --json y habla con él
  por su entrada y salida estándar (stdin/stdout): le manda una orden por
  línea y lee una respuesta en JSON por línea.
"""

import json
import os
import subprocess

# Carpeta donde está este archivo -> el motor está en motor/estadio.exe
_CARPETA = os.path.dirname(os.path.abspath(__file__))
_EJECUTABLE = os.path.join(_CARPETA, "motor", "estadio.exe" if os.name == "nt" else "estadio")


class ErrorEstadio(Exception):
    """Cualquier error que devuelva la base de datos o el conector."""


def conectar(base_de_datos, ejecutable=_EJECUTABLE):
    """Abre una conexión con la base de datos (una carpeta). Devuelve un objeto Conexion."""
    return Conexion(base_de_datos, ejecutable)


# ---------------------------------------------------------------------------
# Utilidades para pasar valores de Python a texto SQL de forma SEGURA
# ---------------------------------------------------------------------------

def _literal(valor):
    """Convierte un valor de Python en un valor SQL: 7 -> 7, "Hugo" -> 'Hugo'."""
    if isinstance(valor, bool):
        raise ErrorEstadio("esta base de datos no tiene tipo booleano")
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, str):
        if "\n" in valor or "\r" in valor:
            raise ErrorEstadio("los textos no pueden tener saltos de línea")
        # Las comillas se duplican: O'Neil -> 'O''Neil'. Así nadie puede "colar" SQL.
        return "'" + valor.replace("'", "''") + "'"
    raise ErrorEstadio(f"tipo no admitido: {type(valor).__name__} (usa int o str)")


def _sustituir_parametros(sql, parametros):
    """Cambia cada ? de la orden por el parámetro que toca (fuera de las comillas)."""
    parametros = list(parametros)
    resultado = []
    en_comillas = False
    usados = 0
    for caracter in sql:
        if caracter == "'":
            en_comillas = not en_comillas
        if caracter == "?" and not en_comillas:
            if usados >= len(parametros):
                raise ErrorEstadio("hay más ? que parámetros")
            resultado.append(_literal(parametros[usados]))
            usados += 1
        else:
            resultado.append(caracter)
    if usados != len(parametros):
        raise ErrorEstadio(f"se han dado {len(parametros)} parámetros pero hay {usados} ?")
    return "".join(resultado)


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

class Conexion:
    def __init__(self, base_de_datos, ejecutable=_EJECUTABLE):
        if not os.path.exists(ejecutable):
            raise ErrorEstadio(f"no se encuentra el motor en {ejecutable} (¿lo has compilado?)")
        try:
            self._proceso = subprocess.Popen(
                [ejecutable, base_de_datos, "--json"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,  # enviar cada línea en cuanto se escribe
            )
        except OSError as e:
            raise ErrorEstadio(f"no se pudo arrancar el motor: {e}") from e

        # El motor saluda nada más arrancar: si no, la conexión ha fallado
        saludo = self._leer_respuesta()
        self.version = saludo.get("version", "?")
        self.base_de_datos = base_de_datos
        self.abierta = True
        self.en_transaccion = False

    def _leer_respuesta(self):
        linea = self._proceso.stdout.readline()
        if not linea:
            raise ErrorEstadio("el motor se ha cerrado inesperadamente")
        respuesta = json.loads(linea)
        if not respuesta["ok"]:
            raise ErrorEstadio(respuesta["error"])
        return respuesta

    def _enviar(self, sql):
        """Manda una orden al motor y devuelve su respuesta (un diccionario)."""
        if not self.abierta:
            raise ErrorEstadio("la conexión está cerrada")
        if "\n" in sql or "\r" in sql:
            raise ErrorEstadio("una orden no puede tener saltos de línea")
        self._proceso.stdin.write(sql + "\n")
        self._proceso.stdin.flush()
        return self._leer_respuesta()

    def cursor(self):
        """Crea un cursor: el objeto que lanza las consultas y guarda sus resultados."""
        return Cursor(self)

    # --- Transacciones -------------------------------------------------------
    def begin(self):
        self._enviar("BEGIN")
        self.en_transaccion = True

    def commit(self):
        self._enviar("COMMIT")
        self.en_transaccion = False

    def rollback(self):
        self._enviar("ROLLBACK")
        self.en_transaccion = False

    # --- Cierre ----------------------------------------------------------------
    def close(self):
        """Cierra la conexión y termina el proceso del motor."""
        if not self.abierta:
            return
        try:
            self._enviar("SALIR")
        except ErrorEstadio:
            pass
        self.abierta = False
        self._proceso.stdin.close()
        self._proceso.stdout.close()
        self._proceso.stderr.close()
        self._proceso.wait(timeout=5)

    # Para poder usar "with conectar(...) as conexion:"
    def __enter__(self):
        return self

    def __exit__(self, tipo_error, error, traza):
        if self.abierta and self.en_transaccion and tipo_error is not None:
            self.rollback()  # si algo falló dentro del with, no se guarda nada a medias
        self.close()
        return False


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

class Cursor:
    def __init__(self, conexion):
        self._conexion = conexion
        self._filas = []
        self._posicion = 0
        self.columnas = []      # nombres de las columnas de la última consulta
        self.rowcount = -1      # filas devueltas o afectadas por la última orden
        self.lastrowid = None   # id generado por el último INSERT
        self.mensaje = ""
        self.cerrado = False

    def _comprobar(self):
        if self.cerrado:
            raise ErrorEstadio("el cursor está cerrado")

    def execute(self, sql, parametros=()):
        """Ejecuta una orden. Usa ? para los valores: execute("... WHERE id = ?", (3,))"""
        self._comprobar()
        respuesta = self._conexion._enviar(_sustituir_parametros(sql, parametros))
        self.columnas = respuesta.get("columnas", [])
        self._filas = [tuple(f) for f in respuesta.get("filas", [])]
        self._posicion = 0
        self.mensaje = respuesta.get("mensaje", "")
        self.rowcount = len(self._filas) if "filas" in respuesta else respuesta.get("afectadas", 0)
        self.lastrowid = respuesta.get("ultimo_id")
        return self

    def callproc(self, nombre, parametros=()):
        """Ejecuta un procedimiento almacenado: callproc("goleadores", (1,))"""
        marcas = ", ".join("?" for _ in parametros)
        return self.execute(f"CALL {nombre}({marcas})", parametros)

    def fetchone(self):
        """Devuelve la siguiente fila (una tupla) o None si no quedan."""
        self._comprobar()
        if self._posicion >= len(self._filas):
            return None
        fila = self._filas[self._posicion]
        self._posicion += 1
        return fila

    def fetchmany(self, cantidad=1):
        self._comprobar()
        filas = self._filas[self._posicion:self._posicion + cantidad]
        self._posicion += len(filas)
        return filas

    def fetchall(self):
        """Devuelve todas las filas que quedan, como lista de tuplas."""
        self._comprobar()
        filas = self._filas[self._posicion:]
        self._posicion = len(self._filas)
        return filas

    def close(self):
        """Libera los resultados guardados. El cursor ya no se puede usar."""
        self._filas = []
        self.columnas = []
        self.cerrado = True

    def __iter__(self):
        fila = self.fetchone()
        while fila is not None:
            yield fila
            fila = self.fetchone()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False
