"""
estadio_orm/modelo.py
La clase Modelo: de ella heredan las clases que se guardan en la base de datos.

    class Equipo(Modelo):
        __tabla__ = "equipos"           # nombre de la tabla (si no, el de la clase + "s")
        id = Entero(primaria=True)
        nombre = Texto(obligatorio=True)

Al definir la clase, una "metaclase" lee sus campos y prepara el MAPEO:
qué tabla le corresponde, qué columna tiene cada atributo y cuál es la clave primaria.
"""

from .campos import Booleano, Campo, ClaveForanea, ErrorORM

_registro = {}  # nombre de clase -> clase (para relaciones escritas como texto: "Socio")


def modelo_por_nombre(nombre):
    if nombre not in _registro:
        raise ErrorORM(f"no existe ningún modelo llamado '{nombre}'")
    return _registro[nombre]


class MetaModelo(type):
    """Se ejecuta al DEFINIR cada clase modelo y construye su mapeo objeto-relacional."""

    def __new__(mcs, nombre, bases, atributos):
        clase = super().__new__(mcs, nombre, bases, atributos)
        if nombre == "Modelo":
            return clase

        campos = {k: v for k, v in atributos.items() if isinstance(v, Campo)}
        if not campos:
            raise ErrorORM(f"el modelo {nombre} no tiene ningún campo")
        primarias = [c for c in campos.values() if c.primaria]
        if len(primarias) != 1:
            raise ErrorORM(f"el modelo {nombre} debe tener exactamente una clave primaria")
        if primarias[0].tipo_sql != "INT" or isinstance(primarias[0], (ClaveForanea, Booleano)):
            raise ErrorORM(f"la clave primaria de {nombre} debe ser Entero")

        clase._campos = campos                                    # atributo -> Campo
        clase._columnas = {c.columna: c for c in campos.values()}  # columna -> Campo
        clase._primaria = primarias[0]
        clase._tabla = atributos.get("__tabla__", nombre.lower() + "s")
        _registro[nombre] = clase
        return clase


class Modelo(metaclass=MetaModelo):

    def __init__(self, **datos):
        self._preparar()
        # Valores por defecto
        for campo in self._campos.values():
            if campo.primaria:
                valor = None
            elif campo.por_defecto is not None:
                valor = campo.por_defecto() if callable(campo.por_defecto) else campo.por_defecto
            elif isinstance(campo, ClaveForanea):
                valor = None
            elif isinstance(campo, Booleano):
                valor = False
            else:
                valor = {"INT": 0, "TEXT": ""}[campo.tipo_sql]
            self.__dict__[campo.columna] = valor
        # Valores dados:  Socio(nombre="Ana", equipo=alevines)
        for clave, valor in datos.items():
            if clave not in self._campos and clave not in self._columnas:
                raise ErrorORM(f"{type(self).__name__} no tiene el campo '{clave}'")
            setattr(self, clave, valor)
        # Comprobar obligatorios
        for campo in self._campos.values():
            if campo.obligatorio and not isinstance(campo, ClaveForanea):
                campo.validar(self.__dict__[campo.columna])
        self._cambios.clear()

    def _preparar(self):
        """Datos internos que el ORM necesita en cada objeto (empiezan por _)."""
        object.__setattr__(self, "_sesion", None)
        object.__setattr__(self, "_estado", "nuevo")   # nuevo -> persistente -> borrado
        object.__setattr__(self, "_cambios", set())    # columnas modificadas sin guardar
        object.__setattr__(self, "_referencias", {})   # claves foráneas a objetos aún sin id
        object.__setattr__(self, "_relacionados", {})  # objetos relacionados ya conocidos (evita consultas)

    def __setattr__(self, nombre, valor):
        if nombre.startswith("_"):
            object.__setattr__(self, nombre, valor)
            return
        campo = self._campos.get(nombre)
        if isinstance(campo, ClaveForanea):
            object.__setattr__(self, nombre, valor)  # lo gestiona ClaveForanea.__set__
            return
        campo = self._columnas.get(nombre)
        if campo is None:
            object.__setattr__(self, nombre, valor)  # atributo normal, no se guarda
            return
        valor = campo.validar(valor)
        if campo.primaria and self._estado != "nuevo" and valor != self.__dict__.get(nombre):
            raise ErrorORM("no se puede cambiar la clave primaria de un objeto guardado")
        if self.__dict__.get(nombre) != valor or nombre not in self.__dict__:
            self.__dict__[nombre] = valor
            if isinstance(campo, ClaveForanea):
                self._referencias.pop(nombre, None)
            self._marcar_cambio(nombre)

    def _marcar_cambio(self, columna):
        # Solo interesa en objetos ya guardados: así el ORM sabe qué hay que actualizar
        if self._estado == "persistente":
            self._cambios.add(columna)

    def _valor_primaria(self):
        return self.__dict__.get(self._primaria.columna)

    def a_dict(self):
        """Los datos del objeto como diccionario {columna: valor}."""
        return {c: self.__dict__.get(c) for c in self._columnas}

    def __repr__(self):
        datos = ", ".join(f"{c}={v!r}" for c, v in self.a_dict().items())
        return f"<{type(self).__name__} {datos}>"

    def __eq__(self, otro):
        if type(self) is not type(otro):
            return NotImplemented
        pk = self._valor_primaria()
        return self is otro or (pk is not None and pk == otro._valor_primaria())

    def __hash__(self):
        return id(self)
