# --- CONTINUACIÓN DE main.py - RUTAS DE VIDEO Y CONTROL ---

@app.get("/video_feed/{cam_id_str}")
async def video_feed(request: Request, cam_id_str: str):
    """Stream de video para cámaras."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    rol = user["rol"]
    usuario = user["usuario"]
    
    # Validar acceso según rol
    if rol == "mama" and usuario == mama_username:
        if cam_id_str != "espia":
            raise HTTPException(status_code=403, detail="Acceso denegado")
        cam_id = INDICE_CAMARA_ESPIA
        cola_a_usar = cola_frames_espia_manipulada
    elif rol == "admin":
        try:
            cam_id = int(cam_id_str)
            if cam_id < 0 or cam_id >= len(FUENTES_CAMARA_TODAS):
                raise HTTPException(status_code=404, detail="Cámara no encontrada")
            cola_a_usar = colas_frames[cam_id]
        except ValueError:
            raise HTTPException(status_code=400, detail="ID de cámara inválido")
    else:
        raise HTTPException(status_code=403, detail="Rol no autorizado")
    
    # Verificar si la cámara está activa
    with bloqueo_estado:
        if not camara_activa[cam_id]:
            raise HTTPException(status_code=503, detail="Cámara no disponible")
    
    print(f"{Style.DIM}[VIDEO]{Style.RESET_ALL} Stream iniciado para '{usuario}' ({rol}) - Cámara {cam_id_str}")
    
    return StreamingResponse(
        generar_frames(cola_a_usar, cam_id, usuario),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

async def generar_frames(cola_frames, cam_id, usuario):
    """Generador de frames para streaming."""
    frames_verificados = 0
    frames_con_error = 0
    tiempo_ultimo_frame = time.time()
    timeout_inactividad = 30.0
    timeout_cola = 2.0
    
    tag_stream = f"{Style.DIM}[STREAM {cam_id}]{Style.RESET_ALL}"
    
    try:
        while True:
            try:
                # Obtener frame de la cola con timeout
                frame = cola_frames.get(timeout=timeout_cola)
                
                # Verificar que el frame sea válido
                if frame is None or frame.size == 0:
                    frames_con_error += 1
                    if frames_con_error % 10 == 0:
                        print(f"{tag_stream} {Fore.YELLOW}Frame inválido #{frames_con_error} para {usuario}")
                    continue
                
                # Codificar frame a JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ret:
                    frames_con_error += 1
                    continue
                
                frames_verificados += 1
                tiempo_ultimo_frame = time.time()
                
                # Log periódico
                if frames_verificados % 100 == 0:
                    print(f"{tag_stream} {Fore.GREEN}Frames enviados: {frames_verificados} para {usuario}")
                
                # Enviar frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + 
                       buffer.tobytes() + b'\r\n')
                
            except queue.Empty:
                # Verificar timeout de inactividad
                if time.time() - tiempo_ultimo_frame > timeout_inactividad:
                    print(f"{tag_stream} {Fore.YELLOW}Timeout de inactividad para {usuario}")
                    break
                continue
                
    except Exception as e:
        print(f"{tag_stream} {Fore.RED}Error en stream para {usuario}: {e}")
    finally:
        print(f"{tag_stream} {Fore.CYAN}Stream terminado para {usuario}. Frames: {frames_verificados}, Errores: {frames_con_error}")

@app.get("/get_status")
async def get_status(request: Request):
    """Obtener estado del sistema."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    rol = user["rol"]
    
    # Estado base
    status = {
        "cameras": {},
        "sabotage": {},
        "mama_status": {}
    }
    
    # Estado de cámaras
    with bloqueo_estado:
        for i in range(len(FUENTES_CAMARA_TODAS)):
            status["cameras"][str(i)] = {
                "running": camara_activa[i],
                "person_detected": estado_persona_detectada[i] if i < len(estado_persona_detectada) else False
            }
    
    # Estado de sabotaje (solo para admin)
    if rol == "admin":
        with bloqueo_manipulacion_espia:
            status["sabotage"] = {
                "mode": modo_sabotaje_activo,
                "active": modo_sabotaje_activo != "normal",
                "auto_mode_active": modo_auto_activo,
                "preemptive_freeze_active": preemptive_freeze_activo
            }
            if modo_sabotaje_activo == "ralentizar":
                status["sabotage"]["fps"] = fps_ralentizar_actual
        
        # Estado de mamá
        with bloqueo_contador_mama:
            status["mama_status"] = {
                "online": mama_login_count > 0,
                "login_count": mama_login_count
            }
    
    return status

# --- RUTAS DE CONTROL ---

@app.post("/control_espia")
async def control_espia(request: Request):
    """Control de sabotaje de cámara espía."""
    user = require_admin(request)
    
    form = await request.form()
    accion = form.get("accion", "").strip()
    
    tag_control = f"{Fore.MAGENTA}[CONTROL]{Style.RESET_ALL}"
    
    global modo_sabotaje_activo, espia_congelada_manual, ultimo_frame_espia_congelado
    global modo_auto_activo, evento_parada_auto, hilo_auto_mode
    global preemptive_freeze_activo, tiempo_inicio_preemptive_freeze
    global intervalo_fps_reducido, fps_ralentizar_actual
    
    with bloqueo_manipulacion_espia:
        if accion == "pixel":
            modo_sabotaje_activo = "pixel"
            espia_congelada_manual = False
            if not preemptive_freeze_activo:
                ultimo_frame_espia_congelado = None
            print(f"{tag_control} {Fore.CYAN}Sabotaje: Pixelación activada.")
            
        elif accion == "gray":
            modo_sabotaje_activo = "gray"
            espia_congelada_manual = False
            if not preemptive_freeze_activo:
                ultimo_frame_espia_congelado = None
            print(f"{tag_control} {Fore.CYAN}Sabotaje: Escala de grises activada.")
            
        elif accion == "freeze":
            modo_sabotaje_activo = "freeze"
            espia_congelada_manual = True
            print(f"{tag_control} {Fore.CYAN}Sabotaje: Congelación manual activada.")
            
        elif accion == "normal":
            modo_sabotaje_activo = "normal"
            espia_congelada_manual = False
            if not preemptive_freeze_activo:
                ultimo_frame_espia_congelado = None
            print(f"{tag_control} {Fore.GREEN}Sabotaje: Modo normal activado.")
            
        elif accion == "ralentizar":
            fps_elegido = random.randint(FPS_RALENTIZAR_MIN, FPS_RALENTIZAR_MAX)
            modo_sabotaje_activo = "ralentizar"
            espia_congelada_manual = False
            intervalo_fps_reducido = 1.0 / fps_elegido if fps_elegido > 0 else 0.0
            fps_ralentizar_actual = fps_elegido
            if not preemptive_freeze_activo:
                ultimo_frame_espia_congelado = None
            print(f"{tag_control} {Fore.CYAN}Sabotaje: Ralentización activada ({fps_elegido} FPS).")
            
        elif accion == "auto_on":
            if not modo_auto_activo:
                modo_auto_activo = True
                evento_parada_auto.clear()
                hilo_auto_mode = threading.Thread(target=gestionar_modo_auto, daemon=True)
                hilo_auto_mode.start()
                print(f"{tag_control} {Fore.BLUE}Modo Auto activado.")
            else:
                print(f"{tag_control} {Fore.YELLOW}Modo Auto ya estaba activo.")
                
        elif accion == "auto_off":
            if modo_auto_activo:
                modo_auto_activo = False
                evento_parada_auto.set()
                if hilo_auto_mode and hilo_auto_mode.is_alive():
                    hilo_auto_mode.join(timeout=2)
                print(f"{tag_control} {Fore.BLUE}Modo Auto desactivado.")
            else:
                print(f"{tag_control} {Fore.YELLOW}Modo Auto ya estaba inactivo.")
                
        elif accion == "preemptive_on":
            if not preemptive_freeze_activo:
                preemptive_freeze_activo = True
                tiempo_inicio_preemptive_freeze = time.time()
                print(f"{tag_control} {Fore.MAGENTA}Congelación Preemptiva activada.")
            else:
                print(f"{tag_control} {Fore.YELLOW}Congelación Preemptiva ya estaba activa.")
                
        elif accion == "preemptive_off":
            if preemptive_freeze_activo:
                preemptive_freeze_activo = False
                tiempo_inicio_preemptive_freeze = 0
                if not espia_congelada_manual:
                    ultimo_frame_espia_congelado = None
                print(f"{tag_control} {Fore.MAGENTA}Congelación Preemptiva desactivada.")
            else:
                print(f"{tag_control} {Fore.YELLOW}Congelación Preemptiva ya estaba inactiva.")
        else:
            print(f"{tag_control} {Fore.RED}Acción desconocida: {accion}")
            raise HTTPException(status_code=400, detail="Acción no válida")
    
    return {"status": "success", "action": accion}

@app.post("/toggle_camera")
async def toggle_camera(request: Request):
    """Activar/desactivar cámara."""
    user = require_admin(request)
    
    form = await request.form()
    try:
        cam_id = int(form.get("camera_id", -1))
        action = form.get("action", "").strip()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Parámetros inválidos")
    
    if cam_id < 0 or cam_id >= len(FUENTES_CAMARA_TODAS):
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    
    tag_toggle = f"{Fore.CYAN}[TOGGLE]{Style.RESET_ALL}"
    
    with bloqueo_estado:
        if action == "start":
            if not camara_activa[cam_id]:
                camara_activa[cam_id] = True
                # Iniciar hilo de cámara
                hilo = threading.Thread(
                    target=hilo_camara, 
                    args=(cam_id, FUENTES_CAMARA_TODAS[cam_id]), 
                    daemon=True
                )
                hilo.start()
                hilos_camara[cam_id] = hilo
                print(f"{tag_toggle} {Fore.GREEN}Cámara {cam_id} iniciada.")
            else:
                print(f"{tag_toggle} {Fore.YELLOW}Cámara {cam_id} ya estaba activa.")
                
        elif action == "stop":
            if camara_activa[cam_id]:
                camara_activa[cam_id] = False
                print(f"{tag_toggle} {Fore.YELLOW}Cámara {cam_id} detenida.")
            else:
                print(f"{tag_toggle} {Fore.YELLOW}Cámara {cam_id} ya estaba inactiva.")
        else:
            raise HTTPException(status_code=400, detail="Acción no válida")
    
    return {"status": "success", "camera_id": cam_id, "action": action}

@app.post("/add_ip_camera")
async def add_ip_camera(request: Request):
    """Agregar nueva cámara IP."""
    user = require_admin(request)
    
    form = await request.form()
    ip_url = form.get("ip_url", "").strip()
    
    if not ip_url:
        raise HTTPException(status_code=400, detail="URL de cámara IP requerida")
    
    tag_add = f"{Fore.GREEN}[ADD CAM]{Style.RESET_ALL}"
    
    # Agregar nueva fuente de cámara
    global FUENTES_CAMARA_TODAS, colas_frames, camara_activa, estado_persona_detectada, hilos_camara
    
    new_id = len(FUENTES_CAMARA_TODAS)
    FUENTES_CAMARA_TODAS.append(ip_url)
    
    # Inicializar estructuras para nueva cámara
    colas_frames.append(queue.Queue(maxsize=TAMANO_COLA_FRAMES))
    camara_activa.append(False)
    estado_persona_detectada.append(False)
    hilos_camara.append(None)
    
    print(f"{tag_add} {Fore.GREEN}Nueva cámara IP agregada: ID {new_id}, URL: {ip_url}")
    
    return {"status": "success", "camera_id": new_id, "url": ip_url}

@app.post("/force_logout_mama")
async def force_logout_mama(request: Request):
    """Forzar logout de mamá."""
    user = require_admin(request)
    
    tag_force = f"{Fore.RED}[FORCE LOGOUT]{Style.RESET_ALL}"
    
    # Enviar señal de logout forzado a todas las conexiones de mamá
    await manager.broadcast_to_room(
        json.dumps({"type": "force_logout", "data": {}}),
        MAMA_ROOM
    )
    
    print(f"{tag_force} {Fore.RED}Logout forzado enviado a mamá.")
    
    return {"status": "success", "message": "Logout forzado enviado"}

@app.post("/complicate_mama_session")
async def complicate_mama_session(request: Request):
    """Complicar sesión de mamá."""
    user = require_admin(request)
    
    tag_complicate = f"{Fore.YELLOW}[COMPLICATE]{Style.RESET_ALL}"
    
    # Enviar señal de complicación a todas las conexiones de mamá
    await manager.broadcast_to_room(
        json.dumps({"type": "complicate_session", "data": {}}),
        MAMA_ROOM
    )
    
    print(f"{tag_complicate} {Fore.YELLOW}Complicación de sesión enviada a mamá.")
    
    return {"status": "success", "message": "Complicación enviada"}