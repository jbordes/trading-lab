# Navegación adaptable y marca — análisis visual

**Fecha:** 2026-10-19
**Estado:** Implementado en la rama `feature/adaptive-navigation`; sujeto a revisión humana.

## Referencias y alcance

Las referencias provistas son [escritorio](../idea-visual-tabs.png) y
[móvil](../idea-web-mobile-app.png). Se toman como ideas de organización y
jerarquía, no como definición de colores, métricas o funciones. La paleta clara y
oscura suave del piloto se conserva.

Vistas del prototipo en modo demo: [escritorio claro](../adaptive-navigation-desktop.png)
y [móvil oscuro](../adaptive-navigation-mobile.png). Son capturas de ejemplo;
los importes simulados cambian con las lecturas.

La referencia de escritorio aporta una identidad persistente a la izquierda y
un área de trabajo despejada a la derecha. La de móvil muestra acceso constante
a las áreas principales en el borde inferior y un encabezado compacto. Esa
relación cambia con el espacio disponible dentro del panel: barra lateral desde
1000 px y barra inferior por debajo. La portada no forma parte de esa navegación:
es una página de presentación con encabezado propio y una entrada al panel.

| Elemento de referencia | Adaptación actual | Motivo |
| --- | --- | --- |
| Marca en encabezado | Logo original negro o blanco según tema, más nombre | Reconocer la aplicación sin depender solo de texto |
| Menú lateral de escritorio | Resumen, Operaciones, Actividad | Solo contiene vistas de trabajo |
| Menú inferior móvil | Las mismas tres vistas, con icono y texto | Mantener orientación dentro del panel |
| Equity y curva como foco | Equity primero y curva existente en Resumen | Datos observados, sin porcentajes calculados sin contrato |
| Estrategias, backtests, reportes, configuración | No aparecen como destinos | Aún no tienen vista ni datos propios |
| Rangos 1D/1W/1M/1Y y alertas | No aparecen | Falta historia durable y sistema de alertas |

Los logos provistos en `docs/logo_black.png` y `docs/logo_white.png` se copiaron
sin alterar a `src/tradinglab/dashboard/static/` para servirlos localmente. Los
originales del usuario se conservaron. Para el favicon, el navegador dibuja
un recorte centrado del logo horizontal dentro de un lienzo cuadrado
transparente: el motivo tiene mejor presencia a 16 px sin estirar los PNG.
El nombre sigue siendo texto real; el
gráfico decorativo queda oculto al lector de pantalla. Las vistas del panel
mantienen sus roles de tab y el título principal cambia con la vista activa.
La navegación de teclado acepta flechas horizontales y verticales, Inicio y Fin.

## Móvil y futura app

La barra inferior respeta el área segura (`safe-area-inset-bottom`) y el contenido
mantiene espacio al final para que no quede tapado. Esta convención podría
reutilizarse en una futura app, pero no decide hoy si será web instalable, nativa
o híbrida. Antes de elegir plataforma habrá que definir qué requiere uso sin
conexión, notificaciones, autenticación y acceso seguro a las fuentes.

Un icono específico para sistema operativo se diseñará cuando exista esa decisión.

La portada y el dashboard comparten identidad visual, pero no navegación. Al
incorporar el futuro login con token, habrá que proteger las rutas HTTP del
dashboard y sus datos en el servidor. Ocultar enlaces o agregar una pantalla
de login en el navegador no constituiría control de acceso.

## Validación y límites

Se revisaron páginas y vistas en ambos temas y anchos de 1440, 768, 390 y 320 px.
Se comprobó ausencia de desborde horizontal, ubicación de la navegación, cambio
de tema y títulos de vista. La revisión en Chromium con viewport emulado no
sustituye una prueba táctil en iOS/Android ni una evaluación con lector de
pantalla. La estructura y los destinos deben contrastarse con el socio antes de
añadir secciones futuras.
