"""
estadio_orm/campos.py
Tipos de campo: describen cómo se guarda cada atributo de un objeto en una columna.

    class Socio(Modelo):
        id = Entero(primaria=True)        ->  id INT PRIMARY KEY
        nombre = Texto(obligatorio=True)  ->  nombre TEXT
        activo = Booleano(por_defecto=True) -> activo INT  (1 / 0)
        nacimiento = Fecha()              ->  nacimiento TEXT  (AAAA-MM-DD validada)
        pago = Opcion(["Efectivo", "Domiciliación"]) -> pago TEXT (solo esos valores)
        equipo = ClaveForanea(Equipo)     ->  equipo_id INT REFERENCES equipos(id)
"""


class ErrorORM(Exception):
    """Error del ORM: mapeo mal definido, valor de tipo incorrecto, fallo al guardar..."""


class Campo:
    tipo_sql = "TEXT"

    def __init__(self, primaria=False, por_defecto=None, obligatorio=False):
        self.primaria = primaria
        self.por_defecto = por_defecto
        self.obligatorio = obligatorio
        self.nombre = None   # nombre del atributo en Python (lo pone Python al crear la clase)
        self.columna = None  # nombre de la columna en la base de datos

    def __set_name__(self, modelo, nombre):
        self.nombre = nombre
        self.columna = nombre

    def definicion_sql(self):
        sql = f"{self.columna} {self.tipo_sql}"
        if self.primaria:
            sql += " PRIMARY KEY"
        return sql

    def validar(self, valor):
        """Comprueba el valor antes de guardarlo en el objeto. Devuelve el valor (o lo corrige)."""
        return valor

    def a_bd(self, valor):
        """Valor de Python -> valor para la base de datos."""
        return valor

    def a_python(self, valor):
        """Valor de la base de datos -> valor de Python."""
        return valor


class Entero(Campo):
    tipo_sql = "INT"

    def validar(self, valor):
        if valor is None:
            if self.primaria:
                return None  # la pone la base de datos al insertar
            raise ErrorORM(f"'{self.nombre}' no puede estar vacío")
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ErrorORM(f"'{self.nombre}' debe ser un número entero (se ha dado {valor!r})")
        return valor


class Texto(Campo):
    tipo_sql = "TEXT"

    def __init__(self, largo_maximo=None, **opciones):
        super().__init__(**opciones)
        self.largo_maximo = largo_maximo

    def validar(self, valor):
        if valor is None:
            valor = ""
        if not isinstance(valor, str):
            raise ErrorORM(f"'{self.nombre}' debe ser un texto (se ha dado {valor!r})")
        if "\n" in valor or "\r" in valor:
            raise ErrorORM(f"'{self.nombre}' no puede tener saltos de línea")
        if self.obligatorio and not valor.strip():
            raise ErrorORM(f"'{self.nombre}' es obligatorio")
        if self.largo_maximo and len(valor) > self.largo_maximo:
            raise ErrorORM(f"'{self.nombre}' no puede pasar de {self.largo_maximo} caracteres")
        return valor


class Fecha(Texto):
    """Fecha guardada como texto AAAA-MM-DD (así se ordena bien). Puede quedar vacía."""

    def validar(self, valor):
        valor = super().validar(valor).strip()
        if valor:
            from datetime import date
            try:
                date.fromisoformat(valor)
            except ValueError:
                raise ErrorORM(f"'{self.nombre}' debe ser una fecha AAAA-MM-DD (se ha dado {valor!r})") from None
        return valor


class Opcion(Texto):
    """Texto que solo puede tomar unos valores concretos: Opcion(["Efectivo", "Domiciliación"])."""

    def __init__(self, opciones, **kwargs):
        super().__init__(**kwargs)
        self.opciones = list(opciones)
        if self.por_defecto is None:
            self.por_defecto = self.opciones[0]

    def validar(self, valor):
        valor = super().validar(valor)
        if valor not in self.opciones:
            raise ErrorORM(f"'{self.nombre}' debe ser una de: {', '.join(self.opciones)}")
        return valor


class Booleano(Campo):
    """Verdadero/falso. La base de datos no tiene ese tipo: se guarda como INT 1 o 0."""
    tipo_sql = "INT"

    def validar(self, valor):
        if not isinstance(valor, bool):
            raise ErrorORM(f"'{self.nombre}' debe ser True o False")
        return valor

    def a_bd(self, valor):
        return 1 if valor else 0

    def a_python(self, valor):
        return bool(valor)


class ClaveForanea(Campo):
    """
    Relación "muchos a uno": muchos socios pertenecen a un equipo.

        equipo = ClaveForanea(Equipo)

    - En la base de datos crea la columna  equipo_id INT REFERENCES equipos(id)
    - En Python:  socio.equipo     -> devuelve el objeto Equipo (lo carga solo)
                  socio.equipo = e -> guarda el id de e
                  socio.equipo_id  -> el número, directamente
    """
    tipo_sql = "INT"

    def __init__(self, modelo_destino, **opciones):
        super().__init__(**opciones)
        self.modelo_destino = modelo_destino  # la clase, o su nombre como texto

    def __set_name__(self, modelo, nombre):
        self.nombre = nombre
        self.columna = nombre + "_id"

    def destino(self):
        from .modelo import modelo_por_nombre
        if isinstance(self.modelo_destino, str):
            return modelo_por_nombre(self.modelo_destino)
        return self.modelo_destino

    def definicion_sql(self):
        d = self.destino()
        return f"{self.columna} INT REFERENCES {d._tabla}({d._primaria.columna})"

    # En la base de datos, 0 significa "sin relación" (no hay NULL)
    def a_bd(self, valor):
        return 0 if valor is None else valor

    def a_python(self, valor):
        return None if valor in (0, None) else valor

    def validar(self, valor):
        if valor is None:
            if self.obligatorio:
                raise ErrorORM(f"'{self.nombre}' es obligatorio")
            return None
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ErrorORM(f"'{self.columna}' debe ser un número entero (el id)")
        return valor

    # --- Descriptor: lo que pasa al leer o escribir  socio.equipo -------------
    def __get__(self, objeto, modelo=None):
        if objeto is None:
            return self  # acceso desde la clase: Socio.equipo
        id_destino = objeto.__dict__.get(self.columna)
        if id_destino is None:
            return objeto._referencias.get(self.columna)  # objeto relacionado aún sin guardar
        conocido = objeto._relacionados.get(self.columna)
        if conocido is not None and conocido._valor_primaria() == id_destino:
            return conocido  # ya lo tenemos: no hace falta consultar
        if objeto._sesion is None:
            raise ErrorORM("para cargar la relación, el objeto debe estar en una sesión")
        return objeto._sesion.obtener(self.destino(), id_destino)

    def __set__(self, objeto, valor):
        from .modelo import Modelo
        if valor is None:
            objeto.__setattr__(self.columna, None)
            objeto._referencias.pop(self.columna, None)
            return
        if not isinstance(valor, Modelo) or not isinstance(valor, self.destino()):
            raise ErrorORM(f"'{self.nombre}' debe ser un objeto {self.destino().__name__}")
        pk = valor._valor_primaria()
        if pk is None:
            # Todavía no tiene id: se apunta y el id se pondrá al guardar
            objeto._referencias[self.columna] = valor
            objeto.__dict__[self.columna] = None
            objeto._marcar_cambio(self.columna)
        else:
            objeto._referencias.pop(self.columna, None)
            objeto.__setattr__(self.columna, pk)
        objeto._relacionados[self.columna] = valor


class Relacion:
    """
    Relación "uno a muchos" (la vuelta de una ClaveForanea):

        class Equipo(Modelo):
            socios = Relacion("Socio", "equipo")

        equipo.socios  -> lista de objetos Socio de ese equipo

    No crea ninguna columna: hace una consulta cuando se lee.
    """

    def __init__(self, modelo_origen, clave):
        self.modelo_origen = modelo_origen
        self.clave = clave

    def __set_name__(self, modelo, nombre):
        self.nombre = nombre

    def __get__(self, objeto, modelo=None):
        if objeto is None:
            return self
        from .modelo import modelo_por_nombre
        origen = modelo_por_nombre(self.modelo_origen) if isinstance(self.modelo_origen, str) else self.modelo_origen
        if objeto._sesion is None or objeto._valor_primaria() is None:
            return []
        return objeto._sesion.consulta(origen).filtrar(**{self.clave: objeto}).todos()

    def __set__(self, objeto, valor):
        raise ErrorORM(f"'{self.nombre}' es de solo lectura: cambia la clave foránea en cada objeto")
