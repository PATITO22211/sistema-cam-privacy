# --- INICIO DEL ARCHIVO deteccion_login_es.py (Modo Static con Overlay JS + Freeze - CORREGIDO y con Duración Auto) ---

# region Imports
from flask import (
    Flask,
    render_template,
    Response,
    jsonify,
    request,
    session,
    redirect,
    url_for,
    flash,
)
from flask_socketio import SocketIO, join_room, leave_room
import cv2
import numpy as np
from ultralytics import YOLO
import torch
import time
import os
from datetime import datetime
import threading
import queue
from functools import wraps
import random
import traceback
import colorama
from colorama import Fore, Style, Back
from flask_socketio import SocketIO, join_room, leave_room, disconnect  # añadimos disconnect :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}

# endregion

# --- Inicializar Colorama ---
colorama.init(autoreset=True)

# --- Configuración General ---
FUENTES_CAMARA_ADMIN = [
    "http://192.168.100.17:8080/video",
    "http://192.168.100.44:8080/video",
]
FUENTE_CAMARA_ESPIA = "http://192.168.100.45:8080/video"
FUENTES_CAMARA_TODAS = FUENTES_CAMARA_ADMIN + [FUENTE_CAMARA_ESPIA]
INDICE_CAMARA_ESPIA = len(FUENTES_CAMARA_ADMIN)
RUTA_MODELO_YOLO = "yolo11s.pt"  # Asegúrate que este modelo existe o usa uno estándar
UMBRAL_DETECCION = 0.45  # Ajusta según necesites
ENFRIAMIENTO_SONIDO = 3.0
ANCHO_FRAME = 640
ALTO_FRAME = 480

# --- Configuración de Usuarios y Roles ---
CREDENCIALES_USUARIOS = {
    "admin": "admin",
    "1234": "1234",
}  # Cambia '1234' por user/pass para mamá
ROLES_USUARIOS = {"admin": "admin", "1234": "mama"}
mama_username = "1234"  # Define el nombre de usuario específico para mamá

# --- Configuración de Sabotaje ---
CALIDAD_PIXELACION = 2  # Calidad JPEG (0-100, bajo es peor)
DURACION_PREEMPTIVE_FREEZE = 5.0  # Segundos que dura el congelamiento automático


# --- Configuración App y SocketIO ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "clave-secreta-muy-MUY-insegura-cambiar!"
)  # ¡¡CAMBIA ESTO!!
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
    logger=False,  # silencia logs del servidor SocketIO
    engineio_logger=False,  # silencia logs de Engine.IO
)
# --- Variables Globales de Estado ---
colas_frames = [queue.Queue(maxsize=3) for _ in FUENTES_CAMARA_TODAS]
cola_frames_espia_manipulada = queue.Queue(maxsize=3)
camara_activa = [True] * len(FUENTES_CAMARA_TODAS)
estado_persona_detectada = [False] * len(FUENTES_CAMARA_ADMIN)
tiempo_ultimo_sonido = 0

# Control de Usuarios/Mamá
connected_users = {}
mama_login_count = 0
MAMA_ROOM = f"user_{mama_username}"
ADMIN_ROOM = "admin_room"

# Estado de Sabotaje
modo_sabotaje_activo = "normal"
espia_congelada_manual = False
intervalo_fps_reducido = 0.0  # Este valor será leído por hilo_camara
fps_ralentizar_actual = 0 # Guardar el FPS elegido para mostrarlo (opcional)
ultimo_frame_espia_congelado = None
tiempo_ultimo_frame_espia_manipulado = 0
modo_auto_activo = False
hilo_modo_auto = None
evento_parada_auto = threading.Event()
preemptive_freeze_activo = False
tiempo_inicio_preemptive_freeze = 0

FPS_RALENTIZAR_MIN = 1
FPS_RALENTIZAR_MAX = 5


# --- Bloqueos (Locks) ---
bloqueo_sonido = threading.Lock()
bloqueo_estado = threading.Lock()
bloqueo_manipulacion_espia = threading.Lock()
bloqueo_contador_mama = threading.Lock()
bloqueo_usuarios_conectados = threading.Lock()

# --- Funciones Helper ---
# region Funciones Helper (Sabotaje Frame, Dibujo) - Sin cambios
def sabotear_pixelacion(frame):
    """Reduce drásticamente la calidad JPEG del frame."""
    if frame is None or not isinstance(frame, np.ndarray):
        print(
            f"{Fore.RED}Error en sabotear_pixelacion: input no es un array NumPy válido."
        )
        return frame
    try:
        result, encoded_image = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), CALIDAD_PIXELACION]
        )
        if result:
            frame_pixelado = cv2.imdecode(encoded_image, 1)
            return frame_pixelado
        else:
            print(f"{Fore.YELLOW}Advertencia: Falló codificación JPEG para pixelación.")
            return frame
    except cv2.error as e:
        print(f"{Fore.RED}Error OpenCV en sabotear_pixelacion: {e}")
        print(
            f"{Fore.RED} -> Tipo de input: {type(frame)}, Shape: {getattr(frame, 'shape', 'N/A')}"
        )
        return frame
    except Exception as e:
        print(
            f"{Fore.YELLOW}Advertencia: Falló sabotaje de pixelación (error general): {e}"
        )
        return frame

def sabotear_gris(frame):
    """Convierte el frame a escala de grises (manteniendo 3 canales)."""
    if frame is None or not isinstance(frame, np.ndarray):
        print(f"{Fore.RED}Error en sabotear_gris: input no es un array NumPy válido.")
        return frame
    try:
        frame_gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_gris_bgr = cv2.cvtColor(frame_gris, cv2.COLOR_GRAY2BGR)
        return frame_gris_bgr
    except cv2.error as e:
        print(f"{Fore.RED}Error OpenCV en sabotear_gris: {e}")
        return frame
    except Exception as e:
        print(f"{Fore.YELLOW}Advertencia: Falló sabotaje a gris: {e}")
        return frame

def dibujar_recuadros_color(imagen, resultados):
    """Dibuja recuadros de detección de personas YOLO en la imagen."""
    persona_detectada_en_frame = False
    if imagen is None or not isinstance(imagen, np.ndarray):
        return imagen, persona_detectada_en_frame
    if not resultados:
        return imagen, persona_detectada_en_frame
    for resultado in resultados:
        if not hasattr(resultado, "boxes") or resultado.boxes is None:
            continue
        recuadros = resultado.boxes
        nombres = getattr(resultado, "names", {})
        for recuadro in recuadros:
            try:
                b = recuadro.xyxy[0].cpu().numpy()
                idx_clase = int(recuadro.cls[0].cpu().item())
                conf = recuadro.conf[0].cpu().item()
                nombre_etiqueta = nombres.get(idx_clase, f"Clase {idx_clase}")
                if nombre_etiqueta == "person" and conf >= UMBRAL_DETECCION:
                    persona_detectada_en_frame = True
                    color = (0, 0, 255)
                    etiqueta = f"{nombre_etiqueta} {conf:.2f}"
                    cv2.rectangle(
                        imagen, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 2
                    )
                    (tw, th), _ = cv2.getTextSize(
                        etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                    )
                    tx, ty = int(b[0]), int(b[1]) - 10
                    if ty < th:
                        ty = int(b[1]) + th + 5
                    cv2.rectangle(
                        imagen, (tx, ty - th - 2), (tx + tw + 2, ty), color, -1
                    )
                    cv2.putText(
                        imagen,
                        etiqueta,
                        (tx + 1, ty - 2),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
            except Exception as e:
                print(f"{Fore.RED}Error al dibujar recuadro específico: {e}")
    return imagen, persona_detectada_en_frame
# endregion

# --- Decorador de Autenticación ---
def login_required(f):
    """Decorador para requerir inicio de sesión en rutas Flask."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario" not in session or "rol" not in session:
            flash("Debes iniciar sesión para acceder a esta página.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- Hilo de Modo Auto (MODIFICADO para Ralentizar) ---
def gestionar_modo_auto():
    """Hilo que gestiona el cambio aleatorio de modos de sabotaje."""
    global modo_sabotaje_activo, espia_congelada_manual, ultimo_frame_espia_congelado, modo_auto_activo, intervalo_fps_reducido, fps_ralentizar_actual
    tag_auto = f"{Fore.BLUE}[AUTO MODE]{Style.RESET_ALL}"
    print(f"{tag_auto} {Fore.CYAN}Hilo de Modo Auto iniciado.")

    # --- MODIFICACIÓN AQUÍ: Añadir 'ralentizar' a los efectos ---
    efectos_backend = ["pixel", "gray", "freeze", "normal", "ralentizar"]
    efectos_overlay = ["static"]
    todos_efectos = efectos_backend + efectos_overlay
    # --- MODIFICACIÓN AQUÍ: Añadir peso para 'ralentizar' (ej: 4) ---
    pesos = [5, 0.5, 6, 1, 4, 5.5] # pixel, gray, freeze, normal, ralentizar, static

    while modo_auto_activo and not evento_parada_auto.is_set():
        efecto_elegido = random.choices(todos_efectos, weights=pesos, k=1)[0]
        duracion = random.uniform(3.5, 15.5)
        duracion_str = f"{duracion:.1f}s"
        mensaje_consola = f"AUTO: Aplicando '{efecto_elegido}' por {duracion_str}"
        es_modo_static = efecto_elegido == "static"
        es_modo_freeze = efecto_elegido == "freeze"
        es_modo_ralentizar = efecto_elegido == "ralentizar" # Nuevo flag

        with bloqueo_manipulacion_espia:
            if not modo_auto_activo: break # Salir si el modo auto se desactivó mientras esperábamos

            modo_sabotaje_activo = efecto_elegido
            espia_congelada_manual = es_modo_freeze # Solo freeze manual se maneja aquí

            # --- MODIFICACIÓN AQUÍ: Calcular FPS y intervalo para ralentizar ---
            if es_modo_ralentizar:
                fps_elegido = random.randint(FPS_RALENTIZAR_MIN, FPS_RALENTIZAR_MAX)
                intervalo_fps_reducido = 1.0 / fps_elegido if fps_elegido > 0 else 0.0
                fps_ralentizar_actual = fps_elegido # Guardar para posible log/info
                mensaje_consola += f" (~{fps_elegido} FPS)" # Añadir FPS al log
                print(f"{tag_auto} {Fore.CYAN}Ralentizar elegido: {fps_elegido} FPS -> Intervalo: {intervalo_fps_reducido:.3f}s")
                # Asegurar que otros estados conflictivos estén desactivados
                espia_congelada_manual = False
                if not preemptive_freeze_activo: ultimo_frame_espia_congelado = None
            else:
                # Si no es ralentizar, asegurar que el intervalo sea 0
                intervalo_fps_reducido = 0.0
                fps_ralentizar_actual = 0
                # Limpiar frame congelado si salimos de freeze y preemptive no está activo
                if not es_modo_freeze and not preemptive_freeze_activo:
                     ultimo_frame_espia_congelado = None

        print(f"{tag_auto} {Fore.YELLOW}{mensaje_consola}")

        # --- MODIFICACIÓN AQUÍ: Añadir 'fps' al payload si es ralentizar ---
        payload_status = {
            "mode": efecto_elegido,
            "active": efecto_elegido != "normal",
            "is_auto_running": True,
            "duration": duracion_str,
            "is_preemptive_active": preemptive_freeze_activo # Informar si preemptive está activo
        }
        if es_modo_ralentizar:
             payload_status["fps"] = fps_ralentizar_actual # Añadir FPS al estado para el admin

        socketio.emit("sabotage_status_update", payload_status, room=ADMIN_ROOM)

        # Emitir señal para overlay (static)
        socketio.emit("show_buffering_overlay", {"show": es_modo_static}, room=MAMA_ROOM)
        if es_modo_static:
            print(f"{tag_auto} {Fore.MAGENTA}Enviando señal SHOW overlay a mamá ({MAMA_ROOM}).")

        # Esperar la duración del efecto
        evento_parada_auto.wait(timeout=duracion)

    # --- Limpieza al salir del bucle ---
    with bloqueo_manipulacion_espia:
        # Volver a normal y limpiar estados de sabotaje
        modo_sabotaje_activo = "normal"
        espia_congelada_manual = False
        intervalo_fps_reducido = 0.0
        fps_ralentizar_actual = 0
        if not preemptive_freeze_activo:
            ultimo_frame_espia_congelado = None
        modo_auto_activo = False # Asegurar que el flag global esté bajo

    print(f"{tag_auto} {Fore.YELLOW}Modo Auto detenido. Volviendo a Normal.")

    # Emitir estado final Normal
    socketio.emit(
        "sabotage_status_update",
        {
            "mode": "normal", "active": False, "is_auto_running": False,
            "is_preemptive_active": preemptive_freeze_activo # Informar estado preemptive al salir
        },
        room=ADMIN_ROOM,
    )
    # Asegurar que el overlay se oculte al detener Auto
    socketio.emit("show_buffering_overlay", {"show": False}, room=MAMA_ROOM)
    print(f"{tag_auto} {Fore.GREEN}Enviando señal HIDE overlay final a mamá ({MAMA_ROOM}).")


# --- Hilo de Cámara (CORREGIDO - Sin cambios relevantes para esta solicitud) ---
def hilo_camara(id_camara, fuente_camara):
    """Hilo principal para capturar, procesar y encolar frames."""
    # Globales necesarias
    global colas_frames, camara_activa, tiempo_ultimo_sonido, estado_persona_detectada
    global cola_frames_espia_manipulada, ultimo_frame_espia_congelado, modo_sabotaje_activo
    global espia_congelada_manual, intervalo_fps_reducido, preemptive_freeze_activo
    global tiempo_inicio_preemptive_freeze, fps_ralentizar_actual

    es_camara_espia = id_camara == INDICE_CAMARA_ESPIA
    modelo = None; dispositivo = "cpu"
    cam_tag = (f"{Fore.MAGENTA}[CAM {id_camara}]{Style.RESET_ALL}" if not es_camara_espia
               else f"{Fore.YELLOW}[ESPÍA {id_camara}]{Style.RESET_ALL}")

    # Carga de modelo YOLO (sin cambios)
    if not es_camara_espia:
        print(f"{cam_tag} {Style.DIM}Cargando modelo YOLO ({RUTA_MODELO_YOLO})...")
        try:
            modelo = YOLO(RUTA_MODELO_YOLO)
            dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
            modelo.to(dispositivo)
            print(f"{cam_tag} {Fore.GREEN}Modelo YOLO cargado en {dispositivo.upper()}.")
        except Exception as e:
            print(f"{cam_tag} {Fore.RED}{Style.BRIGHT}Error al cargar YOLO: {e}")
            modelo = None
    else:
        print(f"{cam_tag} {Fore.CYAN}Iniciando hilo de cámara espía.")

    captura = None; errores_consecutivos = 0; max_errores = 15
    ultimo_estado_persona = False; ultimo_estado_activa = True; persona_afuera_antes = False

    while True:
        # --- 0. Comprobar si la cámara debe seguir activa ---
        with bloqueo_estado:
            activa = camara_activa[id_camara]
        if not activa:
            if ultimo_estado_activa:
                print(f"{cam_tag} {Fore.YELLOW}Recibida señal de parada...")
                ultimo_estado_activa = False
            break # Salir del bucle while

        # --- 1. Aplicar Ralentizar (Sleep) ANTES de leer el frame ---
        # Leer el estado actual del modo y el intervalo bajo bloqueo
        current_mode = "normal"
        current_interval = 0.0
        with bloqueo_manipulacion_espia:
            current_mode = modo_sabotaje_activo
            # Solo leer intervalo si el modo es ralentizar (por seguridad)
            if current_mode == "ralentizar":
                current_interval = intervalo_fps_reducido

        # Aplicar sleep si es la cámara espía, modo ralentizar y hay intervalo válido
        if es_camara_espia and current_mode == "ralentizar" and current_interval > 0:
            #print(f"{cam_tag} Ralentizando: sleep({current_interval:.3f}s)") # Log opcional muy verboso
            time.sleep(current_interval)

        try:
            # 1. Conexión y Lectura de Frame
            if captura is None or not captura.isOpened():
                print(f"{cam_tag} {Fore.CYAN}Intentando conectar...")
                captura = cv2.VideoCapture(fuente_camara, cv2.CAP_FFMPEG)
                captura.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)  # 5 segundos timeout
                captura.set(
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000
                )  # 5 segundos timeout lectura

                if not captura.isOpened():
                    print(f"{cam_tag} {Fore.RED}Error conexión.")
                    captura = None
                    time.sleep(5)
                    errores_consecutivos += 1
                    if ultimo_estado_activa:
                        socketio.emit(
                            "status_update", {"id": id_camara, "running": False}
                        )
                        ultimo_estado_activa = False
                    if errores_consecutivos >= max_errores:
                        print(f"{cam_tag} {Fore.RED}Max reintentos.")
                    with bloqueo_estado:
                        camara_activa[id_camara] = False
                        continue
                else:
                    print(f"{cam_tag} {Fore.GREEN}Conectada.")
                    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    errores_consecutivos = 0
                    if not ultimo_estado_activa:
                        ultimo_estado_activa = True
                        detect_status = False
                        if not es_camara_espia and id_camara < len(
                            estado_persona_detectada
                        ):
                            with bloqueo_estado:
                                detect_status = estado_persona_detectada[id_camara]
                        socketio.emit(
                            "status_update",
                            {
                                "id": id_camara,
                                "running": True,
                                "person_detected": detect_status,
                            },
                        )
            ret, frame = captura.read()
            if not ret or frame is None:
                print(
                    f"{cam_tag} {Fore.YELLOW}Fallo captura frame (ret={ret}, frame is None={frame is None})."
                )
                time.sleep(1)
                errores_consecutivos += 1
                if captura is not None:
                    captura.release()
                    captura = None
                if ultimo_estado_activa:
                    socketio.emit("status_update", {"id": id_camara, "running": False})
                    ultimo_estado_activa = False
                if errores_consecutivos >= max_errores:
                    print(f"{cam_tag} {Fore.RED}Max errores captura.")
                with bloqueo_estado:
                    camara_activa[id_camara] = False
                    continue
            errores_consecutivos = 0
            if not ultimo_estado_activa:
                ultimo_estado_activa = True
                detect_status = False
                if not es_camara_espia and id_camara < len(estado_persona_detectada):
                    with bloqueo_estado:
                        detect_status = estado_persona_detectada[id_camara]
                socketio.emit(
                    "status_update",
                    {
                        "id": id_camara,
                        "running": True,
                        "person_detected": detect_status,
                    },
                )

            # 2. Procesamiento Básico
            try:
                frame_redim = cv2.resize(frame, (ANCHO_FRAME, ALTO_FRAME))
            except cv2.error as e:
                print(f"{cam_tag} {Fore.YELLOW}Error redimensionando: {e}.")
                continue

            # 3. Lógica Específica
            if not es_camara_espia:
                # Cámara Admin (YOLO)
                if modelo:
                    resultados = modelo(frame_redim, verbose=False, device=dispositivo)
                    frame_anotado, detectada_ahora = dibujar_recuadros_color(
                        frame_redim.copy(), resultados
                    )
                    with bloqueo_estado:
                        estado_persona_detectada[id_camara] = detectada_ahora
                    if detectada_ahora != ultimo_estado_persona:
                        print(
                            f"{cam_tag}////////////////////////////// Cambio detección:  {Fore.RED if detectada_ahora else Fore.GREEN}{detectada_ahora}"
                        )
                        for i in range(3):
                            print(f"{cam_tag}//////////////////////////////")
                            
                        socketio.emit(
                            "status_update",
                            {
                                "id": id_camara,
                                "running": True,
                                "person_detected": detectada_ahora,
                            },
                        )
                        if detectada_ahora:
                            t_actual = time.time()
                            # Comprobar cooldown global
                            with bloqueo_sonido:
                                if t_actual - tiempo_ultimo_sonido >= ENFRIAMIENTO_SONIDO:
                                    print(
                                        f"{cam_tag} {Fore.RED}{Style.BRIGHT}ALERTA!{Style.RESET_ALL} Sonido emitido."
                                    )
                                    # Actualizar tiempo del último sonido
                                    tiempo_ultimo_sonido = t_actual
                                    # Emitir evento SOLO al admin
                                    socketio.emit("play_sound", room=ADMIN_ROOM)
                                # else: # Opcional: Log si está en cooldown
                                #    print(f"{cam_tag} {Style.DIM}Alerta sonido en cooldown global.")
                        # ---> FIN Lógica de Sonido <---

                        # Actualizar estado local para la próxima iteración
                        ultimo_estado_persona = detectada_ahora
                    try:
                        if colas_frames[id_camara].full():
                            colas_frames[id_camara].get_nowait()
                        colas_frames[id_camara].put_nowait(frame_anotado)
                    except queue.Full:
                        pass
                else:  # Modelo no cargado
                    try:
                        if colas_frames[id_camara].full():
                            colas_frames[id_camara].get_nowait()
                        colas_frames[id_camara].put_nowait(frame_redim)
                    except queue.Full:
                        pass
            else:
                # Cámara Espía
                frame_orig = frame_redim.copy()
                frame_mama = frame_orig

                # Cola Admin (frame original)
                try:
                    if colas_frames[id_camara].full():
                        colas_frames[id_camara].get_nowait()
                    colas_frames[id_camara].put_nowait(frame_orig)
                except queue.Full:
                    pass

                # Lógica Sabotaje
                ahora = time.time()
                with bloqueo_estado:
                    persona_afuera_ahora = any(estado_persona_detectada)

                # Preemptive Freeze
                preemptive_on = False
                preemptive_changed = False
                with bloqueo_manipulacion_espia:
                    current_preemptive = preemptive_freeze_activo
                    if (
                        persona_afuera_ahora
                        and not persona_afuera_antes
                        and not current_preemptive
                    ):
                        preemptive_freeze_activo = True
                        tiempo_inicio_preemptive_freeze = ahora
                        # Capturar frame para preemptive si no hay uno ya congelado manualmente
                        if ultimo_frame_espia_congelado is None:
                            ultimo_frame_espia_congelado = frame_orig.copy()
                        print(
                            f"{cam_tag} {Back.RED}{Fore.WHITE} PREEMPTIVE ON {Style.RESET_ALL}"
                        )
                        preemptive_changed = True
                    elif current_preemptive and (
                        ahora - tiempo_inicio_preemptive_freeze
                        >= DURACION_PREEMPTIVE_FREEZE
                    ):
                        preemptive_freeze_activo = False
                        # Solo limpiar frame congelado si no hay un freeze manual activo
                        if not espia_congelada_manual:
                            ultimo_frame_espia_congelado = None
                        print(f"{cam_tag} {Fore.YELLOW}Preemptive OFF (Timeout).")
                        preemptive_changed = True
                    preemptive_on = preemptive_freeze_activo

                if preemptive_changed:
                    # Emitir estado preemptive (sin duración, es un estado binario)
                    socketio.emit(
                        "sabotage_status_update",
                        {
                            "mode": "preemptive"
                            if preemptive_on
                            else modo_sabotaje_activo,  # Reporta modo actual si preemptive termina
                            "active": preemptive_on
                            or (modo_sabotaje_activo != "normal"),
                            "is_auto_running": modo_auto_activo,
                            "is_preemptive_active": preemptive_on,  # Añadimos explícitamente el estado preemptive
                        },
                        room=ADMIN_ROOM,
                    )

                # --- Aplicar Modo Sabotaje al Frame de Mamá ---
                frame_para_mama = None
                with bloqueo_manipulacion_espia: # Bloqueo para acceder modo_sabotaje y frame congelado
                    modo_actual_sabotaje = modo_sabotaje_activo # Leer modo actual

                    # Prioridad 1: Preemptive Freeze
                    if preemptive_on:
                        if ultimo_frame_espia_congelado is not None:
                            frame_para_mama = ultimo_frame_espia_congelado.copy()
                        else:
                            frame_para_mama = np.zeros_like(frame_orig) # Fallback negro
                            print(f"{cam_tag} {Fore.YELLOW}WARN: Preemptive activo pero sin frame congelado.")
                    # Prioridad 2: Otros modos (si Preemptive no está activo)
                    elif modo_actual_sabotaje == "freeze":
                        if not espia_congelada_manual: # Si entramos a freeze manual
                            if ultimo_frame_espia_congelado is None: # Capturar si no hay frame
                                ultimo_frame_espia_congelado = frame_orig.copy()
                                print(f"{cam_tag} {Fore.CYAN}Modo Freeze Manual: Capturando frame.")
                            espia_congelada_manual = True # Marcar como freeze manual
                        if ultimo_frame_espia_congelado is not None:
                            frame_para_mama = ultimo_frame_espia_congelado.copy()
                        else: # Fallback
                            frame_para_mama = np.zeros_like(frame_orig)
                            print(f"{cam_tag} {Fore.YELLOW}WARN: Freeze manual activo pero sin frame.")
                    elif modo_actual_sabotaje == "pixel":
                        frame_para_mama = sabotear_pixelacion(frame_orig)
                        if espia_congelada_manual: espia_congelada_manual = False; ultimo_frame_espia_congelado = None # Salir de freeze
                    elif modo_actual_sabotaje == "gray":
                        frame_para_mama = sabotear_gris(frame_orig)
                        if espia_congelada_manual: espia_congelada_manual = False; ultimo_frame_espia_congelado = None # Salir de freeze
                    # --- MODIFICACIÓN AQUÍ: Ralentizar solo afecta el sleep, no el frame ---
                    elif modo_actual_sabotaje == "ralentizar":
                        frame_para_mama = frame_orig # Usar frame original
                        if espia_congelada_manual: espia_congelada_manual = False; ultimo_frame_espia_congelado = None # Salir de freeze
                    elif modo_actual_sabotaje == "static":
                        frame_para_mama = frame_orig # Solo overlay JS
                        if espia_congelada_manual: espia_congelada_manual = False; ultimo_frame_espia_congelado = None # Salir de freeze
                    elif modo_actual_sabotaje == "normal":
                        frame_para_mama = frame_orig
                        if espia_congelada_manual: # Si salimos de freeze a normal
                            print(f"{cam_tag} {Fore.GREEN}Saliendo de Freeze Manual -> Normal.")
                            espia_congelada_manual = False; ultimo_frame_espia_congelado = None

                # Cola Mamá (frame manipulado)
                if frame_para_mama is not None:
                    try:
                        if cola_frames_espia_manipulada.full():
                            cola_frames_espia_manipulada.get_nowait()
                        cola_frames_espia_manipulada.put_nowait(frame_para_mama)
                    except queue.Full:
                        pass
                else:
                    # Si frame_para_mama es None (no debería pasar con la lógica actual, pero por seguridad)
                    try:
                        fallback_frame = np.zeros_like(
                            frame_orig
                        )  # Frame negro como fallback
                        if cola_frames_espia_manipulada.full():
                            cola_frames_espia_manipulada.get_nowait()
                        cola_frames_espia_manipulada.put_nowait(fallback_frame)
                    except queue.Full:
                        pass
                    except Exception as q_err:
                        print(
                            f"{cam_tag} {Fore.RED}Error en cola mamá fallback: {q_err}"
                        )

                persona_afuera_antes = persona_afuera_ahora

        except Exception as e:  # Captura general
            print(f"{cam_tag} {Fore.RED}{Style.BRIGHT}Error Bucle Principal: {e}")
            traceback.print_exc()
            if ultimo_estado_activa:
                socketio.emit("status_update", {"id": id_camara, "running": False})
                ultimo_estado_activa = False
            errores_consecutivos += 1
            time.sleep(5)
            if errores_consecutivos >= max_errores:
                print(f"{cam_tag} {Fore.RED}Max errores.")
            with bloqueo_estado:
                camara_activa[id_camara] = False

    # --- Limpieza hilo ---
    print(f"{cam_tag} {Style.DIM}Limpiando hilo...")
    if captura is not None:
        captura.release()
        print(f"{cam_tag} {Style.DIM}Captura liberada.")
    with bloqueo_estado:
        camara_activa[id_camara] = False
        if not es_camara_espia and id_camara < len(estado_persona_detectada):
            estado_persona_detectada[id_camara] = False
            print(f"{cam_tag} {Style.DIM}Detección reseteada.")
    if ultimo_estado_activa:
        socketio.emit("status_update", {"id": id_camara, "running": False})
        print(f"{cam_tag} {Style.DIM}Estado final 'stopped' emitido.")
    print(f"{cam_tag} {Fore.YELLOW}Hilo detenido completamente.")


# --- Rutas Flask ---
@app.route("/login", methods=["GET", "POST"])
def login():
    global mama_login_count
    tag_auth = f"{Fore.CYAN}[AUTH]{Style.RESET_ALL}"
    if request.method == "POST":
        user = request.form.get("usuario")
        pwd = request.form.get("contrasena")
        if user in CREDENCIALES_USUARIOS and CREDENCIALES_USUARIOS[user] == pwd:
            session["usuario"] = user
            session["rol"] = ROLES_USUARIOS[user]
            if session["rol"] == "mama" and user == mama_username:
                with bloqueo_contador_mama:
                    mama_login_count += 1
                    print(f"{tag_auth} {Fore.YELLOW}Mamá logins: {mama_login_count}.")
            print(f"{tag_auth} {Fore.GREEN}Login OK: '{user}' ({session['rol']}).")
            flash("Inicio correcto.", "success")
            return redirect(url_for("indice"))
        else:
            flash("Credenciales incorrectas.", "danger")
            print(f"{tag_auth} {Fore.YELLOW}Login FAIL: '{user}'.")
            return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    tag_auth = f"{Fore.CYAN}[AUTH]{Style.RESET_ALL}"
    user = session.get("usuario", "?")
    rol = session.get("rol", "?")
    session.clear()
    flash("Sesión cerrada.", "info")
    print(f"{tag_auth} {Fore.YELLOW}Logout: '{user}' ({rol}).")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def indice():
    rol = session["rol"]; user = session["usuario"]
    sabotage_mode = "normal"; auto_running = False; mama_logins = 0; indices = []
    is_preemptive = False; current_fps = 0

    if rol == "admin":
        indices = list(range(len(FUENTES_CAMARA_TODAS)))
        with bloqueo_manipulacion_espia:
            sabotage_mode = modo_sabotaje_activo
            auto_running = modo_auto_activo
            is_preemptive = preemptive_freeze_activo
            if sabotage_mode == 'ralentizar':
                current_fps = fps_ralentizar_actual # Pasar FPS actual si es ralentizar
        with bloqueo_contador_mama:
            mama_logins = mama_login_count
    elif rol == "mama" and user == mama_username:
        indices = ["espia"]
    else:
        flash("Error rol.", "danger"); return redirect(url_for("logout"))

    print(f"{Style.DIM}[ACCESS]{Style.RESET_ALL} Índice para '{user}' ({rol}).")
    # Pasar más datos iniciales si es admin
    template_data = {
        "rol": rol, "indices": indices, "indice_espia": INDICE_CAMARA_ESPIA,
        "initial_sabotage_mode": sabotage_mode,
        "initial_auto_mode_status": auto_running,
        "mama_logins": mama_logins
    }
    if rol == 'admin':
        template_data["initial_preemptive_status"] = is_preemptive
        template_data["initial_fps"] = current_fps # Añadir FPS inicial

    return render_template("index.html", **template_data)

@app.route("/video_feed/<cam_id_str>")
@login_required
def flujo_video(cam_id_str):
    rol = session["rol"]; user = session["usuario"]
    q_fuente = None; id_real = -1; feed_info = f"'{user}' ({rol})"

    # --- Lógica para Mamá ---
    if rol == "mama" and user == mama_username:
        if cam_id_str != "espia": # <-- Correcto, mamá solo pide 'espia'
            print(f"{Fore.YELLOW}[FEED DENIED]{Style.RESET_ALL} {feed_info} pidió '{cam_id_str}'.")
            return "Acceso denegado", 403
        # --- Asignación Clave ---
        id_real = INDICE_CAMARA_ESPIA # <-- Correcto, usamos el índice numérico real
        q_fuente = cola_frames_espia_manipulada # <-- CORRECTO, usa la cola manipulada
        print(f"{Fore.CYAN}[FEED REQ]{Style.RESET_ALL} Mamá ({user}) solicita '{cam_id_str}', usando cola MANIPULADA (Índice: {id_real}).") # <-- Añadir log

    # --- Lógica para Admin ---
    elif rol == "admin":
        try:
            id_real = int(cam_id_str); assert 0 <= id_real < len(FUENTES_CAMARA_TODAS)
            q_fuente = colas_frames[id_real] # <-- Correcto, admin usa las colas originales
            print(f"{Fore.CYAN}[FEED REQ]{Style.RESET_ALL} Admin ({user}) solicita cam '{cam_id_str}', usando cola ORIGINAL (Índice: {id_real}).") # <-- Añadir log
        except (ValueError, AssertionError):
            print(f"{Fore.YELLOW}[FEED DENIED]{Style.RESET_ALL} {feed_info} pidió ID inválido '{cam_id_str}'.")
            return "ID inválido", 400
    else:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} Rol inválido '{rol}' en flujo_video.")
        return "Rol inválido", 500

    # --- Verificar si la cola fue asignada ---
    if q_fuente is None:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} No se asignó una cola de fuente para {feed_info} pidiendo '{cam_id_str}'.")
        return "Error interno del servidor", 500

    # --- Verificar si la cámara asociada está activa ---
    # Usar id_real que ya determinamos
    with bloqueo_estado:
        activa = camara_activa[id_real] if 0 <= id_real < len(camara_activa) else False
    if not activa:
        print(f"{Fore.YELLOW}[FEED STOPPED]{Style.RESET_ALL} Cámara {id_real} inactiva para {feed_info} (solicitud: '{cam_id_str}').")
        return "Cámara inactiva", 404 # 404 podría ser más apropiado que 503

    # --- Generador (Sin cambios, pero verificar logs dentro) ---
    def generar(q, id_cam, info_local):
        feed_tag = f"{Fore.CYAN}[GENERADOR {id_cam} para {info_local}]{Style.RESET_ALL}"
        last_t = time.time()
        print(f"{feed_tag} Iniciando.")
        frames_yielded = 0
        while True:
            # Comprobar estado activo dentro del bucle también
            with bloqueo_estado:
                activa_gen = camara_activa[id_cam] if 0 <= id_cam < len(camara_activa) else False
            if not activa_gen:
                print(f"{feed_tag} {Fore.YELLOW}Detectada cámara inactiva. Fin generador.")
                break
            try:
                # Obtener frame de la cola asignada (q)
                # Aumentar un poco el timeout por si el modo ralentizar está activo
                frame = q.get(timeout=3.0) # <-- Timeout ligeramente aumentado
                if frame is None:
                    print(f"{feed_tag} {Fore.YELLOW}Recibido frame None de la cola. Saltando.")
                    continue

                # --- Log de Verificación del Frame ---
                if not isinstance(frame, np.ndarray) or frame.size == 0:
                     print(f"{feed_tag} {Fore.RED}ERROR: Frame inválido obtenido de la cola (Tipo: {type(frame)}, Size: {getattr(frame, 'size', 'N/A')}). Saltando.")
                     continue
                # print(f"{feed_tag} Frame obtenido: Shape={frame.shape}, Dtype={frame.dtype}") # Log muy verboso

                # Codificar frame a JPEG
                ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    # Enviar frame codificado
                    yield(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
                    frames_yielded += 1
                    # print(f"{feed_tag} Frame {frames_yielded} enviado.") # Log muy verboso
                    last_t = time.time() # Resetear temporizador de inactividad
                else:
                    # Error en la codificación
                    print(f"{feed_tag} {Fore.RED}ERROR al codificar frame a JPEG. Shape={frame.shape}, Dtype={frame.dtype}")
                    # Esperar un poco para no inundar logs si el problema persiste
                    time.sleep(0.2)

            except queue.Empty:
                # La cola está vacía, esperar un poco
                # print(f"{feed_tag} {Style.DIM}Cola vacía...") # Log muy verboso
                # Si lleva mucho tiempo vacía, asumir que algo va mal
                if time.time() - last_t > 15.0: # <-- Timeout de inactividad aumentado
                    print(f"{feed_tag} {Fore.RED}TIMEOUT: Sin frames en la cola por más de 15s. Fin generador.")
                    break
                continue # Reintentar obtener de la cola
            except Exception as e:
                # Capturar cualquier otro error inesperado
                print(f"{feed_tag} {Fore.RED}ERROR INESPERADO en el generador: {e}")
                traceback.print_exc()
                break # Salir del generador si hay un error grave
        print(f"{feed_tag} {Fore.YELLOW}Generador detenido. Total frames enviados: {frames_yielded}.")

    # Crear respuesta (Sin cambios)
    response = Response(generar(q_fuente, id_real, feed_info), mimetype="multipart/x-mixed-replace; boundary=frame")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/get_status")
@login_required
def obtener_estado():
    """Devuelve el estado actual de las cámaras, sabotaje y mamá."""
    rol = session['rol']
    estados_cam = []; sabotage_info = {}; mama_status = {}

    with bloqueo_estado:
        cam_activas = list(camara_activa)
        det_admin = list(estado_persona_detectada)

    if rol == "admin":
        for i, src in enumerate(FUENTES_CAMARA_TODAS):
            running = cam_activas[i] if i < len(cam_activas) else False
            detected = det_admin[i] if i < len(det_admin) and i != INDICE_CAMARA_ESPIA else False
            estados_cam.append({"id": i, "running": running, "person_detected": detected})

        with bloqueo_manipulacion_espia:
             sabotage_info = {
                "current_mode": modo_sabotaje_activo,
                "is_auto_running": modo_auto_activo,
                "is_preemptive_active": preemptive_freeze_activo
             }
             # Añadir FPS si el modo es ralentizar
             if modo_sabotaje_activo == 'ralentizar':
                 sabotage_info['fps'] = fps_ralentizar_actual

        with bloqueo_usuarios_conectados:
            is_mama_conn = any(ud.get('username') == mama_username for ud in connected_users.values())
        with bloqueo_contador_mama:
            logins = mama_login_count
        mama_status = {"status": "online" if is_mama_conn else "offline", "logins": logins}

    elif rol == "mama":
         running = cam_activas[INDICE_CAMARA_ESPIA] if INDICE_CAMARA_ESPIA < len(cam_activas) else False
         estados_cam.append({"id": "espia", "running": running, "person_detected": False})

    return jsonify({"cameras": estados_cam, "sabotage_status": sabotage_info, "mama_status": mama_status})
# endregion

# --- Ruta Control Espía (MODIFICADA para Ralentizar) ---
@app.route("/control_espia/<accion>", methods=["POST"])
@login_required
def controlar_camara_espia(accion):
    if session.get("rol") != "admin":
        return jsonify({"success": False, "message": "No autorizado"}), 403

    # Necesitamos acceso global a las variables de estado del sabotaje
    global modo_sabotaje_activo, modo_auto_activo, hilo_modo_auto, evento_parada_auto
    global espia_congelada_manual, ultimo_frame_espia_congelado, intervalo_fps_reducido
    global preemptive_freeze_activo, fps_ralentizar_actual

    mensaje_respuesta = ""
    modo_aplicado_final = "normal" # Default
    parar_hilo_auto_previo = False
    admin_user = session.get("usuario", "Admin")
    tag_control = f"{Fore.BLUE}[CTRL ESPÍA por {admin_user}]{Style.RESET_ALL}"

    # Leer estado preemptive ANTES del bloqueo para saber si limpiamos frame congelado
    estado_preemptive_antes = preemptive_freeze_activo

    payload_emit = {} # Para construir el payload del socketio emit

    with bloqueo_manipulacion_espia: # Proteger acceso a variables globales de sabotaje
        # --- Acción: Modo Automático ---
        if accion == "auto":
            if not modo_auto_activo:
                # Activar Auto
                print(f"{tag_control} {Fore.GREEN}Activando Auto.")
                modo_auto_activo = True
                modo_sabotaje_activo = "auto"
                evento_parada_auto.clear()
                espia_congelada_manual = False
                intervalo_fps_reducido = 0.0 # Auto gestionará esto
                fps_ralentizar_actual = 0
                if not estado_preemptive_antes: ultimo_frame_espia_congelado = None

                if hilo_modo_auto is None or not hilo_modo_auto.is_alive():
                    hilo_modo_auto = threading.Thread(target=gestionar_modo_auto, daemon=True)
                    hilo_modo_auto.start()

                mensaje_respuesta = "Modo Auto Activado."
                modo_aplicado_final = "auto"
                payload_emit = {"mode": "auto", "active": True, "is_auto_running": True, "is_preemptive_active": estado_preemptive_antes}
                socketio.emit("show_buffering_overlay", {"show": False}, room=MAMA_ROOM)
            else:
                # Desactivar Auto
                print(f"{tag_control} {Fore.YELLOW}Desactivando Auto.")
                modo_auto_activo = False
                modo_sabotaje_activo = "normal" # Volver a normal
                evento_parada_auto.set()
                parar_hilo_auto_previo = True
                espia_congelada_manual = False
                intervalo_fps_reducido = 0.0 # Resetear intervalo
                fps_ralentizar_actual = 0
                if not estado_preemptive_antes: ultimo_frame_espia_congelado = None

                mensaje_respuesta = "Modo Auto Desactivado. Volviendo a Normal."
                modo_aplicado_final = "normal"
                payload_emit = {"mode": "normal", "active": False, "is_auto_running": False, "is_preemptive_active": estado_preemptive_antes}
                socketio.emit("show_buffering_overlay", {"show": False}, room=MAMA_ROOM)
        # --- Acciones Manuales ---
        else:
            # Detener Auto si estaba activo
            if modo_auto_activo:
                print(f"{tag_control} {Fore.YELLOW}Acción manual '{accion}'. Deteniendo Auto...")
                modo_auto_activo = False
                evento_parada_auto.set()
                parar_hilo_auto_previo = True

            show_overlay = False
            is_active_state = True # La mayoría de modos son 'activos'

            # Resetear intervalo FPS por defecto, se calculará si es ralentizar
            intervalo_fps_reducido = 0.0
            fps_ralentizar_actual = 0
            # Limpiar frame congelado si no es freeze y preemptive no está activo
            if accion != "freeze" and not estado_preemptive_antes:
                ultimo_frame_espia_congelado = None
            # Asegurar que el flag de freeze manual esté bajo si no es freeze
            if accion != "freeze":
                espia_congelada_manual = False

            # Procesar acción específica
            if accion == "static":
                print(f"{tag_control} {Fore.MAGENTA}Activando 'Static' (Overlay JS).")
                modo_sabotaje_activo = "static"
                mensaje_respuesta = "Overlay Static activado (Manual)."
                modo_aplicado_final = "static"
                show_overlay = True
            elif accion == "freeze":
                 print(f"{tag_control} {Fore.CYAN}Activando 'Freeze' (Manual).")
                 modo_sabotaje_activo = "freeze"
                 # No ponemos espia_congelada_manual=True aquí, lo hace el hilo cámara
                 mensaje_respuesta = "Cámara espía: Congelada (Manual)."
                 modo_aplicado_final = "freeze"
            elif accion == "pixel":
                 print(f"{tag_control} Activando 'Pixel' (Manual).")
                 modo_sabotaje_activo = "pixel"
                 mensaje_respuesta = f"Pixel (Q={CALIDAD_PIXELACION}) (Manual)"
                 modo_aplicado_final = "pixel"
            elif accion == "gray":
                 print(f"{tag_control} Activando 'Gray' (Manual).")
                 modo_sabotaje_activo = "gray"
                 mensaje_respuesta = "Grises (Manual)"
                 modo_aplicado_final = "gray"
            # --- MODIFICACIÓN AQUÍ: Manejar 'ralentizar' ---
            elif accion == "ralentizar":
                 print(f"{tag_control} {Fore.CYAN}Activando 'Ralentizar' (Manual).")
                 modo_sabotaje_activo = "ralentizar"
                 # Calcular FPS e intervalo aleatorio AHORA
                 fps_elegido = random.randint(FPS_RALENTIZAR_MIN, FPS_RALENTIZAR_MAX)
                 intervalo_fps_reducido = 1.0 / fps_elegido if fps_elegido > 0 else 0.0
                 fps_ralentizar_actual = fps_elegido # Guardar para emitir
                 print(f"{tag_control} -> FPS elegido: {fps_elegido}, Intervalo: {intervalo_fps_reducido:.3f}s")
                 mensaje_respuesta = f"Ralentizar (~{fps_elegido} FPS) (Manual)"
                 modo_aplicado_final = "ralentizar"
                 # Añadir FPS al payload para informar al admin inmediatamente
                 payload_emit["fps"] = fps_elegido
            elif accion == "normal":
                 print(f"{tag_control} Activando 'Normal' (Manual).")
                 modo_sabotaje_activo = "normal"
                 mensaje_respuesta = "Normal (Manual)"
                 modo_aplicado_final = "normal"
                 is_active_state = False # Normal no es activo
            else: # Acción inválida
                 print(f"{tag_control} {Fore.RED}Acción inválida: {accion}")
                 modo_aplicado_final = modo_sabotaje_activo # No cambiar modo
                 return jsonify({"success": False, "message": f"Acción inválida: {accion}"}), 400

            # Construir y emitir estado actualizado para acciones manuales
            payload_emit.update({
                "mode": modo_aplicado_final,
                "active": is_active_state,
                "is_auto_running": False, # Siempre false en manual
                "is_preemptive_active": estado_preemptive_antes
            })
            socketio.emit("sabotage_status_update", payload_emit, room=ADMIN_ROOM)
            socketio.emit("show_buffering_overlay", {'show': show_overlay}, room=MAMA_ROOM)

    # Esperar al hilo Auto si se detuvo
    if parar_hilo_auto_previo and hilo_modo_auto is not None and hilo_modo_auto.is_alive():
        print(f"{tag_control} {Style.DIM}Esperando Hilo Auto para detenerse...")
        hilo_modo_auto.join(1.0)
        if hilo_modo_auto.is_alive(): print(f"{tag_control} {Fore.RED}WARN: Hilo Auto no terminó a tiempo.")
        else: print(f"{tag_control} {Style.DIM}Hilo Auto detenido.")

    return jsonify({"success": True, "message": mensaje_respuesta, "modo_actual": modo_aplicado_final})


# --- Eventos SocketIO ---
@socketio.on("connect")
def manejar_conexion():
    global connected_users, mama_login_count
    sid = request.sid; tag = f"{Fore.GREEN}[SocketIO]{Style.RESET_ALL}"
    if "usuario" not in session or "rol" not in session: print(f"{tag} {Fore.YELLOW}Rechazado (SID:{sid}): Sesión inválida."); return False
    user = session["usuario"]; rol = session["rol"]; color = Fore.GREEN if rol == "admin" else Fore.CYAN
    print(f"{tag} {color}Conectado:{Style.RESET_ALL} {user} ({rol}) (SID:{sid})")


    with bloqueo_usuarios_conectados:
        old_sid = next((s for s, d in connected_users.items() if d.get('username') == user and s != sid), None)
        if old_sid:
            print(f"{tag} Limpiando SID viejo {old_sid} para {user}.")
            try:
                old_rol = connected_users[old_sid].get('rol')
                room = MAMA_ROOM if old_rol=='mama' else ADMIN_ROOM if old_rol=='admin' else None
                leave_room(room, old_sid) if room else None
                del connected_users[old_sid]
            except Exception as e: print(f"{tag} {Fore.RED}Error limpiando SID viejo {old_sid}: {e}")
        connected_users[sid] = {"username": user, "rol": rol}

    if rol == "mama" and user == mama_username:
        join_room(MAMA_ROOM, sid); print(f"{tag} Mamá unida a '{MAMA_ROOM}'.")
        with bloqueo_contador_mama: logins = mama_login_count
        socketio.emit("mama_connection_status", {"status": "online", "logins": logins}, room=ADMIN_ROOM);
    elif rol == "admin":
        join_room(ADMIN_ROOM, sid); print(f"{tag} Admin unido a '{ADMIN_ROOM}'.")
        # Enviar estado actual de mamá al admin que se conecta
        with bloqueo_usuarios_conectados: is_mama_conn = any(ud.get('username') == mama_username for ud in connected_users.values())
        with bloqueo_contador_mama: logins = mama_login_count
        socketio.emit("mama_connection_status", {"status": "online" if is_mama_conn else "offline", "logins": logins}, room=sid)

        # Enviar estado actual del sabotaje al admin que se conecta
        with bloqueo_manipulacion_espia:
            current_sabotage_status = {
                "mode": modo_sabotaje_activo,
                "active": modo_sabotaje_activo != 'normal' or preemptive_freeze_activo,
                "is_auto_running": modo_auto_activo,
                "is_preemptive_active": preemptive_freeze_activo
            }
            # --- MODIFICACIÓN AQUÍ: Añadir FPS si es ralentizar ---
            if modo_sabotaje_activo == 'ralentizar':
                 current_sabotage_status['fps'] = fps_ralentizar_actual
            # No enviamos 'duration' aquí, el hilo auto lo hará si está activo
        socketio.emit("sabotage_status_update", current_sabotage_status, room=sid)

@socketio.on("disconnect")
def manejar_desconexion():
    global connected_users
    sid = request.sid
    tag = f"{Fore.YELLOW}[SocketIO]{Style.RESET_ALL}"
    with bloqueo_usuarios_conectados:
        if sid in connected_users:
            user_data = connected_users.pop(sid)
            user = user_data.get("username", "?")
            rol = user_data.get("rol", "?")
            color = Fore.GREEN if rol == "admin" else Fore.CYAN
            print(
                f"{tag} {color}Desconectado:{Style.RESET_ALL} {user} ({rol}) (SID:{sid})"
            )
            try:
                room = (
                    MAMA_ROOM
                    if rol == "mama" and user == mama_username
                    else ADMIN_ROOM
                    if rol == "admin"
                    else None
                )
                if room:
                    leave_room(room, sid)
                # Si la última mamá se desconecta, notificar a los admins
                if (
                    rol == "mama"
                    and user == mama_username
                    and not any(
                        ud.get("username") == mama_username
                        for ud in connected_users.values()
                    )
                ):
                    with bloqueo_contador_mama:
                        logins = mama_login_count  # Obtener los logins actuales
                    print(
                        f"{tag} Última mamá off. Notificando 'offline' ({logins} logins) -> '{ADMIN_ROOM}'."
                    )
                    socketio.emit(
                        "mama_connection_status",
                        {"status": "offline", "logins": logins},
                        room=ADMIN_ROOM,
                    )
            except Exception as e:
                print(f"{tag} {Fore.RED}Error al quitar de room {sid}: {e}")
        else:
            print(f"{tag} Desconectado SID desconocido: {sid}")


@socketio.on("admin_force_logout_mama")
def manejar_force_logout_mama(data):
    sid_admin = request.sid
    tag = f"{Fore.RED}[ADMIN ACTION]{Style.RESET_ALL}"

    # 1️⃣ Validar admin
    with bloqueo_usuarios_conectados:
        admin_info = connected_users.get(sid_admin, {})
    if admin_info.get("rol") != "admin":
        print(f"{tag} Rechazado logout (no admin): SID {sid_admin}")
        return {"success": False, "message": "No autorizado"}

    # 2️⃣ Agarrar los SIDs de mamá (sacando sólo la primera posición de cada tupla)
    try:
        raw = socketio.server.manager.get_participants(namespace="/", room=MAMA_ROOM) or []
    except Exception as e:
        print(f"{tag} Error get_participants para {MAMA_ROOM}: {e}")
        raw = []
    room_sids = [entry if isinstance(entry, str) else entry[0] for entry in raw]

    if not room_sids:
        print(f"{tag} Room '{MAMA_ROOM}' vacío.")
        return {"success": False, "message": "Mamá no está conectada."}

    msg = data.get("message", "Sesión terminada por el Admin.")
    print(f"{tag} Enviando logout a mamá, SIDs: {room_sids}")

    # 3️⃣ Emitir ONLY el evento «force_logout». El cliente hará redirect y se desconectará solo.
    for mama_sid in room_sids:
        socketio.emit("force_logout", {"message": msg}, room=mama_sid)

    # ✅ Ack al admin
    return {"success": True, "message": f"Logout enviado a {len(room_sids)} cliente(s)."}


@socketio.on("admin_complicar_sesion_mama")
def manejar_complicar_sesion_mama(data):
    sid_admin = request.sid
    tag = f"{Fore.RED}[ADMIN ACTION]{Style.RESET_ALL}"
    # 1️⃣ Validar que sea admin
    with bloqueo_usuarios_conectados:
        admin_info = connected_users.get(sid_admin)
        is_admin = admin_info and admin_info.get("rol") == "admin"
        user_admin = admin_info.get("username", "???") if admin_info else "???"
    if not is_admin:
        print(f"{tag} Rechazado complicar sesión (no admin): SID {sid_admin}")
        return {"success": False, "message": "No autorizado"}

    # 2️⃣ Obtener SIDs del room, convirtiendo a lista
    try:
        room_name = MAMA_ROOM  # e.g. "user_1234"
        room_sids = list(socketio.server.manager.get_participants(
            namespace="/",
            room=room_name
        ))
    except Exception as e:
        print(f"{tag} Error al obtener participantes de {room_name}: {e}")
        room_sids = []

    # 3️⃣ Emitir el evento si hay alguien conectado
    if room_sids:
        msg = data.get("message", "Error en la conexión: latencia inestable.")
        print(f"{tag} Admin '{user_admin}' complicando sesión -> '{room_name}' (SIDs: {room_sids}).")
        # Emitimos a todo el room
        socketio.emit("complicar_sesion", {"message": msg}, room=room_name)
        return {
            "success": True,
            "message": f"Señal de 'Complicación' enviada a {len(room_sids)} cliente(s)."
        }
    else:
        print(f"{tag} Intento de complicar sesión, pero '{room_name}' está vacío.")
        return {
            "success": False,
            "message": "Mamá no está conectada."
        }

# --- Ejecución Principal ---
if __name__ == "__main__":
    print(f"{Fore.MAGENTA}{Style.BRIGHT}--- Iniciando Aplicación ---{Style.RESET_ALL}")
    if not os.path.exists("static"):
        os.makedirs("static")
        print(f"{Fore.GREEN}Directorio 'static' creado.")
    if not os.path.exists("static/alert.mp3"):
        print(f"{Fore.YELLOW}WARN: static/alert.mp3 no encontrado.")
    if not os.path.exists("static/login_notification.mp3"):
        print(
            f"{Fore.YELLOW}WARN: static/login_notification.mp3 no encontrado."
        )  # Añadido chequeo

    print(f"{Fore.CYAN}Iniciando hilos cámaras...{Style.RESET_ALL}")
    hilos_camaras = []
    for i, fuente in enumerate(FUENTES_CAMARA_TODAS):
        with bloqueo_estado:
            if i >= len(camara_activa):
                camara_activa.append(True)
            else:
                camara_activa[i] = True
        hilo = threading.Thread(target=hilo_camara, args=(i, fuente), daemon=True)
        hilos_camaras.append(hilo)
        hilo.start()
        time.sleep(0.2)  # Dar un poco más de tiempo entre inicios

    host_ip = "0.0.0.0"
    port_num = 8000
    print(
        f"{Fore.GREEN}{Style.BRIGHT}Servidor Flask-SocketIO listo en http://{host_ip}:{port_num}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.YELLOW}Accede en tu navegador local a http://localhost:{port_num} o http://127.0.0.1:{port_num}"
    )
    print(
        f"{Fore.YELLOW}Desde otros dispositivos en la red, usa: http://<IP_LOCAL_DEL_SERVIDOR>:{port_num}"
    )

    try:
        # engineio_logger y logger en False para reducir verbosidad estándar
        socketio.run(app, host=host_ip, port=port_num, debug=True, use_reloader=False)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interrupción por teclado detectada...{Style.RESET_ALL}")
    except Exception as e:
        print(
            f"\n{Fore.RED}{Style.BRIGHT}Error al iniciar el servidor: {e}{Style.RESET_ALL}"
        )
        traceback.print_exc()
    finally:
        print(f"{Fore.MAGENTA}--- Iniciando proceso de apagado ---{Style.RESET_ALL}")
        tag_shutdown = f"{Fore.CYAN}[SHUTDOWN]{Style.RESET_ALL}"

        # 1. Detener hilo Auto si está activo
        if modo_auto_activo:
            print(f"{tag_shutdown} Deteniendo Hilo Auto...")
            modo_auto_activo = False  # Asegurar que el flag esté bajo antes de la señal
            evento_parada_auto.set()
            if hilo_modo_auto and hilo_modo_auto.is_alive():
                hilo_modo_auto.join(1.5)  # Esperar hasta 1.5 segundos
                if hilo_modo_auto.is_alive():
                    print(
                        f"{tag_shutdown} {Fore.RED}ADVERTENCIA: Hilo Auto no terminó limpiamente."
                    )
                else:
                    print(f"{tag_shutdown} {Fore.GREEN}Hilo Auto detenido.")
            else:
                print(
                    f"{tag_shutdown} {Fore.GREEN}Hilo Auto ya estaba detenido o no se inició."
                )

        # 2. Detener Hilos Cámara
        print(f"{tag_shutdown} Enviando señal de parada a Hilos Cámara...")
        with bloqueo_estado:
            for i in range(len(camara_activa)):
                camara_activa[i] = False

        print(f"{tag_shutdown} Esperando finalización de Hilos Cámara...")
        active_threads_after_join = []
        for i, h in enumerate(hilos_camaras):
            if h.is_alive():
                h.join(5.0)  # Esperar hasta 5 segundos por cada hilo
                if h.is_alive():
                    active_threads_after_join.append(i)
                    print(
                        f"{tag_shutdown} {Fore.RED}ADVERTENCIA: Hilo cámara {i} no terminó limpiamente."
                    )

        if not active_threads_after_join:
            print(
                f"{tag_shutdown} {Fore.GREEN}Todos los Hilos Cámara parecen detenidos."
            )
        else:
            print(
                f"{tag_shutdown} {Fore.RED}Algunos hilos de cámara ({active_threads_after_join}) no finalizaron."
            )

        # 3. Mensaje final
        print(f"{Fore.MAGENTA}--- Aplicación finalizada ---{Style.RESET_ALL}")

# --- FIN DEL ARCHIVO ---
