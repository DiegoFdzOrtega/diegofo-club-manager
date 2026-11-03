// =====================================================================
//  diegofo | estadio  2.0  -  motor de base de datos relacional en C++
//  RA3 · Acceso a datos (0486) · Diego Fernández Ortega
//
//  Novedades de la versión 2 (pensadas para poder usar un ORM encima):
//    - Claves primarias:      id INT PRIMARY KEY   (se numeran solas)
//    - Claves foráneas:       equipo_id INT REFERENCES equipos(id)   (0 = sin relación)
//    - INSERT con columnas:   INSERT INTO t (a, b) VALUES (...)  -> devuelve el id nuevo
//    - JOIN entre tablas:     SELECT ... FROM a JOIN b ON a.x = b.id
//    - Funciones de grupo:    COUNT(*), SUM(col) con GROUP BY y alias (AS)
//    - Búsquedas con LIKE:    WHERE nombre LIKE '%ana%'
//    - Migraciones:           ALTER TABLE socios ADD COLUMN iban TEXT
//
//  Uso:
//    estadio <carpeta_de_la_base>          -> modo consola (para personas)
//    estadio <carpeta_de_la_base> --json   -> modo conector (para programas)
// =====================================================================

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

using namespace std;
namespace fs = std::filesystem;

const string VERSION = "2.1";

// ---------------------------------------------------------------------
// Estructuras de datos
// ---------------------------------------------------------------------

enum class Tipo { INT, TEXT };

struct Columna {
    string nombre;
    Tipo tipo;
    bool primaria = false;  // PRIMARY KEY
    string refTabla;        // REFERENCES refTabla(refColumna)
    string refColumna;
};

struct Tabla {
    string nombre;
    vector<Columna> columnas;
    vector<vector<string>> filas;  // todos los valores se guardan como texto

    int indiceDe(const string& col) const {
        for (size_t i = 0; i < columnas.size(); i++) {
            if (columnas[i].nombre == col) return (int)i;
        }
        // También vale "tabla.columna"
        size_t punto = col.find('.');
        if (punto != string::npos && col.substr(0, punto) == nombre) return indiceDe(col.substr(punto + 1));
        return -1;
    }
    int indicePrimaria() const {
        for (size_t i = 0; i < columnas.size(); i++) {
            if (columnas[i].primaria) return (int)i;
        }
        return -1;
    }
};

struct Procedimiento {
    string nombre;
    int numParametros = 0;
    string cuerpo;  // una o varias órdenes separadas por ';' con $1, $2...
};

// Lo que devuelve cada orden
struct Resultado {
    vector<string> columnas;
    vector<Tipo> tipos;
    vector<vector<string>> filas;
    int afectadas = 0;
    long long ultimoId = -1;  // id generado por el último INSERT
    string mensaje;
    bool esConsulta = false;
};

// Error "controlado" de la base de datos (orden mal escrita, tabla que no existe...)
class ErrorBD : public runtime_error {
public:
    explicit ErrorBD(const string& m) : runtime_error(m) {}
};

// ---------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------

string mayusculas(string s) {
    for (char& c : s) c = (char)toupper((unsigned char)c);
    return s;
}

string minusculas(string s) {
    for (char& c : s) c = (char)tolower((unsigned char)c);
    return s;
}

// Número de caracteres reales de un texto UTF-8 (la "á" ocupa 2 bytes pero es 1 letra)
size_t largoUtf8(const string& s) {
    size_t n = 0;
    for (unsigned char c : s) {
        if ((c & 0xC0) != 0x80) n++;
    }
    return n;
}

bool esEntero(const string& s) {
    if (s.empty()) return false;
    size_t i = (s[0] == '-') ? 1 : 0;
    if (i == s.size()) return false;
    for (; i < s.size(); i++) {
        if (!isdigit((unsigned char)s[i])) return false;
    }
    return true;
}

// LIKE: % = cualquier cosa (también nada), _ = un carácter. Sin distinguir mayúsculas.
bool coincideLike(const string& texto, const string& patron) {
    string t = minusculas(texto), p = minusculas(patron);
    size_t i = 0, j = 0, estrella = string::npos, marca = 0;
    while (i < t.size()) {
        if (j < p.size() && (p[j] == '_' || p[j] == t[i])) { i++; j++; }
        else if (j < p.size() && p[j] == '%') { estrella = j++; marca = i; }
        else if (estrella != string::npos) { j = estrella + 1; i = ++marca; }
        else return false;
    }
    while (j < p.size() && p[j] == '%') j++;
    return j == p.size();
}

// En el fichero, cada fila es una línea con los valores separados por '|'.
// Si un valor contiene '|', '\' o un salto de línea, se "escapa".
string escapar(const string& s) {
    string r;
    for (char c : s) {
        if (c == '\\') r += "\\\\";
        else if (c == '|') r += "\\p";
        else if (c == '\n') r += "\\n";
        else r += c;
    }
    return r;
}

string desescapar(const string& s) {
    string r;
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '\\' && i + 1 < s.size()) {
            char sig = s[++i];
            if (sig == 'p') r += '|';
            else if (sig == 'n') r += '\n';
            else r += sig;
        } else {
            r += s[i];
        }
    }
    return r;
}

vector<string> partir(const string& linea, char sep) {
    vector<string> partes;
    string actual;
    for (size_t i = 0; i < linea.size(); i++) {
        if (linea[i] == '\\' && i + 1 < linea.size()) {
            actual += linea[i];
            actual += linea[++i];
        } else if (linea[i] == sep) {
            partes.push_back(actual);
            actual.clear();
        } else {
            actual += linea[i];
        }
    }
    partes.push_back(actual);
    return partes;
}

string jsonTexto(const string& s) {
    string r = "\"";
    for (char c : s) {
        switch (c) {
            case '"': r += "\\\""; break;
            case '\\': r += "\\\\"; break;
            case '\n': r += "\\n"; break;
            case '\r': r += "\\r"; break;
            case '\t': r += "\\t"; break;
            default: r += c;
        }
    }
    return r + "\"";
}

// ---------------------------------------------------------------------
// Analizador léxico: convierte el texto de una orden en "tokens"
//   SELECT nombre FROM socios WHERE cuota > 5
//   -> [SELECT] [nombre] [FROM] [socios] [WHERE] [cuota] [>] [5]
// ---------------------------------------------------------------------

enum class TT { PALABRA, NUMERO, TEXTO, SIMBOLO, PARAMETRO, FIN };

struct Token {
    TT tipo;
    string valor;
    size_t inicio;  // posición en el texto original
};

vector<Token> tokenizar(const string& s) {
    vector<Token> tokens;
    size_t i = 0;
    while (i < s.size()) {
        unsigned char c = s[i];
        if (isspace(c)) { i++; continue; }
        size_t inicio = i;

        // Texto entre comillas simples: 'Ana López'  ('' dentro = una comilla)
        if (c == '\'') {
            string v;
            i++;
            while (true) {
                if (i >= s.size()) throw ErrorBD("falta cerrar una comilla");
                if (s[i] == '\'') {
                    if (i + 1 < s.size() && s[i + 1] == '\'') { v += '\''; i += 2; continue; }
                    i++;
                    break;
                }
                v += s[i++];
            }
            tokens.push_back({TT::TEXTO, v, inicio});
            continue;
        }
        // Número (puede ser negativo)
        if (isdigit(c) || (c == '-' && i + 1 < s.size() && isdigit((unsigned char)s[i + 1]))) {
            string v(1, (char)c);
            i++;
            while (i < s.size() && isdigit((unsigned char)s[i])) v += s[i++];
            tokens.push_back({TT::NUMERO, v, inicio});
            continue;
        }
        // Parámetro de procedimiento: $1, $2...
        if (c == '$') {
            string v;
            i++;
            while (i < s.size() && isdigit((unsigned char)s[i])) v += s[i++];
            if (v.empty()) throw ErrorBD("parámetro mal escrito: usa $1, $2...");
            tokens.push_back({TT::PARAMETRO, v, inicio});
            continue;
        }
        // Palabra: nombres de tablas, columnas (también tabla.columna) y palabras clave
        if (isalpha(c) || c == '_' || c >= 0x80) {
            string v;
            while (i < s.size()) {
                unsigned char d = s[i];
                bool puntoValido = (d == '.' && i + 1 < s.size() &&
                                    (isalpha((unsigned char)s[i + 1]) || s[i + 1] == '_'));
                if (isalnum(d) || d == '_' || d >= 0x80 || puntoValido) v += s[i++];
                else break;
            }
            tokens.push_back({TT::PALABRA, v, inicio});
            continue;
        }
        // Símbolos de dos caracteres
        if (i + 1 < s.size()) {
            string dos = s.substr(i, 2);
            if (dos == "<=" || dos == ">=" || dos == "!=" || dos == "<>") {
                tokens.push_back({TT::SIMBOLO, dos == "<>" ? "!=" : dos, inicio});
                i += 2;
                continue;
            }
        }
        // Símbolos de un caracter
        if (string("(),*;=<>").find((char)c) != string::npos) {
            tokens.push_back({TT::SIMBOLO, string(1, (char)c), inicio});
            i++;
            continue;
        }
        throw ErrorBD(string("carácter no válido: ") + (char)c);
    }
    tokens.push_back({TT::FIN, "", s.size()});
    return tokens;
}

// ---------------------------------------------------------------------
// Ayudante para recorrer los tokens
// ---------------------------------------------------------------------

class Lector {
public:
    explicit Lector(const vector<Token>& t) : tokens(t) {}

    const Token& actual() const { return tokens[pos]; }
    Token siguiente() { return tokens[pos++]; }

    bool esPalabra(const string& clave) const {
        return actual().tipo == TT::PALABRA && mayusculas(actual().valor) == clave;
    }
    bool esSimbolo(const string& s) const {
        return actual().tipo == TT::SIMBOLO && actual().valor == s;
    }
    bool aceptarPalabra(const string& clave) {
        if (esPalabra(clave)) { pos++; return true; }
        return false;
    }
    bool aceptarSimbolo(const string& s) {
        if (esSimbolo(s)) { pos++; return true; }
        return false;
    }
    void esperarPalabra(const string& clave) {
        if (!aceptarPalabra(clave)) throw ErrorBD("se esperaba " + clave + cerca());
    }
    void esperarSimbolo(const string& s) {
        if (!aceptarSimbolo(s)) throw ErrorBD("se esperaba '" + s + "'" + cerca());
    }
    string nombre() {
        if (actual().tipo != TT::PALABRA) throw ErrorBD("se esperaba un nombre" + cerca());
        return siguiente().valor;
    }
    // Un valor literal: número o texto
    Token valor() {
        if (actual().tipo == TT::NUMERO || actual().tipo == TT::TEXTO) return siguiente();
        if (esPalabra("NULL")) throw ErrorBD("esta base de datos no admite NULL");
        throw ErrorBD("se esperaba un valor" + cerca());
    }
    void esperarFin() {
        aceptarSimbolo(";");
        if (actual().tipo != TT::FIN) throw ErrorBD("sobra texto al final" + cerca());
    }
    string cerca() const {
        if (actual().tipo == TT::FIN) return " (al final de la orden)";
        return " cerca de '" + actual().valor + "'";
    }
    size_t posicionTexto() const { return actual().inicio; }

private:
    const vector<Token>& tokens;
    size_t pos = 0;
};

// ---------------------------------------------------------------------
// Vista: el resultado intermedio de un SELECT (una tabla o varias unidas)
// Las columnas se llaman "tabla.columna" para que no se confundan.
// ---------------------------------------------------------------------

struct Vista {
    vector<string> nombres;  // "socios.nombre"
    vector<Tipo> tipos;
    vector<vector<string>> filas;

    // Busca una columna por "tabla.col" o solo "col" (si no hay dos iguales)
    int indice(const string& col) const {
        if (col.find('.') != string::npos) {
            for (size_t i = 0; i < nombres.size(); i++)
                if (nombres[i] == col) return (int)i;
            return -1;
        }
        int encontrado = -1;
        for (size_t i = 0; i < nombres.size(); i++) {
            const string& n = nombres[i];
            size_t p = n.find('.');
            if (n.substr(p + 1) == col) {
                if (encontrado != -1) throw ErrorBD("la columna '" + col + "' está en varias tablas: usa tabla." + col);
                encontrado = (int)i;
            }
        }
        return encontrado;
    }
    int indiceObligatorio(const string& col) const {
        int i = indice(col);
        if (i == -1) throw ErrorBD("la columna '" + col + "' no existe");
        return i;
    }
};

Vista vistaDe(const Tabla& t) {
    Vista v;
    for (auto& c : t.columnas) {
        v.nombres.push_back(t.nombre + "." + c.nombre);
        v.tipos.push_back(c.tipo);
    }
    v.filas = t.filas;
    return v;
}

// Condición del WHERE: columna operador valor
struct Condicion {
    int columna;
    string op;
    string valor;
};

// Compara dos valores según el tipo de la columna: -1, 0 o 1
int comparar(const string& a, const string& b, Tipo tipo) {
    if (tipo == Tipo::INT) {
        long long x = stoll(a), y = stoll(b);
        return (x < y) ? -1 : (x > y ? 1 : 0);
    }
    return (a < b) ? -1 : (a > b ? 1 : 0);
}

bool cumple(const vector<string>& fila, const vector<Condicion>& conds, const vector<Tipo>& tipos) {
    for (const auto& c : conds) {
        if (c.op == "LIKE") {
            if (!coincideLike(fila[c.columna], c.valor)) return false;
            continue;
        }
        int cmp = comparar(fila[c.columna], c.valor, tipos[c.columna]);
        bool ok = (c.op == "=" && cmp == 0) || (c.op == "!=" && cmp != 0) ||
                  (c.op == "<" && cmp < 0) || (c.op == ">" && cmp > 0) ||
                  (c.op == "<=" && cmp <= 0) || (c.op == ">=" && cmp >= 0);
        if (!ok) return false;
    }
    return true;
}

// Un elemento de la lista del SELECT
struct ElementoSelect {
    enum Clase { COLUMNA, COUNT, SUM } clase;
    int columna = -1;   // en la vista (no se usa en COUNT)
    string salida;      // nombre que se verá en el resultado
};

// ---------------------------------------------------------------------
// La base de datos
// ---------------------------------------------------------------------

class BaseDeDatos {
public:
    explicit BaseDeDatos(const string& carpeta) : dir(carpeta) {
        if (!fs::exists(dir)) fs::create_directories(dir);
        if (!fs::is_directory(dir)) throw ErrorBD("'" + carpeta + "' no es una carpeta");
        cargar();
    }

    bool enTransaccion() const { return transaccion; }

    // Ejecuta una orden (una línea de texto) y devuelve el resultado
    Resultado ejecutar(const string& orden, int profundidad = 0) {
        if (profundidad > 10) throw ErrorBD("demasiados procedimientos anidados");
        vector<Token> tokens = tokenizar(orden);
        Lector l(tokens);
        if (l.actual().tipo == TT::FIN) throw ErrorBD("orden vacía");

        if (l.aceptarPalabra("CREATE")) {
            if (l.aceptarPalabra("TABLE")) return crearTabla(l);
            if (l.aceptarPalabra("PROCEDURE")) return crearProcedimiento(l, orden);
            throw ErrorBD("después de CREATE va TABLE o PROCEDURE");
        }
        if (l.aceptarPalabra("DROP")) {
            if (l.aceptarPalabra("TABLE")) return borrarTabla(l);
            if (l.aceptarPalabra("PROCEDURE")) return borrarProcedimiento(l);
            throw ErrorBD("después de DROP va TABLE o PROCEDURE");
        }
        if (l.aceptarPalabra("ALTER")) return alterarTabla(l);
        if (l.aceptarPalabra("INSERT")) return insertar(l);
        if (l.aceptarPalabra("SELECT")) return seleccionar(l);
        if (l.aceptarPalabra("UPDATE")) return actualizar(l);
        if (l.aceptarPalabra("DELETE")) return eliminar(l);
        if (l.aceptarPalabra("CALL")) return llamar(l, profundidad);
        if (l.aceptarPalabra("BEGIN") || (l.aceptarPalabra("START") && (l.esperarPalabra("TRANSACTION"), true))) {
            l.esperarFin();
            return empezarTransaccion();
        }
        if (l.aceptarPalabra("COMMIT")) { l.esperarFin(); return confirmar(); }
        if (l.aceptarPalabra("ROLLBACK")) { l.esperarFin(); return deshacer(); }
        if (l.aceptarPalabra("SHOW")) return mostrar(l);
        if (l.aceptarPalabra("DESCRIBE")) return describir(l);
        throw ErrorBD("orden desconocida: " + l.actual().valor);
    }

private:
    fs::path dir;
    map<string, Tabla> tablas;
    map<string, Procedimiento> procedimientos;

    // Transacciones: copia de seguridad en memoria al hacer BEGIN
    bool transaccion = false;
    map<string, Tabla> copiaTablas;
    map<string, Procedimiento> copiaProcedimientos;

    Tabla& tabla(const string& nombre) {
        auto it = tablas.find(nombre);
        if (it == tablas.end()) throw ErrorBD("la tabla '" + nombre + "' no existe");
        return it->second;
    }

    int columnaDe(const Tabla& t, const string& col) {
        int i = t.indiceDe(col);
        if (i == -1) throw ErrorBD("la columna '" + col + "' no existe en '" + t.nombre + "'");
        return i;
    }

    // Comprueba que un valor encaja con el tipo de la columna y lo devuelve como texto
    static string convertir(const Token& t, Tipo tipo, const string& nombreCol) {
        if (tipo == Tipo::INT) {
            if (t.tipo != TT::NUMERO) {
                throw ErrorBD("la columna '" + nombreCol + "' es INT y '" + t.valor + "' no es un número entero");
            }
            return to_string(stoll(t.valor));  // normaliza: "007" -> "7"
        }
        return t.valor;  // TEXT admite texto y números
    }

    // ¿Existe en 'destino' una fila con ese valor en esa columna?
    bool existeValor(const string& tablaDestino, const string& col, const string& valor) {
        Tabla& d = tabla(tablaDestino);
        int i = columnaDe(d, col);
        for (auto& f : d.filas)
            if (f[i] == valor) return true;
        return false;
    }

    // Integridad referencial: las claves foráneas deben apuntar a algo que exista
    void comprobarForaneas(const Tabla& t, const vector<string>& fila) {
        for (size_t i = 0; i < t.columnas.size(); i++) {
            const Columna& c = t.columnas[i];
            if (c.refTabla.empty()) continue;
            if (fila[i] == "0") continue;  // 0 = clave foránea vacía (sin relación)
            if (!existeValor(c.refTabla, c.refColumna, fila[i])) {
                throw ErrorBD("clave foránea: no existe " + c.refTabla + "." + c.refColumna + " = " + fila[i] +
                              " (columna " + t.nombre + "." + c.nombre + ")");
            }
        }
    }

    // Antes de borrar filas de 't', comprobar que nadie las está usando
    void comprobarQueNadieLasUsa(const Tabla& t, const vector<vector<string>>& aBorrar) {
        for (auto& [nombre, otra] : tablas) {
            for (size_t i = 0; i < otra.columnas.size(); i++) {
                const Columna& c = otra.columnas[i];
                if (c.refTabla != t.nombre) continue;
                int ref = t.indiceDe(c.refColumna);
                for (auto& borrada : aBorrar) {
                    for (auto& f : otra.filas) {
                        if (f[i] == borrada[ref]) {
                            throw ErrorBD("no se puede borrar: " + nombre + "." + c.nombre + " = " + borrada[ref] +
                                          " depende de esa fila de '" + t.nombre + "'");
                        }
                    }
                }
            }
        }
    }

    // ------------------------------- CREATE TABLE
    // CREATE TABLE socios (id INT PRIMARY KEY, nombre TEXT, equipo_id INT REFERENCES equipos(id))
    Resultado crearTabla(Lector& l) {
        string nombre = l.nombre();
        for (unsigned char c : nombre) {
            // El nombre se usa para el fichero: solo letras sin tilde, números y _
            if (!isalnum(c) && c != '_') throw ErrorBD("nombre de tabla no válido: usa letras sin tildes, números y _");
        }
        if (tablas.count(nombre)) throw ErrorBD("la tabla '" + nombre + "' ya existe");
        Tabla t;
        t.nombre = nombre;
        l.esperarSimbolo("(");
        do {
            Columna c;
            c.nombre = l.nombre();
            if (c.nombre.find('.') != string::npos) throw ErrorBD("un nombre de columna no puede llevar punto");
            string tipo = mayusculas(l.nombre());
            if (tipo == "INT" || tipo == "INTEGER") c.tipo = Tipo::INT;
            else if (tipo == "TEXT" || tipo == "VARCHAR") c.tipo = Tipo::TEXT;
            else throw ErrorBD("tipo desconocido '" + tipo + "' (usa INT o TEXT)");

            if (l.aceptarPalabra("PRIMARY")) {
                l.esperarPalabra("KEY");
                if (c.tipo != Tipo::INT) throw ErrorBD("la clave primaria debe ser INT");
                if (t.indicePrimaria() != -1) throw ErrorBD("solo puede haber una clave primaria");
                c.primaria = true;
            }
            if (l.aceptarPalabra("REFERENCES")) {
                c.refTabla = l.nombre();
                l.esperarSimbolo("(");
                c.refColumna = l.nombre();
                l.esperarSimbolo(")");
                Tabla& destino = tabla(c.refTabla);
                int ref = columnaDe(destino, c.refColumna);
                if (!destino.columnas[ref].primaria) throw ErrorBD("REFERENCES debe apuntar a una clave primaria");
                if (destino.columnas[ref].tipo != c.tipo) throw ErrorBD("la clave foránea debe ser del mismo tipo");
            }
            if (t.indiceDe(c.nombre) != -1) throw ErrorBD("columna repetida: " + c.nombre);
            t.columnas.push_back(c);
        } while (l.aceptarSimbolo(","));
        l.esperarSimbolo(")");
        l.esperarFin();
        tablas[nombre] = t;
        guardarSiNoHayTransaccion();
        Resultado r;
        r.mensaje = "tabla '" + nombre + "' creada con " + to_string(t.columnas.size()) + " columnas";
        return r;
    }

    // ------------------------------- ALTER TABLE t ADD [COLUMN] col TIPO
    // Añade una columna a una tabla que ya tiene datos (migraciones).
    // Las filas que ya existen reciben el valor por defecto: 0 o ''.
    Resultado alterarTabla(Lector& l) {
        l.esperarPalabra("TABLE");
        Tabla& t = tabla(l.nombre());
        l.esperarPalabra("ADD");
        l.aceptarPalabra("COLUMN");
        Columna c;
        c.nombre = l.nombre();
        if (c.nombre.find('.') != string::npos) throw ErrorBD("un nombre de columna no puede llevar punto");
        if (t.indiceDe(c.nombre) != -1) throw ErrorBD("la columna '" + c.nombre + "' ya existe en '" + t.nombre + "'");
        string tipo = mayusculas(l.nombre());
        if (tipo == "INT" || tipo == "INTEGER") c.tipo = Tipo::INT;
        else if (tipo == "TEXT" || tipo == "VARCHAR") c.tipo = Tipo::TEXT;
        else throw ErrorBD("tipo desconocido '" + tipo + "' (usa INT o TEXT)");
        if (l.esPalabra("PRIMARY")) throw ErrorBD("ALTER TABLE no puede añadir una clave primaria");
        if (l.aceptarPalabra("REFERENCES")) {
            // Las filas que ya existen quedan con 0 = "sin relación"
            c.refTabla = l.nombre();
            l.esperarSimbolo("(");
            c.refColumna = l.nombre();
            l.esperarSimbolo(")");
            Tabla& destino = tabla(c.refTabla);
            int ref = columnaDe(destino, c.refColumna);
            if (!destino.columnas[ref].primaria) throw ErrorBD("REFERENCES debe apuntar a una clave primaria");
            if (c.tipo != Tipo::INT) throw ErrorBD("la clave foránea debe ser INT");
        }
        l.esperarFin();
        t.columnas.push_back(c);
        for (auto& f : t.filas) f.push_back(c.tipo == Tipo::INT ? "0" : "");
        guardarSiNoHayTransaccion();
        Resultado r;
        r.mensaje = "columna '" + c.nombre + "' añadida a '" + t.nombre + "'";
        return r;
    }

    // ------------------------------- DROP TABLE
    Resultado borrarTabla(Lector& l) {
        bool siExiste = false;
        if (l.aceptarPalabra("IF")) { l.esperarPalabra("EXISTS"); siExiste = true; }
        string nombre = l.nombre();
        l.esperarFin();
        Resultado r;
        if (!tablas.count(nombre)) {
            if (siExiste) { r.mensaje = "la tabla '" + nombre + "' no existía"; return r; }
            throw ErrorBD("la tabla '" + nombre + "' no existe");
        }
        for (auto& [otroNombre, otra] : tablas) {
            if (otroNombre == nombre) continue;
            for (auto& c : otra.columnas) {
                if (c.refTabla == nombre) {
                    throw ErrorBD("no se puede borrar '" + nombre + "': la tabla '" + otroNombre + "' la usa");
                }
            }
        }
        tablas.erase(nombre);
        guardarSiNoHayTransaccion();
        r.mensaje = "tabla '" + nombre + "' borrada";
        return r;
    }

    // ------------------------------- INSERT INTO t [(cols)] VALUES (...), (...)
    // Las columnas que no se indican toman un valor por defecto:
    //   la clave primaria -> el siguiente número libre; INT -> 0; TEXT -> ''
    Resultado insertar(Lector& l) {
        l.esperarPalabra("INTO");
        Tabla& t = tabla(l.nombre());

        vector<int> indices;
        if (l.aceptarSimbolo("(")) {
            do {
                int i = columnaDe(t, l.nombre());
                if (find(indices.begin(), indices.end(), i) != indices.end()) throw ErrorBD("columna repetida en el INSERT");
                indices.push_back(i);
            } while (l.aceptarSimbolo(","));
            l.esperarSimbolo(")");
        } else {
            for (size_t i = 0; i < t.columnas.size(); i++) indices.push_back((int)i);
        }

        int pk = t.indicePrimaria();
        long long siguienteId = 1;
        if (pk != -1) {
            for (auto& f : t.filas) siguienteId = max(siguienteId, stoll(f[pk]) + 1);
        }

        l.esperarPalabra("VALUES");
        vector<vector<string>> nuevas;
        long long ultimoId = -1;
        do {
            l.esperarSimbolo("(");
            vector<Token> valores;
            do { valores.push_back(l.valor()); } while (l.aceptarSimbolo(","));
            l.esperarSimbolo(")");
            if (valores.size() != indices.size()) {
                throw ErrorBD("se esperaban " + to_string(indices.size()) + " valores y hay " + to_string(valores.size()));
            }
            // Valores por defecto
            vector<string> fila(t.columnas.size());
            vector<bool> dado(t.columnas.size(), false);
            for (size_t i = 0; i < t.columnas.size(); i++) fila[i] = (t.columnas[i].tipo == Tipo::INT) ? "0" : "";
            for (size_t k = 0; k < valores.size(); k++) {
                const Columna& c = t.columnas[indices[k]];
                fila[indices[k]] = convertir(valores[k], c.tipo, c.nombre);
                dado[indices[k]] = true;
            }
            // Clave primaria: automática o comprobada
            if (pk != -1) {
                if (!dado[pk]) {
                    fila[pk] = to_string(siguienteId);
                } else {
                    for (auto& f : t.filas)
                        if (f[pk] == fila[pk]) throw ErrorBD("clave primaria repetida: " + t.columnas[pk].nombre + " = " + fila[pk]);
                    for (auto& f : nuevas)
                        if (f[pk] == fila[pk]) throw ErrorBD("clave primaria repetida: " + t.columnas[pk].nombre + " = " + fila[pk]);
                }
                siguienteId = max(siguienteId, stoll(fila[pk]) + 1);
                ultimoId = stoll(fila[pk]);
            }
            comprobarForaneas(t, fila);
            nuevas.push_back(fila);
        } while (l.aceptarSimbolo(","));
        l.esperarFin();

        // Solo se añaden si TODAS las filas son correctas
        for (auto& f : nuevas) t.filas.push_back(f);
        guardarSiNoHayTransaccion();
        Resultado r;
        r.afectadas = (int)nuevas.size();
        r.ultimoId = ultimoId;
        r.mensaje = to_string(nuevas.size()) + " fila(s) insertada(s)";
        if (ultimoId != -1) r.mensaje += " (id " + to_string(ultimoId) + ")";
        return r;
    }

    // ------------------------------- WHERE col op valor [AND ...]
    vector<Condicion> leerWhere(Lector& l, const Vista& v) {
        vector<Condicion> conds;
        if (!l.aceptarPalabra("WHERE")) return conds;
        do {
            Condicion c;
            c.columna = v.indiceObligatorio(l.nombre());
            if (l.aceptarPalabra("LIKE")) {
                c.op = "LIKE";
                Token patron = l.valor();
                if (patron.tipo != TT::TEXTO) throw ErrorBD("LIKE necesita un texto entre comillas");
                c.valor = patron.valor;
            } else {
                if (l.actual().tipo != TT::SIMBOLO) throw ErrorBD("se esperaba un operador (=, !=, <, >, <=, >=, LIKE)" + l.cerca());
                c.op = l.siguiente().valor;
                if (c.op != "=" && c.op != "!=" && c.op != "<" && c.op != ">" && c.op != "<=" && c.op != ">=") {
                    throw ErrorBD("operador no válido: " + c.op);
                }
                c.valor = convertir(l.valor(), v.tipos[c.columna], v.nombres[c.columna]);
            }
            conds.push_back(c);
        } while (l.aceptarPalabra("AND"));
        return conds;
    }

    // ------------------------------- SELECT
    // SELECT cols | * | COUNT(*) | SUM(col) [AS alias]
    //   FROM t [JOIN t2 ON a = b]... [WHERE ...] [GROUP BY cols] [ORDER BY col [DESC]] [LIMIT n]
    Resultado seleccionar(Lector& l) {
        // 1) Leer la lista de lo que se quiere (todavía sin saber las tablas)
        struct Pedido { ElementoSelect::Clase clase; string col; string alias; };
        vector<Pedido> pedidos;
        bool todas = false;
        if (l.aceptarSimbolo("*")) {
            todas = true;
        } else {
            do {
                Pedido p;
                if (l.aceptarPalabra("COUNT")) {
                    l.esperarSimbolo("(");
                    l.esperarSimbolo("*");
                    l.esperarSimbolo(")");
                    p.clase = ElementoSelect::COUNT;
                    p.alias = "total";
                } else if (l.aceptarPalabra("SUM")) {
                    l.esperarSimbolo("(");
                    p.col = l.nombre();
                    l.esperarSimbolo(")");
                    p.clase = ElementoSelect::SUM;
                    p.alias = "suma";
                } else {
                    p.clase = ElementoSelect::COLUMNA;
                    p.col = l.nombre();
                    p.alias = p.col.substr(p.col.find('.') + 1);  // "socios.nombre" se muestra como "nombre"
                }
                if (l.aceptarPalabra("AS")) p.alias = l.nombre();
                pedidos.push_back(p);
            } while (l.aceptarSimbolo(","));
        }

        // 2) FROM y JOIN: construir la vista
        l.esperarPalabra("FROM");
        Tabla& base = tabla(l.nombre());
        Vista v = vistaDe(base);
        bool hayJoin = false;
        while (l.aceptarPalabra("JOIN") || (l.aceptarPalabra("INNER") && (l.esperarPalabra("JOIN"), true))) {
            hayJoin = true;
            Tabla& otra = tabla(l.nombre());
            Vista derecha = vistaDe(otra);
            l.esperarPalabra("ON");
            string izq = l.nombre();
            l.esperarSimbolo("=");
            string der = l.nombre();

            // Unir las columnas de las dos vistas para saber dónde está cada una
            Vista unida;
            unida.nombres = v.nombres;
            unida.nombres.insert(unida.nombres.end(), derecha.nombres.begin(), derecha.nombres.end());
            unida.tipos = v.tipos;
            unida.tipos.insert(unida.tipos.end(), derecha.tipos.begin(), derecha.tipos.end());
            int a = unida.indiceObligatorio(izq);
            int b = unida.indiceObligatorio(der);
            // Que 'a' sea de la izquierda y 'b' de la derecha
            int nIzq = (int)v.nombres.size();
            if (a >= nIzq && b < nIzq) swap(a, b);
            if (a >= nIzq || b < nIzq) throw ErrorBD("el ON debe comparar una columna de cada lado del JOIN");
            for (auto& f1 : v.filas) {
                for (auto& f2 : derecha.filas) {
                    if (f1[a] == f2[b - nIzq]) {
                        vector<string> f = f1;
                        f.insert(f.end(), f2.begin(), f2.end());
                        unida.filas.push_back(f);
                    }
                }
            }
            v = unida;
        }

        // 3) Pasar los pedidos a índices de la vista
        vector<ElementoSelect> elementos;
        bool hayAgregados = false;
        if (todas) {
            for (size_t i = 0; i < v.nombres.size(); i++) {
                string n = v.nombres[i];
                if (!hayJoin) n = n.substr(n.find('.') + 1);  // con una sola tabla: "nombre" en vez de "socios.nombre"
                elementos.push_back({ElementoSelect::COLUMNA, (int)i, n});
            }
        } else {
            for (auto& p : pedidos) {
                ElementoSelect e{p.clase, -1, p.alias};
                if (p.clase != ElementoSelect::COUNT) e.columna = v.indiceObligatorio(p.col);
                if (p.clase == ElementoSelect::SUM && v.tipos[e.columna] != Tipo::INT) throw ErrorBD("SUM solo funciona con columnas INT");
                if (p.clase != ElementoSelect::COLUMNA) hayAgregados = true;
                elementos.push_back(e);
            }
        }

        // 4) WHERE
        vector<Condicion> conds = leerWhere(l, v);
        vector<vector<string>> elegidas;
        for (auto& f : v.filas)
            if (cumple(f, conds, v.tipos)) elegidas.push_back(f);

        // 5) GROUP BY
        vector<int> grupo;
        if (l.aceptarPalabra("GROUP")) {
            l.esperarPalabra("BY");
            do { grupo.push_back(v.indiceObligatorio(l.nombre())); } while (l.aceptarSimbolo(","));
            hayAgregados = true;
        }

        Resultado r;
        r.esConsulta = true;
        for (auto& e : elementos) {
            r.columnas.push_back(e.salida);
            r.tipos.push_back(e.clase == ElementoSelect::COLUMNA ? v.tipos[e.columna] : Tipo::INT);
        }

        if (hayAgregados) {
            for (auto& e : elementos) {
                if (e.clase == ElementoSelect::COLUMNA && find(grupo.begin(), grupo.end(), e.columna) == grupo.end()) {
                    throw ErrorBD("la columna '" + e.salida + "' debe ir en el GROUP BY");
                }
            }
            // Agrupar las filas por los valores de las columnas del GROUP BY (en orden de aparición)
            vector<vector<string>> claves;
            vector<vector<vector<string>>> grupos;
            for (auto& f : elegidas) {
                vector<string> clave;
                for (int g : grupo) clave.push_back(f[g]);
                auto it = find(claves.begin(), claves.end(), clave);
                if (it == claves.end()) { claves.push_back(clave); grupos.push_back({f}); }
                else grupos[it - claves.begin()].push_back(f);
            }
            if (grupo.empty() && grupos.empty()) grupos.push_back({});  // COUNT(*) de nada = 0
            for (auto& filasGrupo : grupos) {
                vector<string> salida;
                for (auto& e : elementos) {
                    if (e.clase == ElementoSelect::COUNT) salida.push_back(to_string(filasGrupo.size()));
                    else if (e.clase == ElementoSelect::SUM) {
                        long long s = 0;
                        for (auto& f : filasGrupo) s += stoll(f[e.columna]);
                        salida.push_back(to_string(s));
                    } else salida.push_back(filasGrupo.empty() ? "" : filasGrupo[0][e.columna]);
                }
                r.filas.push_back(salida);
            }
        }

        // 6) ORDER BY: por un nombre del resultado (alias) o por una columna de la vista
        int ordenSalida = -1, ordenVista = -1;
        bool descendente = false;
        if (l.aceptarPalabra("ORDER")) {
            l.esperarPalabra("BY");
            string col = l.nombre();
            for (size_t i = 0; i < r.columnas.size(); i++)
                if (r.columnas[i] == col) ordenSalida = (int)i;
            if (ordenSalida == -1) {
                if (hayAgregados) throw ErrorBD("en una consulta con grupos, ORDER BY debe usar una columna del resultado");
                ordenVista = v.indiceObligatorio(col);
            }
            if (l.aceptarPalabra("DESC")) descendente = true;
            else l.aceptarPalabra("ASC");
        }

        long long limite = -1;
        if (l.aceptarPalabra("LIMIT")) {
            Token n = l.valor();
            if (n.tipo != TT::NUMERO) throw ErrorBD("LIMIT necesita un número");
            limite = stoll(n.valor);
        }
        l.esperarFin();

        if (!hayAgregados) {
            // Ordenar las filas de la vista y después quedarse con las columnas pedidas
            if (ordenSalida != -1) ordenVista = elementos[ordenSalida].columna;
            if (ordenVista != -1) {
                Tipo tipo = v.tipos[ordenVista];
                stable_sort(elegidas.begin(), elegidas.end(), [&](const auto& a, const auto& b) {
                    int cmp = comparar(a[ordenVista], b[ordenVista], tipo);
                    return descendente ? cmp > 0 : cmp < 0;
                });
            }
            for (auto& f : elegidas) {
                vector<string> salida;
                for (auto& e : elementos) salida.push_back(f[e.columna]);
                r.filas.push_back(salida);
            }
        } else if (ordenSalida != -1) {
            Tipo tipo = r.tipos[ordenSalida];
            stable_sort(r.filas.begin(), r.filas.end(), [&](const auto& a, const auto& b) {
                int cmp = comparar(a[ordenSalida], b[ordenSalida], tipo);
                return descendente ? cmp > 0 : cmp < 0;
            });
        }
        if (limite >= 0 && (long long)r.filas.size() > limite) r.filas.resize((size_t)limite);

        r.mensaje = to_string(r.filas.size()) + " fila(s)";
        return r;
    }

    // ------------------------------- UPDATE t SET col = valor [, ...] [WHERE]
    Resultado actualizar(Lector& l) {
        Tabla& t = tabla(l.nombre());
        l.esperarPalabra("SET");
        vector<pair<int, string>> cambios;
        do {
            int i = columnaDe(t, l.nombre());
            if (t.columnas[i].primaria) throw ErrorBD("no se puede cambiar la clave primaria");
            l.esperarSimbolo("=");
            cambios.push_back({i, convertir(l.valor(), t.columnas[i].tipo, t.columnas[i].nombre)});
        } while (l.aceptarSimbolo(","));
        Vista v = vistaDe(t);
        vector<Condicion> conds = leerWhere(l, v);
        l.esperarFin();

        // Primero se comprueba todo y después se cambia (o todo o nada)
        vector<size_t> afectadas;
        for (size_t k = 0; k < t.filas.size(); k++) {
            if (!cumple(t.filas[k], conds, v.tipos)) continue;
            vector<string> nueva = t.filas[k];
            for (auto& c : cambios) nueva[c.first] = c.second;
            comprobarForaneas(t, nueva);
            afectadas.push_back(k);
        }
        for (size_t k : afectadas)
            for (auto& c : cambios) t.filas[k][c.first] = c.second;

        guardarSiNoHayTransaccion();
        Resultado r;
        r.afectadas = (int)afectadas.size();
        r.mensaje = to_string(afectadas.size()) + " fila(s) actualizada(s)";
        return r;
    }

    // ------------------------------- DELETE FROM t [WHERE]
    Resultado eliminar(Lector& l) {
        l.esperarPalabra("FROM");
        Tabla& t = tabla(l.nombre());
        Vista v = vistaDe(t);
        vector<Condicion> conds = leerWhere(l, v);
        l.esperarFin();

        vector<vector<string>> aBorrar;
        for (auto& f : t.filas)
            if (cumple(f, conds, v.tipos)) aBorrar.push_back(f);
        comprobarQueNadieLasUsa(t, aBorrar);

        t.filas.erase(remove_if(t.filas.begin(), t.filas.end(),
                                [&](const auto& f) { return cumple(f, conds, v.tipos); }),
                      t.filas.end());
        guardarSiNoHayTransaccion();
        Resultado r;
        r.afectadas = (int)aBorrar.size();
        r.mensaje = to_string(aBorrar.size()) + " fila(s) borrada(s)";
        return r;
    }

    // ------------------------------- CREATE PROCEDURE nombre [(p1, p2)] AS orden; orden
    Resultado crearProcedimiento(Lector& l, const string& textoOriginal) {
        Procedimiento p;
        p.nombre = l.nombre();
        if (procedimientos.count(p.nombre)) throw ErrorBD("el procedimiento '" + p.nombre + "' ya existe");
        if (l.aceptarSimbolo("(")) {
            if (!l.esSimbolo(")")) {
                do { l.nombre(); p.numParametros++; } while (l.aceptarSimbolo(","));
            }
            l.esperarSimbolo(")");
        }
        l.esperarPalabra("AS");
        p.cuerpo = textoOriginal.substr(l.posicionTexto());
        while (!p.cuerpo.empty() && (isspace((unsigned char)p.cuerpo.back()) || p.cuerpo.back() == ';')) {
            p.cuerpo.pop_back();
        }
        if (p.cuerpo.empty()) throw ErrorBD("el procedimiento no tiene cuerpo");
        if (p.cuerpo.find('\t') != string::npos) throw ErrorBD("el cuerpo no puede tener tabuladores");
        tokenizar(p.cuerpo);  // comprobar que al menos se puede leer
        procedimientos[p.nombre] = p;
        guardarSiNoHayTransaccion();
        Resultado r;
        r.mensaje = "procedimiento '" + p.nombre + "' creado con " + to_string(p.numParametros) + " parámetro(s)";
        return r;
    }

    Resultado borrarProcedimiento(Lector& l) {
        bool siExiste = false;
        if (l.aceptarPalabra("IF")) { l.esperarPalabra("EXISTS"); siExiste = true; }
        string nombre = l.nombre();
        l.esperarFin();
        Resultado r;
        if (!procedimientos.count(nombre)) {
            if (siExiste) { r.mensaje = "el procedimiento '" + nombre + "' no existía"; return r; }
            throw ErrorBD("el procedimiento '" + nombre + "' no existe");
        }
        procedimientos.erase(nombre);
        guardarSiNoHayTransaccion();
        r.mensaje = "procedimiento '" + nombre + "' borrado";
        return r;
    }

    // Convierte un valor en texto que se puede volver a meter en una orden
    static string literal(const Token& t) {
        if (t.tipo == TT::NUMERO) return t.valor;
        string r = "'";
        for (char c : t.valor) {
            if (c == '\'') r += "''";
            else r += c;
        }
        return r + "'";
    }

    // Separa el cuerpo en órdenes por ';' (sin cortar dentro de comillas)
    static vector<string> separarOrdenes(const string& cuerpo) {
        vector<string> ordenes;
        string actual;
        bool enComillas = false;
        for (char c : cuerpo) {
            if (c == '\'') enComillas = !enComillas;
            if (c == ';' && !enComillas) {
                ordenes.push_back(actual);
                actual.clear();
            } else {
                actual += c;
            }
        }
        ordenes.push_back(actual);
        vector<string> limpias;
        for (auto& o : ordenes) {
            if (o.find_first_not_of(" \t") != string::npos) limpias.push_back(o);
        }
        return limpias;
    }

    // ------------------------------- CALL nombre(valor, valor)
    Resultado llamar(Lector& l, int profundidad) {
        string nombre = l.nombre();
        auto it = procedimientos.find(nombre);
        if (it == procedimientos.end()) throw ErrorBD("el procedimiento '" + nombre + "' no existe");
        const Procedimiento p = it->second;

        vector<Token> args;
        if (l.aceptarSimbolo("(")) {
            if (!l.esSimbolo(")")) {
                do { args.push_back(l.valor()); } while (l.aceptarSimbolo(","));
            }
            l.esperarSimbolo(")");
        }
        l.esperarFin();
        if ((int)args.size() != p.numParametros) {
            throw ErrorBD("'" + nombre + "' necesita " + to_string(p.numParametros) +
                          " parámetro(s) y se han dado " + to_string(args.size()));
        }

        Resultado total;
        bool hayConsulta = false;
        for (const string& orden : separarOrdenes(p.cuerpo)) {
            // Sustituir $1, $2... por los valores recibidos
            vector<Token> tks = tokenizar(orden);
            string final;
            size_t ultimo = 0;
            for (const Token& tk : tks) {
                if (tk.tipo != TT::PARAMETRO) continue;
                int n = stoi(tk.valor);
                if (n < 1 || n > (int)args.size()) throw ErrorBD("el parámetro $" + tk.valor + " no existe");
                final += orden.substr(ultimo, tk.inicio - ultimo) + literal(args[n - 1]);
                ultimo = tk.inicio + 1 + tk.valor.size();
            }
            final += orden.substr(ultimo);

            Resultado r = ejecutar(final, profundidad + 1);
            total.afectadas += r.afectadas;
            if (r.esConsulta) { hayConsulta = true; total.columnas = r.columnas; total.tipos = r.tipos; total.filas = r.filas; }
        }
        total.esConsulta = hayConsulta;
        total.mensaje = "procedimiento '" + nombre + "' ejecutado";
        return total;
    }

    // ------------------------------- Transacciones
    Resultado empezarTransaccion() {
        if (transaccion) throw ErrorBD("ya hay una transacción abierta");
        copiaTablas = tablas;
        copiaProcedimientos = procedimientos;
        transaccion = true;
        Resultado r;
        r.mensaje = "transacción iniciada";
        return r;
    }

    Resultado confirmar() {
        if (!transaccion) throw ErrorBD("no hay ninguna transacción abierta");
        guardarTodo();
        transaccion = false;
        copiaTablas.clear();
        copiaProcedimientos.clear();
        Resultado r;
        r.mensaje = "transacción confirmada (COMMIT): cambios guardados";
        return r;
    }

    Resultado deshacer() {
        if (!transaccion) throw ErrorBD("no hay ninguna transacción abierta");
        tablas = copiaTablas;
        procedimientos = copiaProcedimientos;
        transaccion = false;
        copiaTablas.clear();
        copiaProcedimientos.clear();
        Resultado r;
        r.mensaje = "transacción deshecha (ROLLBACK): todo vuelve a como estaba";
        return r;
    }

    // ------------------------------- SHOW TABLES / SHOW PROCEDURES
    Resultado mostrar(Lector& l) {
        Resultado r;
        r.esConsulta = true;
        if (l.aceptarPalabra("TABLES")) {
            l.esperarFin();
            r.columnas = {"tabla", "columnas", "filas"};
            r.tipos = {Tipo::TEXT, Tipo::INT, Tipo::INT};
            for (auto& [n, t] : tablas) {
                r.filas.push_back({n, to_string(t.columnas.size()), to_string(t.filas.size())});
            }
        } else if (l.aceptarPalabra("PROCEDURES")) {
            l.esperarFin();
            r.columnas = {"procedimiento", "parametros", "cuerpo"};
            r.tipos = {Tipo::TEXT, Tipo::INT, Tipo::TEXT};
            for (auto& [n, p] : procedimientos) {
                r.filas.push_back({n, to_string(p.numParametros), p.cuerpo});
            }
        } else {
            throw ErrorBD("usa SHOW TABLES o SHOW PROCEDURES");
        }
        r.mensaje = to_string(r.filas.size()) + " fila(s)";
        return r;
    }

    // ------------------------------- DESCRIBE tabla
    Resultado describir(Lector& l) {
        Tabla& t = tabla(l.nombre());
        l.esperarFin();
        Resultado r;
        r.esConsulta = true;
        r.columnas = {"columna", "tipo", "clave"};
        r.tipos = {Tipo::TEXT, Tipo::TEXT, Tipo::TEXT};
        for (auto& c : t.columnas) {
            string clave = c.primaria ? "PRIMARY KEY" : "";
            if (!c.refTabla.empty()) clave = "REFERENCES " + c.refTabla + "(" + c.refColumna + ")";
            r.filas.push_back({c.nombre, c.tipo == Tipo::INT ? "INT" : "TEXT", clave});
        }
        r.mensaje = to_string(r.filas.size()) + " columna(s)";
        return r;
    }

    // ------------------------------- Guardar y cargar ficheros
    void guardarSiNoHayTransaccion() {
        // Sin transacción, cada cambio se guarda al momento (autocommit)
        if (!transaccion) guardarTodo();
    }

    static string definicion(const Columna& c) {
        string d = c.nombre + ":" + (c.tipo == Tipo::INT ? "INT" : "TEXT");
        if (c.primaria) d += ":PK";
        if (!c.refTabla.empty()) d += ":FK=" + c.refTabla + "." + c.refColumna;
        return d;
    }

    void guardarTodo() {
        for (auto& [nombre, t] : tablas) {
            fs::path tmp = dir / (nombre + ".tabla.tmp");
            {
                ofstream f(tmp, ios::binary);
                if (!f) throw ErrorBD("no se puede escribir " + tmp.string());
                for (size_t i = 0; i < t.columnas.size(); i++) {
                    if (i) f << '|';
                    f << definicion(t.columnas[i]);
                }
                f << '\n';
                for (auto& fila : t.filas) {
                    for (size_t i = 0; i < fila.size(); i++) {
                        if (i) f << '|';
                        f << escapar(fila[i]);
                    }
                    f << '\n';
                }
            }
            // Se escribe en un .tmp y luego se renombra: si se va la luz a mitad,
            // el fichero bueno no queda a medias
            fs::path destino = dir / (nombre + ".tabla");
            try {
                fs::rename(tmp, destino);
            } catch (const fs::filesystem_error&) {
                // En algunos Windows rename no sobrescribe: se borra el viejo y se reintenta
                fs::remove(destino);
                fs::rename(tmp, destino);
            }
        }
        // Borrar ficheros de tablas que ya no existen (DROP TABLE)
        for (auto& e : fs::directory_iterator(dir)) {
            if (e.path().extension() == ".tabla" && !tablas.count(e.path().stem().string())) {
                fs::remove(e.path());
            }
        }
        ofstream f(dir / "_procedimientos.txt", ios::binary);
        for (auto& [n, p] : procedimientos) {
            f << n << '\t' << p.numParametros << '\t' << p.cuerpo << '\n';
        }
    }

    void cargar() {
        for (auto& e : fs::directory_iterator(dir)) {
            if (e.path().extension() != ".tabla") continue;
            ifstream f(e.path(), ios::binary);
            Tabla t;
            t.nombre = e.path().stem().string();
            string linea;
            if (!getline(f, linea)) continue;
            if (!linea.empty() && linea.back() == '\r') linea.pop_back();
            for (auto& def : partir(linea, '|')) {
                // nombre:TIPO[:PK][:FK=tabla.col]
                vector<string> partes;
                stringstream ss(def);
                string trozo;
                while (getline(ss, trozo, ':')) partes.push_back(trozo);
                if (partes.size() < 2) throw ErrorBD("cabecera dañada en " + e.path().string());
                Columna c;
                c.nombre = partes[0];
                c.tipo = partes[1] == "INT" ? Tipo::INT : Tipo::TEXT;
                for (size_t k = 2; k < partes.size(); k++) {
                    if (partes[k] == "PK") c.primaria = true;
                    else if (partes[k].rfind("FK=", 0) == 0) {
                        string ref = partes[k].substr(3);
                        size_t p = ref.find('.');
                        c.refTabla = ref.substr(0, p);
                        c.refColumna = ref.substr(p + 1);
                    }
                }
                t.columnas.push_back(c);
            }
            while (getline(f, linea)) {
                if (!linea.empty() && linea.back() == '\r') linea.pop_back();
                if (linea.empty() && t.columnas.size() > 1) continue;
                vector<string> fila;
                for (auto& v : partir(linea, '|')) fila.push_back(desescapar(v));
                if (fila.size() != t.columnas.size()) throw ErrorBD("fila dañada en " + e.path().string());
                t.filas.push_back(fila);
            }
            tablas[t.nombre] = t;
        }
        ifstream f(dir / "_procedimientos.txt", ios::binary);
        string linea;
        while (getline(f, linea)) {
            if (!linea.empty() && linea.back() == '\r') linea.pop_back();
            vector<string> partes;
            stringstream ss(linea);
            string trozo;
            while (getline(ss, trozo, '\t')) partes.push_back(trozo);
            if (partes.size() != 3) continue;
            procedimientos[partes[0]] = {partes[0], stoi(partes[1]), partes[2]};
        }
    }
};

// ---------------------------------------------------------------------
// Salida: JSON (para el conector) o tabla bonita (para personas)
// ---------------------------------------------------------------------

string aJson(const Resultado& r) {
    ostringstream o;
    o << "{\"ok\":true";
    if (r.esConsulta) {
        o << ",\"columnas\":[";
        for (size_t i = 0; i < r.columnas.size(); i++) o << (i ? "," : "") << jsonTexto(r.columnas[i]);
        o << "],\"filas\":[";
        for (size_t f = 0; f < r.filas.size(); f++) {
            o << (f ? "," : "") << "[";
            for (size_t i = 0; i < r.filas[f].size(); i++) {
                o << (i ? "," : "");
                if (r.tipos[i] == Tipo::INT && esEntero(r.filas[f][i])) o << r.filas[f][i];
                else o << jsonTexto(r.filas[f][i]);
            }
            o << "]";
        }
        o << "]";
    }
    o << ",\"afectadas\":" << r.afectadas;
    if (r.ultimoId != -1) o << ",\"ultimo_id\":" << r.ultimoId;
    o << ",\"mensaje\":" << jsonTexto(r.mensaje) << "}";
    return o.str();
}

void imprimirTabla(const Resultado& r) {
    vector<size_t> ancho(r.columnas.size());
    for (size_t i = 0; i < r.columnas.size(); i++) ancho[i] = largoUtf8(r.columnas[i]);
    for (auto& f : r.filas)
        for (size_t i = 0; i < f.size(); i++) ancho[i] = max(ancho[i], largoUtf8(f[i]));

    auto linea = [&]() {
        cout << "+";
        for (size_t a : ancho) cout << string(a + 2, '-') << "+";
        cout << "\n";
    };
    auto celda = [&](const string& v, size_t a) { cout << " " << v << string(a - largoUtf8(v), ' ') << " |"; };

    linea();
    cout << "|";
    for (size_t i = 0; i < r.columnas.size(); i++) celda(r.columnas[i], ancho[i]);
    cout << "\n";
    linea();
    for (auto& f : r.filas) {
        cout << "|";
        for (size_t i = 0; i < f.size(); i++) celda(f[i], ancho[i]);
        cout << "\n";
    }
    linea();
}

// ---------------------------------------------------------------------
// Programa principal
// ---------------------------------------------------------------------

int main(int argc, char* argv[]) {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);  // para que salgan bien las tildes en Windows
    SetConsoleCP(CP_UTF8);
#endif
    if (argc < 2) {
        cerr << "Uso: estadio <carpeta_de_la_base> [--json]\n";
        return 1;
    }
    bool modoJson = (argc >= 3 && string(argv[2]) == "--json");

    BaseDeDatos* bd = nullptr;
    try {
        bd = new BaseDeDatos(argv[1]);
    } catch (const exception& e) {
        if (modoJson) cout << "{\"ok\":false,\"error\":" << jsonTexto(e.what()) << "}" << endl;
        else cerr << "No se pudo abrir la base de datos: " << e.what() << "\n";
        return 1;
    }

    if (modoJson) {
        // Saludo: el conector lo lee para saber que la conexión funciona
        cout << "{\"ok\":true,\"mensaje\":\"diegofo | estadio listo\",\"version\":\"" << VERSION << "\"}" << endl;
    } else {
        cout << "diegofo | estadio " << VERSION << "  -  base de datos: " << argv[1] << "\n";
        cout << "Escribe una orden por línea. SALIR para terminar.\n\n";
    }

    string linea;
    while (true) {
        if (!modoJson) cout << (bd->enTransaccion() ? "estadio*> " : "estadio> ") << flush;
        if (!getline(cin, linea)) break;
        if (!linea.empty() && linea.back() == '\r') linea.pop_back();
        if (linea.find_first_not_of(" \t") == string::npos) continue;

        string primera = mayusculas(linea.substr(linea.find_first_not_of(" \t")));
        if (primera.rfind("SALIR", 0) == 0 || primera.rfind("EXIT", 0) == 0 || primera.rfind("QUIT", 0) == 0) {
            if (modoJson) cout << "{\"ok\":true,\"afectadas\":0,\"mensaje\":\"adiós\"}" << endl;
            break;
        }

        try {
            Resultado r = bd->ejecutar(linea);
            if (modoJson) {
                cout << aJson(r) << endl;  // endl vacía el búfer: el conector lo recibe al momento
            } else {
                if (r.esConsulta) imprimirTabla(r);
                cout << r.mensaje << "\n\n";
            }
        } catch (const exception& e) {
            if (modoJson) cout << "{\"ok\":false,\"error\":" << jsonTexto(e.what()) << "}" << endl;
            else cout << "ERROR: " << e.what() << "\n\n";
        }
    }

    if (bd->enTransaccion() && !modoJson) cout << "Había una transacción sin confirmar: se descarta.\n";
    delete bd;  // liberar la memoria del objeto
    return 0;
}
