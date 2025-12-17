# --- CONTINUACIÓN DE main.py - RUTAS Y FUNCIONALIDADES ---

# --- Hilo de Modo Auto ---
def gestionar_modo_auto():
    """Hilo que gestiona el cambio aleatorio de modos de sabotaje."""
    global modo_sabotaje_activo, espia_congelada_manual, ultimo_frame_espia_congelado, modo_auto_activo, intervalo_fps_reducido, fps_ralentizar_actual
    tag_auto = f"{Fore.BLUE}[AUTO MODE]{Style.RESET_ALL}"
    print(f"{tag_auto} {Fore.CYAN}Hilo de Modo Auto iniciado.")

    efectos_backend = ["pixel", "gray", "freeze", "normal", "ralentizar"]
    efectos_overlay = ["static"]
    todos_efectos = efectos_backend + efectos_overlay
    pesos = [5, 0.5, 6, 1, 4, 5.5]

    while modo_auto_activo and not evento_parada_auto.is_set():
        efecto_elegido = random.choices(todos_efectos, weights=pesos, k=1)[0]
        duracion = random.uniform(3.5, 15.5)
        duracion_str = f"{duracion:.1f}s"
        mensaje_consola = f"AUTO: Aplicando '{efecto_elegido}' por {duracion_str}"
        es_modo_static = efecto_elegido == "static"
        es_modo_freeze = efecto_elegido == "freeze"
        es_modo_ralentizar = efecto_elegido == "ralentizar"

        with bloqueo_manipulacion_espia:
            if not modo_auto_activo: 
                break

            modo_sabotaje_activo = efecto_elegido
            espia_congelada_manual = es_modo_freeze

            if es_modo_ralentizar:
                fps_elegido = random.randint(FPS_RALENTIZAR_MIN, FPS_RALENTIZAR_MAX)
                intervalo_fps_reducido = 1.0 / fps_elegido if fps_elegido > 0 else 0.0
                fps_ralentizar_actual = fps_elegido
                mensaje_consola += f" (~{fps_elegido} FPS)"
                print(f"{tag_auto} {Fore.CYAN}Ralentizar elegido: {fps_elegido} FPS -> Intervalo: {intervalo_fps_reducido:.3f}s")
                espia_congelada_manual = False
                if not preemptive_freeze_activo: 
                    ultimo_frame_espia_congelado = None
            else:
                intervalo_fps_reducido = 0.0
                fps_ralentizar_actual = 0
                if not es_modo_freeze and not preemptive_freeze_activo:
                     ultimo_frame_espia_congelado = None

        print(f"{tag_auto} {Fore.YELLOW}{mensaje_consola}")

        payload_status = {
            "mode": efecto_elegido,
            "active": efecto_elegido != "normal",
            "is_auto_running": True,
            "duration": duracion_str,
            "is_preemptive_active": preemptive_freeze_activo
        }
        if es_modo_ralentizar:
             payload_status["fps"] = fps_ralentizar_actual

        # Enviar a través de WebSocket
        asyncio.create_task(manager.broadcast_to_room(
            json.dumps({"type": "sabotage_status_update", "data": payload_status}), 
            ADMIN_ROOM
        ))

        # Emitir señal para overlay (static)
        asyncio.create_task(manager.broadcast_to_room(
            json.dumps({"type": "show_buffering_overlay", "data": {"show": es_modo_static}}), 
            MAMA_ROOM
        ))
        
        if es_modo_static:
            print(f"{tag_auto} {Fore.MAGENTA}Enviando señal SHOW overlay a mamá ({MAMA_ROOM}).")

        evento_parada_auto.wait(timeout=duracion)

    # Limpieza al salir del bucle
    with bloqueo_manipulacion_espia:
        modo_sabotaje_activo = "normal"
        espia_congelada_manual = False
        intervalo_fps_reducido = 0.0
        fps_ralentizar_actual = 0
        if not preemptive_freeze_activo:
            ultimo_frame_espia_congelado = None
        modo_auto_activo = False

    print(f"{tag_auto} {Fore.YELLOW}Modo Auto detenido. Volviendo a Normal.")

    # Emitir estado final Normal
    asyncio.create_task(manager.broadcast_to_room(
        json.dumps({
            "type": "sabotage_status_update",
            "data": {
                "mode": "normal", 
                "active": False, 
                "is_auto_running": False,
                "is_preemptive_active": preemptive_freeze_activo
            }
        }), 
        ADMIN_ROOM
    ))
    
    asyncio.create_task(manager.broadcast_to_room(
        json.dumps({"type": "show_buffering_overlay", "data": {"show": False}}), 
        MAMA_ROOM
    ))
    print(f"{tag_auto} {Fore.GREEN}Enviando señal HIDE overlay final a mamá ({MAMA_ROOM}).")

# --- Hilo de Cámara ---
def hilo_camara(id_camara, fuente_camara):
    """Hilo principal para capturar, procesar y encolar frames."""
    global colas_frames, camara_activa, tiempo_ultimo_sonido, estado_persona_detectada
    global cola_frames_espia_manipulada, ultimo_frame_espia_congelado, modo_sabotaje_activo
    global espia_congelada_manual, intervalo_fps_reducido, preemptive_freeze_activo
    global tiempo_inicio_preemptive_freeze, fps_ralentizar_actual

    es_camara_espia = id_camara == INDICE_CAMARA_ESPIA
    modelo = None
    dispositivo = "cpu"
    cam_tag = (f"{Fore.MAGENTA}[CAM {id_camara}]{Style.RESET_ALL}" if not es_camara_espia
               else f"{Fore.YELLOW}[ESPÍA {id_camara}]{Style.RESET_ALL}")

    # Carga de modelo YOLO
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

    captura = None
    errores_consecutivos = 0
    max_errores = 15
    ultimo_estado_persona = False
    ultimo_estado_activa = True
    persona_afuera_antes = False

    while True:
        # Comprobar si la cámara debe seguir activa
        with bloqueo_estado:
            activa = camara_activa[id_camara]
        if not activa:
            if ultimo_estado_activa:
                print(f"{cam_tag} {Fore.YELLOW}Recibida señal de parada...")
                ultimo_estado_activa = False
            break

        # Aplicar Ralentizar (Sleep) ANTES de leer el frame
        current_mode = "normal"
        current_interval = 0.0
        with bloqueo_manipulacion_espia:
            current_mode = modo_sabotaje_activo
            if current_mode == "ralentizar":
                current_interval = intervalo_fps_reducido

        if es_camara_espia and current_mode == "ralentizar" and current_interval > 0:
            time.sleep(current_interval)

        try:
            # Conexión y Lectura de Frame
            if captura is None or not captura.isOpened():
                print(f"{cam_tag} {Fore.CYAN}Intentando conectar...")
                captura = cv2.VideoCapture(fuente_camara, cv2.CAP_FFMPEG)
                captura.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                captura.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

                if not captura.isOpened():
                    print(f"{cam_tag} {Fore.RED}Error conexión.")
                    captura = None
                    time.sleep(5)
                    errores_consecutivos += 1
                    if ultimo_estado_activa:
                        # Enviar estado por WebSocket
                        asyncio.create_task(manager.broadcast_to_room(
                            json.dumps({"type": "status_update", "data": {"id": id_camara, "running": False}}),
                            ADMIN_ROOM
                        ))
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

            ret, frame = captura.read()
            if not ret or frame is None:
                print(f"{cam_tag} {Fore.RED}Error al leer frame.")
                errores_consecutivos += 1
                if errores_consecutivos >= 5:
                    print(f"{cam_tag} {Fore.RED}Demasiados errores consecutivos. Reconectando...")
                    if captura:
                        captura.release()
                    captura = None
                    errores_consecutivos = 0
                time.sleep(0.1)
                continue

            errores_consecutivos = 0
            frame = cv2.resize(frame, (ANCHO_FRAME, ALTO_FRAME))

            # Procesamiento específico por tipo de cámara
            if not es_camara_espia:
                # Cámara admin: detección YOLO
                persona_detectada_actual = False
                if modelo is not None:
                    try:
                        resultados = modelo(frame, verbose=False)
                        frame, persona_detectada_actual = dibujar_recuadros_color(frame, resultados)
                    except Exception as e:
                        print(f"{cam_tag} {Fore.RED}Error en detección YOLO: {e}")

                # Actualizar estado de detección
                with bloqueo_estado:
                    if id_camara < len(estado_persona_detectada):
                        estado_persona_detectada[id_camara] = persona_detectada_actual

                # Notificaciones de sonido y WebSocket
                if persona_detectada_actual != ultimo_estado_persona:
                    ultimo_estado_persona = persona_detectada_actual
                    if persona_detectada_actual:
                        print(f"{cam_tag} {Fore.RED}¡PERSONA DETECTADA!")
                        
                        # Enviar notificación por WebSocket
                        asyncio.create_task(manager.broadcast_to_room(
                            json.dumps({
                                "type": "person_detected", 
                                "data": {"camera_id": id_camara, "detected": True}
                            }),
                            ADMIN_ROOM
                        ))

                        # Sonido con enfriamiento
                        with bloqueo_sonido:
                            tiempo_actual = time.time()
                            if tiempo_actual - tiempo_ultimo_sonido >= ENFRIAMIENTO_SONIDO:
                                tiempo_ultimo_sonido = tiempo_actual
                                asyncio.create_task(manager.broadcast_to_room(
                                    json.dumps({"type": "play_alert_sound", "data": {}}),
                                    ADMIN_ROOM
                                ))
                    else:
                        print(f"{cam_tag} {Fore.GREEN}Persona ya no detectada.")

                # Encolar frame original para admin
                try:
                    colas_frames[id_camara].put_nowait(frame.copy())
                except queue.Full:
                    try:
                        colas_frames[id_camara].get_nowait()
                        colas_frames[id_camara].put_nowait(frame.copy())
                    except queue.Empty:
                        pass

            else:
                # Cámara espía: aplicar sabotaje
                frame_para_espia = frame.copy()
                
                with bloqueo_manipulacion_espia:
                    modo_actual = modo_sabotaje_activo
                    freeze_manual = espia_congelada_manual
                    freeze_preemptive = preemptive_freeze_activo

                # Aplicar efectos de sabotaje
                if freeze_manual or freeze_preemptive:
                    if ultimo_frame_espia_congelado is not None:
                        frame_para_espia = ultimo_frame_espia_congelado.copy()
                    else:
                        ultimo_frame_espia_congelado = frame_para_espia.copy()
                elif modo_actual == "pixel":
                    frame_para_espia = sabotear_pixelacion(frame_para_espia)
                elif modo_actual == "gray":
                    frame_para_espia = sabotear_gris(frame_para_espia)

                # Encolar frame original para admin
                try:
                    colas_frames[id_camara].put_nowait(frame.copy())
                except queue.Full:
                    try:
                        colas_frames[id_camara].get_nowait()
                        colas_frames[id_camara].put_nowait(frame.copy())
                    except queue.Empty:
                        pass

                # Encolar frame manipulado para mamá
                try:
                    cola_frames_espia_manipulada.put_nowait(frame_para_espia)
                except queue.Full:
                    try:
                        cola_frames_espia_manipulada.get_nowait()
                        cola_frames_espia_manipulada.put_nowait(frame_para_espia)
                    except queue.Empty:
                        pass

        except Exception as e:
            print(f"{cam_tag} {Fore.RED}Error inesperado: {e}")
            traceback.print_exc()
            time.sleep(1)

    print(f"{cam_tag} {Fore.YELLOW}Hilo de cámara terminado.")
    if captura:
        captura.release()

# --- RUTAS FASTAPI ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal - redirige según autenticación."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    rol = user["rol"]
    usuario = user["usuario"]
    
    sabotage_mode = "normal"
    auto_running = False
    mama_logins = 0
    indices = []
    is_preemptive = False
    current_fps = 0

    if rol == "admin":
        indices = list(range(len(FUENTES_CAMARA_TODAS)))
        with bloqueo_manipulacion_espia:
            sabotage_mode = modo_sabotaje_activo
            auto_running = modo_auto_activo
            is_preemptive = preemptive_freeze_activo
            if sabotage_mode == 'ralentizar':
                current_fps = fps_ralentizar_actual
        with bloqueo_contador_mama:
            mama_logins = mama_login_count
    elif rol == "mama" and usuario == mama_username:
        indices = ["espia"]
    else:
        raise HTTPException(status_code=403, detail="Error de rol")

    print(f"{Style.DIM}[ACCESS]{Style.RESET_ALL} Índice para '{usuario}' ({rol}).")
    
    template_data = {
        "request": request,
        "rol": rol, 
        "indices": indices, 
        "indice_espia": INDICE_CAMARA_ESPIA,
        "initial_sabotage_mode": sabotage_mode,
        "initial_auto_mode_status": auto_running,
        "mama_logins": mama_logins
    }
    
    if rol == 'admin':
        template_data["initial_preemptive_status"] = is_preemptive
        template_data["initial_fps"] = current_fps

    return templates.TemplateResponse("index.html", template_data)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login."""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_post(request: Request):
    """Procesar login."""
    form = await request.form()
    usuario = form.get("usuario", "").strip()
    password = form.get("password", "").strip()
    
    tag_auth = f"{Fore.CYAN}[AUTH]{Style.RESET_ALL}"
    
    if usuario in CREDENCIALES_USUARIOS and CREDENCIALES_USUARIOS[usuario] == password:
        rol = ROLES_USUARIOS[usuario]
        request.session["usuario"] = usuario
        request.session["rol"] = rol
        
        # Incrementar contador de mamá
        if usuario == mama_username:
            with bloqueo_contador_mama:
                global mama_login_count
                mama_login_count += 1
                logins = mama_login_count
            
            print(f"{tag_auth} {Fore.GREEN}Login mamá #{logins}: '{usuario}'")
            
            # Notificar a admin
            asyncio.create_task(manager.broadcast_to_room(
                json.dumps({
                    "type": "mama_connection_status",
                    "data": {"status": "online", "logins": logins}
                }),
                ADMIN_ROOM
            ))
        else:
            print(f"{tag_auth} {Fore.GREEN}Login exitoso: '{usuario}' ({rol})")
        
        return RedirectResponse(url="/", status_code=302)
    else:
        print(f"{tag_auth} {Fore.RED}Login fallido: '{usuario}'")
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Credenciales inválidas"
        })

@app.get("/logout")
async def logout(request: Request):
    """Cerrar sesión."""
    user = get_current_user(request)
    if user:
        tag_auth = f"{Fore.CYAN}[AUTH]{Style.RESET_ALL}"
        print(f"{tag_auth} {Fore.YELLOW}Logout: '{user['usuario']}' ({user['rol']}).")
    
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)