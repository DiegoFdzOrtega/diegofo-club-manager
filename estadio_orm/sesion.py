"""
estadio_orm/sesion.py
La Sesión es el "intermediario" entre tus objetos y la base de datos.

    sesion = Sesion()                      # lee estadio.ini y se conecta
    sesion.agregar(Socio(nombre="Ana"))    # apunta el objeto para guardarlo
    sesion.confirmar()                     # genera los INSERT/UPDATE/DELETE en una transacción

    ana = sesion.consulta(Socio).filtrar(nombre="Ana").primero()
    ana.email = "ana@club.es"              # la sesión se da cuenta del cambio...
    sesion.confirmar()                     # ...y genera solo:  UPDATE socios SET email = ... WHERE id = ...

Ideas que usa (las mismas que ORMs como SQLAlchemy o Hibernate):
  - Unidad de trabajo: los cambios se acumulan y se guardan juntos en confirmar().
  - Mapa de identidad: cada fila se carga UNA vez; pedirla otra vez devuelve el mismo objeto.
"""

from contextlib import contextmanager

from . import conector
from .campos import ClaveForanea, ErrorORM
from .configuracion import cargar_configuracion

OPERADORES = {"=", "!=", "<", ">", "<=", ">=", "LIKE"}


class Sesion:
    def __init__(self, configuracion=None, ruta_config=None):
        self.configuracion = configuracion or cargar_configuracion(ruta_config)
        self.mostrar_sql = self.configuracion.mostrar_sql
        try:
            self._conexion = conector.conectar(self.configuracion.base_de_datos, self.configuracion.motor)
        except conector.ErrorEstadio as e:
            raise ErrorORM(f"no se pudo conectar: {e}") from e
        self._mapa = {}        # (Clase, id) -> objeto   (mapa de identidad)
        self._nuevos = []      # objetos pendientes de INSERT
        self._borrados = []    # objetos pendientes de DELETE
        self.registro = []     # todo el SQL enviado (útil para depurar o enseñarlo en una web)

    # ------------------------------------------------------------------ SQL
    def _ejecutar(self, sql, parametros=()):
        texto = conector._sustituir_parametros(sql, parametros)
        self.registro.append(texto)
        if self.mostrar_sql:
            print("   [SQL]", texto)
        cursor = self._conexion.cursor()
        try:
            cursor.execute(sql, parametros)
        except conector.ErrorEstadio as e:
            raise ErrorORM(str(e)) from e
        return cursor

    def sql(self, sql, parametros=()):
        """SQL escrito a mano. Devuelve una lista de diccionarios {columna: valor}."""
        cursor = self._ejecutar(sql, parametros)
        filas = [dict(zip(cursor.columnas, f)) for f in cursor.fetchall()] if cursor.columnas else []
        cursor.close()
        return filas

    def sql_objetos(self, modelo, sql, parametros=()):
        """SQL escrito a mano que devuelve filas de UNA tabla -> lista de objetos del modelo."""
        cursor = self._ejecutar(sql, parametros)
        objetos = [self._materializar(modelo, cursor.columnas, f) for f in cursor.fetchall()]
        cursor.close()
        return objetos

    # ---------------------------------------------------------- Estructura
    def crear_tablas(self, *modelos):
        """Crea las tablas de los modelos que aún no existan (en el orden dado)."""
        existentes = {f["tabla"] for f in self.sql("SHOW TABLES")}
        for modelo in modelos:
            if modelo._tabla in existentes:
                continue
            columnas = ", ".join(c.definicion_sql() for c in modelo._campos.values())
            self._ejecutar(f"CREATE TABLE {modelo._tabla} ({columnas})").close()

    def migrar(self, *modelos):
        """
        Pone la base de datos al día con los modelos SIN perder datos:
          - crea las tablas que no existan
          - añade las columnas nuevas (ALTER TABLE ... ADD COLUMN)
        Devuelve la lista de cambios hechos.
        """
        cambios = []
        existentes = {f["tabla"] for f in self.sql("SHOW TABLES")}
        for modelo in modelos:
            if modelo._tabla not in existentes:
                self.crear_tablas(modelo)
                cambios.append(f"tabla '{modelo._tabla}' creada")
                continue
            actuales = {f["columna"] for f in self.sql(f"DESCRIBE {modelo._tabla}")}
            for campo in modelo._campos.values():
                if campo.columna in actuales:
                    continue
                if campo.primaria:
                    raise ErrorORM(f"la columna {modelo._tabla}.{campo.columna} es la clave primaria: "
                                   f"no se puede añadir con una migración")
                if isinstance(campo, ClaveForanea) and campo.obligatorio:
                    raise ErrorORM(f"{modelo._tabla}.{campo.columna} es una relación obligatoria: "
                                   f"las filas que ya existen no tendrían valor")
                self._ejecutar(f"ALTER TABLE {modelo._tabla} ADD COLUMN {campo.definicion_sql()}").close()
                cambios.append(f"columna '{campo.columna}' añadida a '{modelo._tabla}'")
        return cambios

    def borrar_tablas(self, *modelos):
        """Borra las tablas (en orden inverso, para respetar las claves foráneas)."""
        for modelo in reversed(modelos):
            self._ejecutar(f"DROP TABLE IF EXISTS {modelo._tabla}").close()
        self._mapa.clear()

    # ------------------------------------------------- Unidad de trabajo
    def agregar(self, *objetos):
        """Apunta objetos nuevos para guardarlos en el próximo confirmar()."""
        for objeto in objetos:
            if objeto._estado == "borrado":
                raise ErrorORM("ese objeto ya se borró")
            object.__setattr__(objeto, "_sesion", self)
            if objeto._estado == "nuevo" and objeto not in self._nuevos:
                self._nuevos.append(objeto)
            # En cascada: los objetos relacionados que aún no están guardados
            for relacionado in objeto._referencias.values():
                if relacionado._estado == "nuevo":
                    self.agregar(relacionado)

    def borrar(self, objeto):
        """Apunta un objeto para borrarlo en el próximo confirmar()."""
        if objeto._estado == "nuevo":
            if objeto in self._nuevos:
                self._nuevos.remove(objeto)
            return
        if objeto not in self._borrados:
            self._borrados.append(objeto)

    def hay_cambios(self):
        return bool(self._nuevos or self._borrados or self._modificados())

    def _modificados(self):
        return [o for o in self._mapa.values() if o._estado == "persistente" and o._cambios]

    def confirmar(self):
        """Guarda TODOS los cambios pendientes dentro de una transacción (o todo o nada)."""
        if not self.hay_cambios():
            return
        insertados = []
        self._log("BEGIN")
        self._conexion.begin()
        try:
            for objeto in list(self._nuevos):
                self._insertar(objeto, insertados)
            for objeto in self._modificados():
                self._actualizar(objeto)
            for objeto in self._borrados:
                self._eliminar(objeto)
            self._log("COMMIT")
            self._conexion.commit()
        except (ErrorORM, conector.ErrorEstadio) as e:
            self._log("ROLLBACK")
            self._conexion.rollback()
            # Los objetos insertados vuelven a estar "sin guardar"
            for objeto in insertados:
                self._mapa.pop((type(objeto), objeto._valor_primaria()), None)
                objeto.__dict__[objeto._primaria.columna] = None
                object.__setattr__(objeto, "_estado", "nuevo")
            raise ErrorORM(f"no se ha guardado nada: {e}") from e

        # Todo bien: limpiar las listas de pendientes
        self._nuevos.clear()
        for objeto in self._mapa.values():
            objeto._cambios.clear()
        for objeto in self._borrados:
            self._mapa.pop((type(objeto), objeto._valor_primaria()), None)
            object.__setattr__(objeto, "_estado", "borrado")
        self._borrados.clear()

    def deshacer(self):
        """Descarta los cambios pendientes y recarga desde la base de datos los objetos modificados."""
        for objeto in self._nuevos:
            object.__setattr__(objeto, "_sesion", None)
        self._nuevos.clear()
        self._borrados.clear()
        for objeto in self._modificados():
            self._recargar(objeto)

    @contextmanager
    def transaccion(self):
        """
        with sesion.transaccion():
            ...cambios...
        Si todo va bien, confirma. Si hay un error, deshace y lo vuelve a lanzar.
        """
        try:
            yield self
            self.confirmar()
        except Exception:
            self.deshacer()
            raise

    def _log(self, texto):
        self.registro.append(texto)
        if self.mostrar_sql:
            print("   [SQL]", texto)

    # --------------------------------------------- INSERT / UPDATE / DELETE
    def _insertar(self, objeto, insertados):
        if objeto._estado != "nuevo":
            return
        modelo = type(objeto)
        # Primero, los objetos a los que apunta (necesitamos su id)
        for columna, relacionado in list(objeto._referencias.items()):
            if relacionado._estado == "nuevo":
                self.agregar(relacionado)
                self._insertar(relacionado, insertados)
            objeto.__dict__[columna] = relacionado._valor_primaria()
        for campo in modelo._campos.values():
            if isinstance(campo, ClaveForanea) and campo.obligatorio and objeto.__dict__.get(campo.columna) is None:
                raise ErrorORM(f"{modelo.__name__}.{campo.nombre} es obligatorio")
        self._validar(objeto)

        columnas, valores = [], []
        for columna, campo in modelo._columnas.items():
            valor = objeto.__dict__.get(columna)
            if campo.primaria and valor is None:
                continue  # la base de datos le dará un id
            if valor is None:
                continue  # clave foránea vacía: no se admite NULL, se deja fuera
            columnas.append(columna)
            valores.append(campo.a_bd(valor))
        marcas = ", ".join("?" for _ in columnas)
        cursor = self._ejecutar(f"INSERT INTO {modelo._tabla} ({', '.join(columnas)}) VALUES ({marcas})", valores)
        nuevo_id = cursor.lastrowid
        cursor.close()

        objeto.__dict__[modelo._primaria.columna] = nuevo_id
        object.__setattr__(objeto, "_estado", "persistente")
        object.__setattr__(objeto, "_sesion", self)
        objeto._cambios.clear()
        objeto._referencias.clear()
        self._mapa[(modelo, nuevo_id)] = objeto
        insertados.append(objeto)

    @staticmethod
    def _validar(objeto):
        """Si el modelo define antes_de_guardar(), se llama: así cada clase puede poner sus reglas."""
        validador = getattr(objeto, "antes_de_guardar", None)
        if callable(validador):
            validador()

    def _actualizar(self, objeto):
        self._validar(objeto)
        modelo = type(objeto)
        cambios = sorted(objeto._cambios)
        asignaciones = ", ".join(f"{c} = ?" for c in cambios)
        valores = [modelo._columnas[c].a_bd(objeto.__dict__[c]) for c in cambios]
        valores.append(objeto._valor_primaria())
        self._ejecutar(f"UPDATE {modelo._tabla} SET {asignaciones} WHERE {modelo._primaria.columna} = ?", valores).close()

    def _eliminar(self, objeto):
        modelo = type(objeto)
        self._ejecutar(f"DELETE FROM {modelo._tabla} WHERE {modelo._primaria.columna} = ?",
                       (objeto._valor_primaria(),)).close()

    # ------------------------------------------------------------ Lectura
    def _materializar(self, modelo, columnas, fila):
        """Fila de la base de datos -> objeto (reutilizando el que ya esté cargado)."""
        datos = dict(zip(columnas, fila))
        pk = datos.get(modelo._primaria.columna)
        if pk is None:
            raise ErrorORM(f"la consulta no devuelve la clave primaria de {modelo.__name__}")
        existente = self._mapa.get((modelo, pk))
        if existente is not None:
            return existente
        objeto = modelo.__new__(modelo)
        objeto._preparar()
        for columna, campo in modelo._columnas.items():
            objeto.__dict__[columna] = campo.a_python(datos[columna]) if columna in datos else None
        object.__setattr__(objeto, "_estado", "persistente")
        object.__setattr__(objeto, "_sesion", self)
        self._mapa[(modelo, pk)] = objeto
        return objeto

    def _recargar(self, objeto):
        modelo = type(objeto)
        cursor = self._ejecutar(f"SELECT * FROM {modelo._tabla} WHERE {modelo._primaria.columna} = ?",
                                (objeto._valor_primaria(),))
        fila = cursor.fetchone()
        if fila is not None:
            for columna, valor in zip(cursor.columnas, fila):
                if columna in modelo._columnas:
                    objeto.__dict__[columna] = modelo._columnas[columna].a_python(valor)
        cursor.close()
        objeto._cambios.clear()
        objeto._referencias.clear()

    def obtener(self, modelo, id_):
        """Busca un objeto por su clave primaria. Devuelve None si no existe."""
        if (modelo, id_) in self._mapa:
            return self._mapa[(modelo, id_)]
        return self.consulta(modelo).filtrar(**{modelo._primaria.nombre: id_}).primero()

    def consulta(self, modelo):
        """Empieza una consulta:  sesion.consulta(Socio).filtrar(...).ordenar(...).todos()"""
        return Consulta(self, modelo)

    # -------------------------------------------------------------- Cierre
    def cerrar(self):
        if self._nuevos or self._borrados or self._modificados():
            print("   [ORM] aviso: se cierra la sesión con cambios sin confirmar (se pierden)")
        self._mapa.clear()
        self._nuevos.clear()
        self._borrados.clear()
        self._conexion.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cerrar()
        return False


class Consulta:
    """Construye un SELECT a base de métodos encadenados. No toca la base de datos hasta todos()/primero()/contar()."""

    def __init__(self, sesion, modelo):
        self._sesion = sesion
        self._modelo = modelo
        self._condiciones = []   # (columna, operador, valor)
        self._orden = None
        self._limite = None

    def _columna_y_valor(self, nombre, valor):
        campo = self._modelo._campos.get(nombre) or self._modelo._columnas.get(nombre)
        if campo is None:
            raise ErrorORM(f"{self._modelo.__name__} no tiene el campo '{nombre}'")
        if isinstance(campo, ClaveForanea) and hasattr(valor, "_valor_primaria"):
            valor = valor._valor_primaria()  # filtrar(equipo=objeto) -> equipo_id = su id
        return campo.columna, campo.a_bd(valor)

    def filtrar(self, *condicion, **iguales):
        """
        filtrar(nombre="Ana")              -> WHERE nombre = 'Ana'
        filtrar("importe", ">=", 30)       -> WHERE importe >= 30
        filtrar(equipo=alevines)           -> WHERE equipo_id = 1
        """
        if condicion:
            if len(condicion) != 3:
                raise ErrorORM("usa filtrar(campo, operador, valor)")
            nombre, operador, valor = condicion
            if operador.upper() not in OPERADORES:
                raise ErrorORM(f"operador no válido: {operador}")
            columna, valor = self._columna_y_valor(nombre, valor)
            self._condiciones.append((columna, operador.upper(), valor))
        for nombre, valor in iguales.items():
            columna, valor = self._columna_y_valor(nombre, valor)
            self._condiciones.append((columna, "=", valor))
        return self

    def buscar(self, nombre, texto):
        """buscar("nombre", "ana") -> WHERE nombre LIKE '%ana%'"""
        return self.filtrar(nombre, "LIKE", f"%{texto}%")

    def ordenar(self, nombre):
        """ordenar("nombre") de A a Z;  ordenar("-importe") de mayor a menor."""
        descendente = nombre.startswith("-")
        campo = self._modelo._campos.get(nombre.lstrip("-")) or self._modelo._columnas.get(nombre.lstrip("-"))
        if campo is None:
            raise ErrorORM(f"{self._modelo.__name__} no tiene el campo '{nombre.lstrip('-')}'")
        self._orden = campo.columna + (" DESC" if descendente else "")
        return self

    def limite(self, cantidad):
        self._limite = int(cantidad)
        return self

    def _sql(self, seleccion):
        sql = f"SELECT {seleccion} FROM {self._modelo._tabla}"
        parametros = []
        if self._condiciones:
            partes = []
            for columna, operador, valor in self._condiciones:
                partes.append(f"{columna} {operador} ?")
                parametros.append(valor)
            sql += " WHERE " + " AND ".join(partes)
        return sql, parametros

    def todos(self):
        sql, parametros = self._sql("*")
        if self._orden:
            sql += f" ORDER BY {self._orden}"
        if self._limite is not None:
            sql += f" LIMIT {self._limite}"
        return self._sesion.sql_objetos(self._modelo, sql, parametros)

    def primero(self):
        self._limite = 1
        resultado = self.todos()
        return resultado[0] if resultado else None

    def contar(self):
        sql, parametros = self._sql("COUNT(*)")
        return self._sesion.sql(sql, parametros)[0]["total"]

    def __iter__(self):
        return iter(self.todos())
