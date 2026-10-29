# amigable-mef

Un servidor MCP que le da a Claude acceso a la **Consulta Amigable del MEF**: el presupuesto (PIA, PIM) y la
ejecución (certificación, compromiso, devengado, girado) del gasto público del Perú, de los tres niveles de
gobierno, desde 2012. Además trae las **definiciones oficiales de los clasificadores presupuestarios**, para que
quien no conoce los filtros sepa dónde cae cada gasto.

La Consulta Amigable no tiene API: el servidor repite los clics de la web (agrupar, elegir una fila, volver a
agrupar) y lee la tabla. Las cuentas las hace Python, así que cada cifra sale de una consulta que se puede repetir
en la web.

## Qué trae

| Primitiva | Nombre | Para qué |
|---|---|---|
| Herramienta | `consultar` | Una tabla de la Consulta Amigable: agrupar por nivel de gobierno, sector, pliego, municipalidad, función, programa, genérica, fuente, departamento, mes... siguiendo una ruta de filtros |
| Herramienta | `resumen` | Total, promedio, mediana, máximo, mínimo, ranking con participación %, avance % y brecha PIM − devengado |
| Herramienta | `barrido` | La misma consulta en varios años, con la variación año a año |
| Herramienta | `glosario` | Busca en los clasificadores del MEF qué significa una partida, fuente o rubro, y cómo filtrarla |
| Recurso | `amigable://glosario/columnas` | Qué es PIA, PIM, certificación, devengado, girado, avance % |
| Recurso | `amigable://clasificador/{clasificador}/{codigo}` | La ficha de una partida con su definición y sus partidas hijas |
| Prompt | `consulta(pregunta)` | Traduce una pregunta a la ruta de filtros y obliga a citar año, ruta y fuente |

## Instalación

Necesitan [`uv`](https://docs.astral.sh/uv/) e internet. No pide claves. La primera vez que arranca, `uv` instala
las dependencias solo.

```bash
git clone https://github.com/ximenapize/mcp-amigable.git
cd mcp-amigable
uv run pytest -q                 # opcional: las pruebas, con datos reales de la Consulta Amigable
```

Después elijan dónde usarlo:

**En Claude Code, dentro de esta carpeta.** No hay que configurar nada: `.mcp.json` ya conecta `amigable-mef` y
`fetch`. Abran `claude` en la carpeta y aprueben los dos servidores la primera vez.

**En Claude Code, desde cualquier carpeta.** Regístrenlo una vez con alcance de usuario y la ruta absoluta del repo:

```bash
claude mcp add --scope user amigable-mef -- uv run --directory /ruta/a/mcp-amigable server.py
```

Con `--directory`, `uv` usa el entorno del repo y el servidor encuentra `glosario.csv` y su caché.

**En Claude Desktop.** Agreguen esto a `claude_desktop_config.json` (en macOS está en
`~/Library/Application Support/Claude/`) y reinicien la app:

```json
{
  "mcpServers": {
    "amigable-mef": {
      "command": "/ruta/completa/a/uv",
      "args": ["run", "--directory", "/ruta/a/mcp-amigable", "server.py"]
    }
  }
}
```

Usen la ruta completa de `uv` (la da `which uv`): la app de escritorio no siempre ve el mismo `PATH` que la terminal.

## Uso

Para comprobar que está conectado, escriban `/mcp` en Claude Code: deben ver `amigable-mef` con sus 4
herramientas. En Claude Desktop aparece en el menú de herramientas del chat.

### 1. Preguntar en lenguaje natural

Es la forma normal. Claude elige la ruta de filtros, llama a las herramientas y cita de dónde sale cada cifra.

- *«¿Cuánto ejecutó la Municipalidad de Lima en seguridad ciudadana en 2025?»*
- *«¿Qué municipalidades de la provincia de Cusco tuvieron el avance más bajo en 2025?»*
- *«¿Cómo cambió el presupuesto de carreteras en Cajamarca entre 2020 y 2024?»*
- *«¿Qué parte del presupuesto del Ministerio de Salud es bienes y servicios?»*
- *«¿Cuánto se gastó con recursos de canon en 2024 y en qué funciones?»*
- *«¿En qué partida se registran los viáticos? ¿Qué incluye?»*

Para obtener mejores respuestas:

- **Digan el año.** Sin año, Claude usa el año en curso, que cambia a diario.
- **Digan qué cifra quieren:** PIA (el presupuesto inicial), PIM (el vigente) o devengado (lo gastado). Si no lo
  dicen, Claude suele dar las tres.
- **Si la fuente no tiene el detalle que piden** (una provincia por ubicación, una enfermedad sin programa propio),
  Claude lo dice, da la cifra del nivel más cercano y ofrece una alternativa. La alternativa solo la ejecuta si
  ustedes la piden.

### 2. Con el prompt `consulta`

El prompt guía a Claude paso a paso: traducir la pregunta a filtros, consultar, no hacer cuentas a mano y citar
año, ruta y fuente.

- En Claude Code: `/mcp__amigable-mef__consulta presupuesto de carreteras en Cajamarca 2020-2024`
- En Claude Desktop: el botón **+** del chat → el servidor `amigable-mef` → `consulta`.

### 3. Con los recursos

Los recursos traen información fija que Claude lee sin consultar la web.

| Recurso | Qué trae | En Claude Code |
|---|---|---|
| `amigable://glosario/columnas` | Qué es PIA, PIM, certificación, compromiso, devengado, girado y avance % | `@amigable-mef:amigable://glosario/columnas` |
| `amigable://clasificador/gasto/{codigo}` | La ficha de una partida de gasto: nombre, nivel, definición oficial y partidas hijas | `@amigable-mef:amigable://clasificador/gasto/2.3` |
| `amigable://clasificador/fuente/{codigo}` | Una fuente de financiamiento (1 a 5) | `@amigable-mef:amigable://clasificador/fuente/5` |
| `amigable://clasificador/rubro/{codigo}` | Un rubro (00, 04, 07, 08, 09, 13, 15, 18, 19) | `@amigable-mef:amigable://clasificador/rubro/18` |

### Las columnas

Todas las herramientas devuelven las mismas columnas que la web, en soles:

| Columna | Qué es |
|---|---|
| `pia` | Presupuesto Institucional de Apertura: el inicial, aprobado con la Ley de Presupuesto |
| `pim` | Presupuesto Institucional Modificado: el PIA más las modificaciones del año. Es el presupuesto vigente |
| `certificacion` | Lo que se garantizó como disponible para un gasto, antes de comprometerlo |
| `compromiso_anual` | Lo comprometido por obligaciones del año, por ejemplo contratos firmados |
| `atencion_compromiso_mensual` | La parte del compromiso programada para el mes |
| `devengado` | La obligación de pago reconocida tras recibir el bien o servicio. Es la medida habitual de lo gastado |
| `girado` | Lo efectivamente pagado |
| `avance_pct` | Devengado / PIM × 100 |

### Cómo funcionan los filtros: la ruta

La Consulta Amigable se recorre así: **agrupar** por un criterio, **elegir una fila** y volver a agrupar por otro.
El servidor lo representa con dos parámetros:

- `ruta`: las filas elegidas antes, en orden, cada una `{"criterio", "codigo"}`.
- `agrupar_por`: el criterio de la tabla que quieren ver al final.

Ejemplo: los pliegos del sector Interior en 2025.

```json
{"anio": 2025,
 "ruta": [{"criterio": "nivel_gobierno", "codigo": "E"}, {"criterio": "sector", "codigo": "07"}],
 "agrupar_por": "pliego"}
```

Los códigos salen siempre de una consulta anterior. Cada respuesta dice en `puede_agrupar_por` qué criterios se
pueden usar a continuación. Los criterios se combinan en cualquier orden: por ejemplo, municipalidad → función →
genérica.

| Pregunta de la web | Criterio (`agrupar_por`) | Botón en la web | Códigos de ejemplo |
|---|---|---|---|
| ¿Quién gasta? | `nivel_gobierno` → `sector` → `pliego` → `ejecutora` | Nivel de Gobierno, Sector, Pliego, Ejecutora | `E` nacional, `R` regional, `M` local; sector `07` Interior, `11` Salud; pliego `007` |
| ¿Quién gasta? (municipalidades) | `nivel_gobierno` M → `gobierno_local` → `departamento_gl` → `provincia_gl` → `municipalidad` | Gob.Loc./Mancom., Departamento, Provincia, Municipalidad | `gobierno_local` `M` municipalidades, `N` mancomunidades; Lima `15` → `01` → `301250` |
| ¿En qué se gasta? (funcional) | `funcion` → `division_funcional` → `grupo_funcional` | Función, División Funcional, Grupo Funcional | función `05` Orden público, `15` Transporte, `20` Salud |
| ¿En qué se gasta? (programas) | `categoria_presupuestal` → `producto_proyecto` → `actividad` | Categoría Presupuestal, Producto/Proyecto, Actividad/Acción/Obra | `0030` seguridad ciudadana, `0017` metaxénicas y zoonosis, `9001` acciones centrales |
| ¿Cómo se estructura el gasto? | `generica` → `subgenerica` → `subgenerica_detalle` → ... | Genérica, Sub-Genérica... | `5-2-3` bienes y servicios (5 corriente, 6 capital, 7 deuda); `2-3-1` compra de bienes |
| ¿Con qué se financia? | `fuente`, `rubro` | Fuente, Rubro | fuente `1` recursos ordinarios, `5` recursos determinados; rubro `18` canon |
| ¿Dónde se gasta? | `departamento` | Departamento | `06` Cajamarca, `08` Cusco, `15` Lima |
| ¿Cuándo se hizo el gasto? | `trimestre`, `mes` | Trimestre, Mes | `12` diciembre |

Al agrupar por genérica, subgenérica, fuente o rubro, cada fila trae también su definición oficial.

### Las herramientas en detalle

**`consultar(anio, agrupar_por, ruta=[], modo="todo")`**

Devuelve una tabla de la Consulta Amigable. Incluye las filas con todas las columnas, el `total`, los criterios
disponibles en `puede_agrupar_por` y el link de la `fuente`. `modo` puede ser `"todo"` (actividades y proyectos),
`"actividades"` o `"proyectos"`. Años desde 2012.

**`resumen(anio, agrupar_por, ruta=[], monto="devengado", top=10, modo="todo")`**

Estadísticas ya calculadas sobre la misma tabla: `total`, `n`, `promedio`, `mediana`, `maximo`, `minimo`, un
`ranking` con la participación % de cada fila, el avance % total y el promedio, las filas con avance menor a 50 %
y la `brecha_pim_devengado` (lo que falta gastar). `monto` puede ser `pia`, `pim`, `certificacion`,
`compromiso_anual`, `devengado` o `girado`.

**`barrido(anios, agrupar_por, ruta=[], monto="pim", modo="todo")`**

La misma consulta en varios años (máximo 15). Para cada año da PIA, PIM, devengado y avance; además la variación %
año a año y entre el primero y el último, y una tabla con el monto de cada fila por año. Si un código no existe en
algún año, ese año queda con su error y los demás siguen.

**`glosario(texto="", codigo="", clasificador="", limite=10)`**

Busca en los clasificadores del MEF por palabras (todas deben aparecer en el nombre o la definición) o por código.
`clasificador` puede ser `"gasto"`, `"fuente"` o `"rubro"`. Cada resultado dice cómo filtrar esa partida en
`consultar`. Ejemplos: `texto="viáticos"`, `texto="mantenimiento de carreteras"`, `codigo="2.3.2.7"`.

### Rutas que ya se sabe que funcionan

| Tema | Ruta |
|---|---|
| Seguridad ciudadana (funcional) | `funcion` 05 → `division_funcional` 014 → `grupo_funcional` 0031 Seguridad vecinal y comunal |
| Seguridad ciudadana (programa) | `categoria_presupuestal` 0030 |
| Carreteras | `funcion` 15 → `division_funcional` 033 → `grupo_funcional` 0064 nacionales, 0065 departamentales, 0066 vecinales |
| Dengue | `categoria_presupuestal` 0017, que incluye todas las metaxénicas y zoonosis; prevención en `producto_proyecto` 3043977, 3043980 y 3043981 |
| Una municipalidad | `nivel_gobierno` M → `gobierno_local` M → `departamento_gl` → `provincia_gl` → `municipalidad` |
| Bienes y servicios | `generica` 5-2-3 |
| Canon y regalías | `rubro` 18 |

### Caché y tiempos

- **Tiempo por consulta:** cada paso de la ruta es un pedido a la web y tarda alrededor de 1 segundo, porque el
  servidor espera 0.7 s entre pedidos para no ser bloqueado. Una consulta de 5 pasos toma entre 5 y 8 segundos, y un
  `barrido` de 5 años, alrededor de medio minuto.
- **Caché:** las respuestas se guardan en `datos/cache/` (git la ignora). Los años cerrados quedan guardados; el año
  en curso se vuelve a pedir al día siguiente, porque cambia a diario. Para forzar datos frescos, borren
  `datos/cache/`.

### Si algo falla

| Síntoma | Qué hacer |
|---|---|
| `/mcp` muestra `amigable-mef` con error | Corran `uv run pytest -q` en la carpeta para ver el error de Python, o `claude mcp get amigable-mef` para revisar el comando |
| «La Consulta Amigable no respondió con datos» | La web bloquea los pedidos muy seguidos. Esperen unos segundos y vuelvan a preguntar |
| «No hay una fila con código...» | El código no existe en ese año o en ese punto de la ruta. El error lista códigos que sí existen |
| «No se puede agrupar por...» | Ese criterio no está disponible en ese punto. El error lista las opciones |
| Claude responde sin usar el servidor | Pídanle explícitamente «usa amigable-mef», o usen el prompt `consulta` |
| Una cifra no coincide con la web | La web redondea al sol y el servidor guarda decimales. Si la diferencia es mayor, borren `datos/cache/`: la cifra pudo actualizarse |

## La evaluación

`evaluar.py` le hace las 10 preguntas de `preguntas.csv` a Claude con `claude -p`, sin herramientas, con búsqueda
web y con este MCP, y las califica contra la cifra oficial. `grafico.py` dibuja `grafico.png` desde
`resultados.csv`. El análisis está en [`informe.md`](informe.md).

```bash
uv run evaluar.py --modos memoria web mcp      # unos 5 minutos con Haiku
uv run grafico.py
```

## El glosario

`glosario.csv` sale de los PDF oficiales de los
[clasificadores presupuestarios del MEF](https://www.mef.gob.pe/es/clasificadores-presupuestarios) del año
fiscal 2026: el clasificador económico de gastos (924 partidas) y el de fuentes de financiamiento y rubros. Para
regenerarlo:

```bash
uv run construir_glosario.py
```

## Límites conocidos

Cuando una pregunta pide un detalle que la fuente no tiene, el servidor le indica a Claude que lo diga, dé la cifra
del nivel más cercano explicando qué incluye y ofrezca la alternativa sin ejecutarla hasta que el usuario la pida.

- La vista «¿Dónde se gasta?» llega a departamento, no a provincia ni distrito. La alternativa para una provincia
  es el gasto de sus municipalidades, que deja fuera lo que gastan ahí el Gobierno Nacional y el regional.
- Algunos temas no tienen un programa propio. El dengue, por ejemplo, está dentro del programa 0017, que cubre
  todas las enfermedades metaxénicas y zoonosis.
- La página tiene protección contra bots: el servidor espera 0.7 s entre pedidos y reintenta si no recibe datos.
