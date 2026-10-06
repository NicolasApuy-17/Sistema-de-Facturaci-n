# Control Empresa

Sistema local para administradores de una empresa peruana. Django 5.2, PostgreSQL 18, moneda PEN y hora de Lima. Uso confirmado en una sola computadora; venta de bolsas para envasar productos alimenticios (por ejemplo, arroz), cajas y otros productos plásticos; Régimen General. La empresa indica que actualmente no trabaja con OSE: queda verificar su obligación con el RUC antes de habilitar emisión.

## Funciones disponibles

- Acceso con contraseña, gestión de administradores y bloqueo temporal de intentos fallidos.
- Clientes, productos y edición de código, nombre, unidad, precio, IGV, stock mínimo y disponibilidad. La edición conserva las descripciones y precios históricos y no cambia existencias. Una unidad con stock o historial no puede cambiarse; dos ediciones simultáneas se detectan.
- Entradas y salidas con motivos, historial, protección contra stock negativo y doble registro.
- Borradores de factura, boleta y notas; registro interno de ventas con descuento de stock y cuenta por cobrar.
- Notas internas de crédito: anulación, descuento por ítem y devolución por ítem. Notas internas de débito: interés por mora y aumento de valor. Modifican el saldo de la venta relacionada. La mercadería retorna al inventario únicamente cuando se confirma su devolución física. No se permite acreditar más que el importe original ni retornar más cantidad que la vendida.
- Pagos parciales, estado de cuenta y devolución de dinero limitada al saldo a favor. Cancelación de borradores.
- Guías remitente y transportista con productos, cantidades y datos de traslado. Son borradores y no duplican salidas de stock.
- Datos de empresa, auditoría y formatos para imprimir o guardar como PDF desde el navegador.
- Asistentes gráficos para actualizar, respaldar y restaurar. Inicio por doble clic, sin consola de servidor abierta.

**Todavía no es apto para emisión tributaria ni para operar el negocio en producción.** Los documentos e impresiones son internos. Ya se genera una vista previa XML UBL 2.1 para facturas, boletas y las notas admitidas. Falta completar las reglas SUNAT, firma, envío CPE/GRE, series definitivas, CDR, QR y conservación de archivos tributarios. Tampoco se calcula ICBPER ni están implementadas todas las afectaciones, percepciones o detracciones. El precio incluye IGV según la afectación seleccionada: gravado 18%, exonerado 0% o inafecto 0%. Debe existir fundamento para exoneración o inafectación; el uso alimenticio de una bolsa no implica IGV 0%. Los productos anteriores con porcentaje 0% migran como pendientes de clasificación, sin cambiar sus importes.

## Actualizar esta instalación conservando datos

1. Ejecuta **Detener.cmd** para cerrar el servidor de esta carpeta; PostgreSQL permanece activo.
2. Abre **Actualizar.cmd** e introduce la contraseña de postgres únicamente en la ventana local. El asistente crea un respaldo previo, aplica migraciones y mantiene los usuarios existentes. No guarda esa contraseña.
3. Selecciona una carpeta para copias diarias, preferentemente en otro disco.
4. Abre **Iniciar.cmd**. El navegador entra en http://127.0.0.1:8765.
5. En Configuración, completa la empresa y selecciona Régimen General. Revisa Inventario → Editar y prueba las operaciones.

Las migraciones y la restauración se probaron en una base aislada. No se aplicaron automáticamente a la base real: requieren ejecutar el asistente local. No vuelvas a ejecutar Configurar para actualizar una instalación existente.

## Primera instalación

PostgreSQL debe estar activo y facturacion_dev o facturacion_prod debe pertenecer a facturacion_admin.

1. En otra computadora, instala Python 3.12 de 64 bits con el lanzador py y pip, y ejecuta **Instalar.cmd**.
2. Abre **Configurar.cmd**, selecciona la base y escribe la contraseña de postgres en la ventana.
3. Crea el primer administrador con contraseña de al menos 12 caracteres y pulsa **Verificar y preparar sistema**.
4. Abre **Iniciar.cmd**.

El asistente crea las tablas como facturacion_admin y un usuario PostgreSQL limitado para el uso cotidiano. Los usuarios de la aplicación son distintos de los usuarios PostgreSQL. config.local.json contiene secretos y queda restringido al usuario Windows instalador y SYSTEM; no lo compartas. La auditoría no puede modificarse ni borrarse con el usuario cotidiano de la base.

## Respaldar y recuperar

- **Respaldar.cmd** crea una copia PostgreSQL y un JSON con tamaño y SHA-256. Conserva ambos juntos. El respaldo contiene datos del negocio y contraseñas de acceso almacenadas como hashes; protege la carpeta. No contiene las credenciales de conexión de config.local.json y no está cifrado.
- La copia automática se realiza una vez por día de Lima mientras el servidor está abierto, si se configuró la carpeta con Actualizar. Revisa el estado en Configuración. No se eliminan copias antiguas automáticamente.
- **Restaurar.cmd** pide una copia y la contraseña de postgres. Verifica su integridad y restaura en una base nueva facturacion_recuperada_AAAAMMDDhhmmss; evita sobrescribir bases existentes y verifica los registros. No cambia la conexión actual. Adoptar una base recuperada requiere revisar los datos y preparar sus permisos y conexión.
- Guarda al menos otra copia fuera del disco principal. Un respaldo en ese mismo disco no protege de su pérdida.

## Instalar posteriormente en la empresa

1. Instala PostgreSQL 18 y crea facturacion_prod con propietario facturacion_admin y contraseñas nuevas.
2. Copia el código, excluyendo .venv, config.local.json, work, staticfiles, logs, backups y backup-status.json. No copies los archivos internos de PostgreSQL ni datos de desarrollo.
3. Ejecuta **Instalar.cmd**, **Configurar.cmd** con facturacion_prod e **Iniciar.cmd**.
4. Configura respaldos con **Actualizar.cmd**, completa la empresa y comprueba venta, pagos, devolución e inventario.
5. Prueba una restauración en una base nueva en la computadora de destino.
6. Opcionalmente ejecuta **Preparar inicio automatico.cmd**. Prepara una tarea para iniciar la aplicación cuando ese usuario entre en Windows. No es un servicio que arranque antes de iniciar sesión. Esta tarea no se ha instalado en la computadora de desarrollo.

El servidor solo escucha en 127.0.0.1: no necesita abrir puertos ni habilitar PostgreSQL en la red. Los administradores pueden entrar con sus propias cuentas en la misma computadora. Los registros técnicos se guardan en logs/application.log. El lanzador detecta migraciones pendientes y solicita Actualizar antes de abrir la aplicación.

## Pendientes para producción

Implementar y validar emisión CPE y GRE; verificar obligación OSE con RUC, series, certificado y credenciales ingresados localmente; clasificación tributaria, ICBPER cuando corresponda, facturación al crédito y cuotas; motivos y excepciones de notas y GRE; reintentos y consulta de estados; firma, archivo XML/CDR, QR e impresión fiscal. Definir el tratamiento operativo de documentos rechazados. Completar pruebas SUNAT y la instalación y restauración en la empresa.

El ICBPER grava determinadas bolsas cuya finalidad es cargar o llevar bienes entregados por el establecimiento. No debe activarse indiscriminadamente para cajas u otros plásticos ni inferirse solo del nombre del producto. SUNAT indica S/ 0.50 por bolsa afecta y su importe no forma parte de la base del IGV. La venta de bolsas como mercadería y su entrega para llevar compras deben clasificarse antes de implementar esta regla.

Fuentes oficiales: [CPE y manuales](https://cpe.sunat.gob.pe/guias-y-manuales), [GRE](https://cpe.sunat.gob.pe/node/116), [alcance del ICBPER](https://orientacion.sunat.gob.pe/02-impuesto-al-consumo-de-las-bolsas-de-plastico), [monto](https://orientacion.sunat.gob.pe/7282-03-monto) y [comprobante e IGV](https://orientacion.sunat.gob.pe/07-comprobante-de-pago).

## Validación

Se aprobaron 48 pruebas, incluidas generación de XML UBL para los cuatro tipos, clasificación tributaria y conservación de históricos: stock y pagos concurrentes, operaciones repetidas, edición e historial, notas y devoluciones, permisos, formularios, acceso, impresión y migración de registros de la primera versión. Se comprobó también instalación con usuario de base limitado, respaldo real, restauración en otra base, rechazo de archivos alterados y protección de auditoría.

tools/test_postgres.py crea un clúster aislado en work/, ejecuta migraciones y pruebas y lo detiene al terminar. No utiliza ni modifica las bases reales. Requiere PostgreSQL 18; ejecutar con .venv\Scripts\python.exe tools\test_postgres.py. Estas pruebas no equivalen a aceptación SUNAT.


## Clasificación de productos y XML de prueba

1. Detén el sistema y abre Actualizar.cmd para instalar las nuevas columnas, con respaldo previo. En esta computadora lxml ya está instalado. En otra instalación con código anterior, instala las dependencias nuevas en su entorno antes de actualizar.
2. En Inventario → Editar, selecciona la afectación al IGV y el uso del producto. Para una bolsa que contiene arroz a granel o se utiliza como envase por inocuidad, revisa y selecciona Envase para alimentos a granel / inocuidad. Para cajas u otros productos que no sean bolsas destinadas a llevar compras, selecciona Otro producto. No se aplicó una clasificación automática a los productos existentes.
3. Completa los datos de empresa en Configuración y crea un borrador nuevo de prueba con los productos clasificados.
4. Abre el documento y pulsa Descargar XML de prueba. Usa referencias provisionales FPRV/BPRV basadas en el identificador interno. No reserva numeración fiscal, no registra ventas, no cambia stock ni envía a SUNAT.

Las notas de prueba apuntan al identificador provisional de su venta original. Se admiten clientes con DNI o RUC y operaciones al contado; las ventas al crédito con vencimiento posterior bloquean la descarga hasta implementar cuotas. Los productos sin clasificación, las bolsas destinadas a llevar compras (ICBPER pendiente), las transferencias gratuitas y las inconsistencias de totales o impuestos bloquean la descarga.

Las líneas nuevas guardan la afectación y el uso del producto; editarlo posteriormente no cambia las ventas anteriores. También se guardan tipo de documento y dirección del cliente al crear la venta. Las ventas antiguas conservan su uso como pendiente, y no se inventa una dirección histórica a partir de la actual. No dupliques una venta real para obtener un XML de prueba.

La validación local usa los XSD originales del estándar UBL 2.1 de [OASIS](https://docs.oasis-open.org/ubl/os-UBL-2.1/). Se incluyen en el código: no se descargan ni se requiere internet durante la generación. El ZIP publicado por SUNAT respondió HTTP 403 durante la preparación. La procedencia y los hashes de los esquemas están en core/fiscal/schemas/source.json. Cumplir el XSD verifica estructura, no firma digital ni aceptación o todas las reglas SUNAT.

La Ley 30884 contempla supuestos de bolsas para alimentos a granel o por inocuidad. La selección refleja el uso real que se debe revisar; no basta con denominar un producto como alimenticio. [Explicación oficial del MINAM](https://www.gob.pe/institucion/minam/noticias/23826-gobierno-promulga-ley-n-30884que-regula-el-plastico-de-un-solo-uso-y-envases-descartables-a-nivel-nacional).
