# Guía para acordar las métricas de riesgo con el socio

**Fecha:** 2026-10-14

**Estado:** pendiente de completar con el socio

**Fuente inicial:** `Metricas 1.xlsx`

## Para qué sirve este documento

Antes de programar una métrica necesitamos que ambos socios entiendan el número
de la misma manera. A ese acuerdo escrito lo llamamos **contrato de la métrica**.
No es un contrato legal ni un documento técnico: es una definición compartida que
evita que el dashboard muestre un valor correcto para una fórmula distinta de la
que ustedes esperaban.

Ejemplo: “drawdown diario de 4 %” puede significar una caída desde el balance al
inicio del día, desde la equity al inicio del día o desde el mayor valor alcanzado
durante ese día. Los tres cálculos son posibles y pueden dar resultados diferentes.

Este archivo está preparado para leerlo juntos y escribir la respuesta debajo de
cada pregunta. Cuando una respuesta no se conozca, conviene marcarla como
`Pendiente` y pedir un ejemplo al proveedor o a quien haya definido la regla.

## Resultado que necesitamos obtener

Para considerar acordada una métrica debemos conocer:

1. qué pregunta responde y para qué decisión se usará;
2. sobre qué se calcula: cuenta, bot, estrategia o cartera;
3. qué datos entran en el cálculo;
4. desde cuándo y durante cuánto tiempo se observa;
5. cómo se tratan flotante, depósitos, retiros, comisiones y swaps;
6. en qué unidad se muestra: porcentaje, dinero o ambas;
7. qué valor genera advertencia o peligro;
8. uno o más ejemplos calculados manualmente para comprobar el sistema;
9. cómo debe verse en el dashboard.

## Orden recomendado para la conversación

No es necesario resolver todas las métricas en una sola reunión.

1. DDD o Daily Drawdown.
2. Maximum Drawdown permitido por la cuenta.
3. Maximum Drawdown histórico observado.
4. VaR y volatilidad.
5. Covarianza y riesgo conjunto de la cartera.
6. Sharpe.

Las tres primeras permiten construir el primer control operativo. Las restantes
necesitan una historia de resultados suficientemente larga.

---

## Parte 1 — Decisiones generales

Estas respuestas se aplicarán a varias métricas.

### 1. Qué queremos vigilar

¿Cuál es la prioridad inicial?

- [ ] Evitar perder una cuenta por superar sus límites.
- [ ] Conocer el riesgo de cada bot.
- [ ] Comparar bots entre sí.
- [ ] Vigilar el riesgo combinado de una cartera.
- [ ] Todas, pero en el orden indicado abajo.

**Respuesta acordada:**

### 2. Nivel de cálculo

¿Qué niveles debe mostrar el dashboard?

- [ ] Cuenta completa.
- [ ] Bot identificado por Magic Number.
- [ ] Estrategia que puede contener varios bots.
- [ ] Cartera de bots o estrategias.

**Respuesta acordada:**

> Nota: MT5 informa directamente la equity de la cuenta, pero no una “equity del
> bot”. Para calcular riesgo por bot habrá que acordar cómo asignarle capital y
> cómo repartir depósitos, retiros y costes.

### 3. Unidad principal

¿Se quiere ver el riesgo en porcentaje, en dinero o en ambos?

**Respuesta acordada:**

### 4. Día operativo

¿A qué hora y en qué zona horaria comienza un nuevo día para las reglas diarias?
¿Debe coincidir con el horario del broker, WSF, Madrid u otra referencia?

**Respuesta acordada:**

### 5. Movimientos de dinero

¿Cómo deben tratarse depósitos, retiros, créditos y ajustes del broker? Por
ejemplo, un depósito no debería parecer una ganancia de trading ni un retiro una
pérdida.

**Respuesta acordada:**

### 6. Costes

¿Los resultados deben ser siempre netos de comisión, swap y fee?

**Respuesta acordada:**

### 7. Datos faltantes

Si MT5 estuvo desconectado durante un periodo, ¿el dashboard debe mostrar la
métrica como no disponible, calcularla con datos parciales o reconstruirla desde
el historial cuando sea posible?

**Respuesta acordada:**

---

## Parte 2 — DDD o Daily Drawdown

### En palabras sencillas

Responde: **¿cuánto podemos perder hoy antes de incumplir el límite diario de la
cuenta?** Se reinicia cada día según una hora determinada.

El Excel indica que debe respetar el método definido por WSF. Necesitamos la regla
exacta de WSF, no una fórmula genérica de internet.

### Preguntas para resolver

1. ¿Pueden aportar una captura, documento o ejemplo numérico de la regla WSF?
2. ¿El límite está expresado en porcentaje, dinero o ambos?
3. ¿La referencia inicial es el balance o la equity al comenzar el día?
4. ¿La referencia queda fija todo el día o sube si la cuenta alcanza un nuevo
   máximo?
5. ¿Las pérdidas abiertas cuentan aunque la operación todavía no haya cerrado?
6. ¿Las ganancias obtenidas durante el día amplían el margen disponible?
7. ¿Qué ocurre con depósitos, retiros, comisiones y swaps?
8. ¿A qué hora exacta se reinicia y qué reloj determina esa hora?
9. ¿Se calcula únicamente para la cuenta o también por Magic Number?
10. ¿Cuáles son los niveles de aviso? Por ejemplo: normal, advertencia y peligro.

**Respuesta acordada:**

### Ejemplo que debe aportar el socio

Completar un día ficticio o real con:

- balance y equity al comenzar el día;
- mejor equity del día, si influye;
- peor equity del día;
- depósitos o retiros;
- límite diario;
- DDD que debería mostrar el dashboard;
- cantidad restante antes de incumplir el límite.

**Ejemplo aprobado:**

---

## Parte 3 — Maximum Drawdown permitido

### En palabras sencillas

Responde: **¿cuánto puede caer la cuenta en total antes de incumplir su límite?**
A diferencia del DDD, normalmente no se reinicia cada día.

### Preguntas para resolver

1. ¿La regla es fija desde el capital inicial o sigue el máximo alcanzado por la
   cuenta?
2. ¿Se basa en balance, equity o en el peor de ambos?
3. ¿Las posiciones abiertas forman parte de la pérdida?
4. ¿El límite se expresa en dinero, porcentaje o ambos?
5. ¿Cómo modifican la referencia los depósitos y retiros?
6. ¿La regla pertenece al broker, a WSF o es una regla interna de TradingLab?
7. ¿Qué niveles de aviso deben mostrarse antes de alcanzar el límite?
8. ¿Se necesita solamente por cuenta o también por bot y cartera?

**Respuesta acordada:**

### Ejemplo que debe aportar el socio

- capital inicial;
- máximo capital alcanzado;
- equity actual y peor equity;
- límite total;
- drawdown esperado;
- margen restante antes del incumplimiento.

**Ejemplo aprobado:**

---

## Parte 4 — Maximum Drawdown histórico

### En palabras sencillas

Responde: **¿cuál fue la peor caída real observada desde un máximo hasta el mínimo
siguiente?** Es una medida analítica del comportamiento pasado y no necesariamente
coincide con el límite contractual de la cuenta.

### Preguntas para resolver

1. ¿Debe calcularse sobre balance, equity o ambos?
2. ¿Qué periodo interesa: desde el inicio, último mes, últimos 90 días u otro?
3. ¿Se necesita por cuenta, bot, estrategia y cartera?
4. ¿Qué frecuencia de observación se considera suficiente para no ocultar caídas
   intradiarias: 5 segundos, 1 minuto u otra?
5. ¿Se muestra en porcentaje, dinero o ambos?
6. ¿Quieren ver también la fecha del máximo, la fecha del mínimo y el tiempo de
   recuperación?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 5 — VaR

### En palabras sencillas

El VaR intenta responder: **en condiciones parecidas a las observadas, qué pérdida
no debería superarse en la mayoría de los periodos?** No indica la peor pérdida
posible y no debe confundirse con una garantía.

El Excel propone como ejemplo un VaR diario al 95 %. Todavía falta acordar cómo se
calcula para TradingLab.

### Preguntas para resolver

1. ¿Se necesita por día, por semana o para otro horizonte?
2. ¿Qué nivel interesa: 95 %, 99 % u otro?
3. ¿Se calcula por bot, cuenta y cartera?
4. ¿Cuánto historial se usará: 30, 60, 90, 252 días u otro periodo?
5. ¿Se prefiere usar directamente las pérdidas históricas o un modelo estadístico?
6. ¿Debe mostrarse como porcentaje, dinero o ambos?
7. ¿Qué decisión se tomará cuando el VaR supere un nivel determinado?
8. ¿Cuántos días mínimos de datos se requieren antes de mostrarlo como confiable?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 6 — Volatilidad

### En palabras sencillas

Responde: **¿qué tan variables o inestables son los resultados?** Dos bots pueden
ganar lo mismo en promedio, pero uno puede hacerlo con movimientos mucho más
bruscos.

### Preguntas para resolver

1. ¿Se medirá usando resultados diarios, semanales u otra frecuencia?
2. ¿Qué ventana se quiere observar?
3. ¿Se necesita por bot, cuenta y cartera?
4. ¿Se muestra como volatilidad del periodo o anualizada?
5. ¿Qué valor se considera bajo, normal o alto?
6. ¿Cuántas observaciones mínimas se necesitan antes de mostrarla?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 7 — Covarianza y relación entre bots

### En palabras sencillas

Busca responder: **¿qué bots tienden a ganar o perder al mismo tiempo?** Si varios
bots pierden juntos, combinarlos puede aportar menos diversificación de la que
parece.

La covarianza es difícil de interpretar visualmente. Conviene confirmar si el
socio quiere ver también correlación, que expresa la relación en una escala de
-1 a 1 y suele ser más clara en un mapa de colores.

### Preguntas para resolver

1. ¿Qué bots o estrategias deben compararse?
2. ¿Se comparan resultados diarios, semanales u otros?
3. ¿Se quiere covarianza, correlación o ambas?
4. ¿Qué periodo histórico se utilizará?
5. ¿Qué cantidad mínima de días compartidos necesitan dos bots para compararlos?
6. ¿Cómo se tratan días sin operaciones o datos faltantes?
7. ¿Qué relación se considera peligrosa o poco diversificada?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 8 — Riesgo de la cartera

### En palabras sencillas

Responde: **¿cuál es el riesgo combinado real de todos los bots?** No alcanza con
sumar el riesgo individual porque algunos bots pueden compensarse y otros perder
juntos.

### Preguntas para resolver

1. ¿Qué bots forman cada cartera y desde qué fecha?
2. ¿Qué peso tiene cada bot: capital asignado, riesgo configurado, exposición
   actual o todos por igual?
3. ¿Los pesos cambian automáticamente o se cargan manualmente?
4. ¿Se mide por cuenta o se combinan varias cuentas?
5. ¿En qué moneda se unifican resultados de cuentas diferentes?
6. ¿Qué valor final se espera ver: volatilidad, VaR, pérdida estimada o varios?
7. ¿Qué límite genera una advertencia?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 9 — Sharpe

### En palabras sencillas

Responde: **¿cuánto retorno se obtuvo en relación con la variabilidad asumida?**
Sirve para comparar alternativas, pero puede ser engañoso con poco historial o
resultados muy irregulares.

### Preguntas para resolver

1. ¿Se calculará para bots, cuentas, carteras o todos?
2. ¿Qué frecuencia de resultados se usará?
3. ¿Qué periodo histórico se observará?
4. ¿Se utilizará una tasa libre de riesgo real o cero durante el piloto?
5. ¿Se anualizará el resultado?
6. ¿Los retornos serán netos de todos los costes?
7. ¿Cuántos datos mínimos se requieren antes de mostrarlo?
8. ¿Qué rangos se consideran malos, aceptables o buenos para este proyecto?

**Respuesta acordada:**

**Ejemplo aprobado:**

---

## Parte 10 — Presentación en el dashboard

La arquitectura prevé Apache ECharts para estas visualizaciones. No hace falta
elegir colores o detalles técnicos con el socio, pero sí qué información le sirve
para decidir.

### Propuestas para confirmar

- DDD y Max DD: valor actual, límite, margen restante y línea temporal de equity.
- Drawdown histórico: curva de drawdown con máximo y mínimo destacados.
- VaR: valor en porcentaje y dinero, acompañado por distribución de resultados.
- Volatilidad: comparación entre bots y evolución temporal.
- Covarianza/correlación: mapa de colores entre bots.
- Riesgo de cartera: valor total y contribución de cada bot.
- Sharpe: comparación entre bots y carteras, mostrando periodo y cantidad de
  observaciones.

### Preguntas finales de presentación

1. ¿Qué tres números deben verse primero al abrir el dashboard?
2. ¿Qué métricas necesitan semáforo o alerta?
3. ¿Qué filtros se necesitan: cuenta, Magic Number, estrategia, cartera y fecha?
4. ¿Se necesita comparar dos periodos o dos bots lado a lado?
5. ¿Qué información debe poder exportarse?

**Respuesta acordada:**

---

## Parte 11 — Datos y conservación

Para calcular métricas históricas debemos comenzar a guardar observaciones fuera
de la memoria temporal del dashboard.

### Preguntas para resolver

1. ¿Cada cuánto se debe guardar balance y equity: 5 segundos, 1 minuto u otra
   frecuencia?
2. ¿Cuánto tiempo debe conservarse el detalle original?
3. ¿Se acepta reducir la frecuencia de datos antiguos conservando máximos y
   mínimos importantes?
4. ¿Desde qué fecha deben comenzar las métricas?
5. ¿Es necesario importar historia anterior o se empieza desde la puesta en marcha?
6. ¿Cómo se marcarán periodos en los que MT5 estuvo desconectado?

**Respuesta acordada:**

## Criterio para comenzar a programar

No hace falta completar todo el documento para avanzar. Podemos comenzar el primer
incremento cuando estén resueltas:

- las decisiones generales;
- la sección de DDD;
- la sección de Maximum Drawdown permitido;
- la frecuencia y conservación inicial de balance/equity;
- al menos un ejemplo aprobado de cada una de esas dos métricas.

Con esas respuestas podremos implementar persistencia mínima, fórmulas versionadas,
pruebas automatizadas y los primeros gráficos con Apache ECharts sin inventar
reglas de negocio.
