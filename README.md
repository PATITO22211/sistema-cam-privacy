# 🎥 Sistema de Vigilancia "Anti-Nervios" con Control de Privacidad

## 📖 Historia y Contexto
la quité, me dió pena
<!-- Este proyecto nació de una necesidad muy específica: **poder estar con mi novia en mi cuarto con la puerta cerrada, sin que mi mamá se preocupara.**

Mi mamá insistía en que la puerta debía estar abierta. Yo le propuse una solución moderna: poner una cámara en mi cuarto que ella pudiera ver desde su celular para "vigilarnos". Ella aceptó.

Lo que ella no sabe es que esa cámara es parte de este sistema inteligente. Mientras ella cree que tiene el control, yo tengo un panel de administración que me permite:

1. **Saber si alguien se acerca**: Tengo otras cámaras (celulares viejos) en el pasillo y entrada que detectan personas automáticamente y me avisan vía pitidos.
2. **Controlar lo que ella ve**: Si necesito privacidad absoluta, puedo "sabotear" su transmisión con un solo clic (congelar la imagen, pixelarla o simular que el video carga o hasta expulsarla de su sesión), dándome el tiempo y la tranquilidad que necesito sin levantar sospechas.

El objetivo final no es solo la vigilancia, sino **eliminar los nervios** de que alguien entre de sorpresa. -->

## ⚙️ ¿Cómo Funciona?

El sistema actúa como un intermediario inteligente entre las cámaras y los usuarios.

1. **Las Cámaras (Celulares baratos con android+ IP Webcam)**:

   * No necesitas cámaras costosas. El sistema está diseñado para usar **celulares económicos (tipo "deshechables")** que tengas guardados.
   * Simplemente instalas la aplicación  [IP WebCam](https://play.google.com/store/apps/details?id=com.pas.webcam&hl=es_CR) (Android) en ellos, los conectas al WiFi y los colocas estratégicamente (pasillo, entrada, cuarto).
2. **El Cerebro (Tu PC)**:

   * El servidor (escrito en Python con **FastAPI**) se conecta a todas las cámaras.
   * Usa **Inteligencia Artificial (YOLOv8)** para analizar el video de las cámaras de seguridad (pasillo/entrada) en tiempo real.
   * Si detecta una persona acercándose, te envía una **alerta de audio y visual** inmediata a tu panel.
3. **La "Ilusión" (Vista de Mamá)**:

   * El sistema toma el video de la cámara de tu cuarto, lo procesa y se lo retransmite a tu mamá.
   * Tú tienes varios botones de "Sabotaje". Al activar alguno, el sistema intercepta el video antes de que le llegue a ella y le aplica efectos (congelado, pixelado, ralentizado, etc.) que parecen fallos de internet, dándote la excusa perfecta para la privacidad.

## 🚀 Funcionalidades Principales

### 👁️ Panel de Administrador (Tu Vista)

- **Monitoreo Total**: Ves todas las cámaras simultáneamente.
- **Radar de Intrusos**: Detección automática de personas en el pasillo. ¡Sabrás que alguien viene antes de que toquen la puerta!
- **Control de Sabotaje**: Panel de control para alterar la cámara de tu cuarto.

### 👵 Panel de Usuario Limitado ("Mamá")

- **Acceso Restringido**: Solo puede ver la cámara del cuarto.
- **Feed Manipulable**: Recibe la señal procesada que tú controlas.

### 🎮 Modos de Sabotaje

Efectos diseñados para parecer errores técnicos creíbles:

- **Freeze**: Congela la imagen en el último momento "seguro".
- **Pixel**: Baja la resolución drásticamente (simula mala señal).
- **Loading**: Muestra un ícono de carga girando sobre la imagen.
- **Slow Motion**: Baja los cuadros por segundo (video entrecortado).
- **Modo Auto**: El sistema aplica "fallos" aleatorios automáticamente para mantener la credibilidad sin que tengas que tocar nada.

## 🛠️ Requisitos

- **Hardware**:

  - 1 PC/Laptop para correr el sistema.
  - Una GPU buena para procesamiento de YOLO (Yo usé una rtx 3060)
  - 16 GB de RAM (yo usé 32, te recomiendo 32)
  - Intel i5 o superior (yo usé intel i7)
  - 2 o 3 Celulares/tablets Android económicos (pueden ser "celulares del Oxxo" o viejos).
  - Red WiFi local.
- **Software**:

  - App **IP Webcam** (gratis en Play Store) instalada en los celulares.
  - CUDA 11.8
  - **Python 3.10+** en la PC.
  - Desactivar el firewall de red privada (para que la otra persona pueda entrar a ver la cámara)

## 📦 Instalación Rápida

1. **Clonar el repositorio**
2. **Instalar dependencias**

   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Configurar Cámaras**

   * Abre la app **IP Webcam** en tus celulares y dale a "Start Server" (te recomiendo la configuración de resolución de video de 320x240 en la cámara que estará en tu cuarto y 640x480 para las demás cámaras)
   * Anota las direcciones IP que aparecen en la pantalla (ej. `http://192.168.1.50:8080`).
   * Edita el archivo `models/config.py`:

   ```python
   class CameraConfig:
       # Cámaras de seguridad (Pasillo/Entrada) - Detectan si alguien viene
       ADMIN_CAMERAS = [
           "http://192.168.1.50:8080/video", 
       ]

       # Cámara del cuarto (La que ve Mamá)
       SPY_CAMERA = "http://192.168.1.51:8080/video"
   ```
4. **Iniciar**
   Ejecuta el archivo `iniciar.bat` o corre:

   ```bash
   python main.py
   ```

## 🛡️ Uso

1. Dale a tu mamá la dirección de la ip de tu computadora (lo puedes saber ejecutando ipconfig en cmd)
2. `http://TU-IP:8000/login` y las credenciales `1234` / `1234`.
3. Tú entra a `localhost:8000` como `admin` / `admin`.
4. ¡Disfruta de tu privacidad sin nervios! Si el sistema te avisa que alguien viene, o si simplemente quieres intimidad, activa el sabotaje y relájate.

## 📺 Aviso en la tele (TvOverlay)

Opcional. Si quieres que la Android TV te avise cuando cualquier cámara detecte a una persona:

1. En la tele activa las opciones de desarrollador y la depuración ADB por red. En la mayoría es Ajustes, Acerca de, pulsa varias veces Compilación, y luego en Opciones de desarrollador enciende Depuración USB (y Depuración de red, si aparece).
2. Instala la app **TvOverlay** desde la Play Store, ábrela y acepta el permiso de dibujar encima de otras apps. El API local queda en el puerto `5001`.
3. En la PC instala platform-tools de Android para tener el comando `adb` en el PATH. Si lo dejas en otra carpeta, pon la ruta en `adb_path`.
4. Edita `models/config.py`, clase `TvOverlayConfig`: pon `enabled = True` y la IP de la tele en `tv_ip`. El puerto ADB por defecto es `5555`. El cooldown (30 s por cámara) evita un aviso en cada frame.
5. Prueba con `python scripts/test_tv_notify.py` o con el botón **Probar aviso TV** del panel de admin. El texto sale así: `Cámara 1 detectó a una persona` (o el nombre de la cámara, si le pusiste uno).

El aviso sale por ADB (`adb connect` y de ahí el `POST /notify` de TvOverlay). Si ADB no responde, se intenta `http://IP_DE_LA_TELE:5001/notify`. Si falla, se anota en la consola y el video sigue igual.

---

**Disclaimer**: Este proyecto es una solución técnica creativa a un problema doméstico. Úsalo con responsabilidad.

jajajaja
