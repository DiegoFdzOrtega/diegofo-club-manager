"""
estadio_orm — ORM (mapeo objeto-relacional) para la base de datos "diegofo | estadio".

    from estadio_orm import Modelo, Entero, Texto, Booleano, Fecha, Opcion, ClaveForanea, Relacion, Sesion

Diego Fernández Ortega · RA3 Acceso a datos (0486)
"""

from .campos import Booleano, ClaveForanea, Entero, ErrorORM, Fecha, Opcion, Relacion, Texto
from .configuracion import Configuracion, cargar_configuracion
from .modelo import Modelo
from .sesion import Consulta, Sesion

__version__ = "1.0.0"

__all__ = [
    "Modelo", "Entero", "Texto", "Booleano", "Fecha", "Opcion", "ClaveForanea", "Relacion",
    "Sesion", "Consulta", "Configuracion", "cargar_configuracion", "ErrorORM",
]
