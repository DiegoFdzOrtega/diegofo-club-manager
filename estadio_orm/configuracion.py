"""
estadio_orm/configuracion.py
Lee la configuración del ORM desde un fichero estadio.ini:

    [conexion]
    motor = motor/estadio.exe      ; dónde está el motor compilado
    base_de_datos = datos_club     ; carpeta de la base de datos

    [orm]
    mostrar_sql = si               ; enseñar por pantalla el SQL que genera el ORM

Las rutas relativas se toman desde la carpeta donde está el .ini.
"""

import configparser
import os
from dataclasses import dataclass

from .campos import ErrorORM

NOMBRE_FICHERO = "estadio.ini"


@dataclass
class Configuracion:
    motor: str
    base_de_datos: str
    mostrar_sql: bool = False
    fichero: str = ""

    def __str__(self):
        return (f"fichero de configuración: {self.fichero}\n"
                f"motor:                    {self.motor}\n"
                f"base de datos:            {self.base_de_datos}\n"
                f"mostrar SQL:              {'sí' if self.mostrar_sql else 'no'}")


def cargar_configuracion(ruta=None):
    """Lee estadio.ini (por defecto, el de la carpeta actual) y devuelve una Configuracion."""
    ruta = os.path.abspath(ruta or NOMBRE_FICHERO)
    if not os.path.exists(ruta):
        raise ErrorORM(f"no se encuentra el fichero de configuración {ruta}")

    ini = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    # Además de yes/no, true/false... aceptar también "si" y "sí"
    ini.BOOLEAN_STATES = {**configparser.ConfigParser.BOOLEAN_STATES, "si": True, "sí": True}
    ini.read(ruta, encoding="utf-8")
    try:
        motor = ini.get("conexion", "motor")
        base = ini.get("conexion", "base_de_datos")
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise ErrorORM(f"configuración incompleta en {ruta}: {e}") from e

    carpeta = os.path.dirname(ruta)
    motor = os.path.normpath(os.path.join(carpeta, motor))
    base = os.path.normpath(os.path.join(carpeta, base))
    # En Windows el ejecutable lleva .exe: si en el .ini no se puso, se añade
    if os.name == "nt" and not motor.lower().endswith(".exe"):
        motor += ".exe"
    if os.name != "nt" and motor.lower().endswith(".exe") and not os.path.exists(motor):
        motor = motor[:-4]
    if not os.path.exists(motor):
        raise ErrorORM(f"no se encuentra el motor en {motor} (¿lo has compilado?)")

    mostrar = ini.getboolean("orm", "mostrar_sql", fallback=False) if ini.has_section("orm") else False
    return Configuracion(motor=motor, base_de_datos=base, mostrar_sql=mostrar, fichero=ruta)
