# --- CONTINUACIÓN DE main.py - WEBSOCKETS Y FUNCIÓN PRINCIPAL ---

# --- WEBSOCKETS ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint principal de WebSocket."""
    await websocket.accept()

    global mama_login_count
    
    # Obtener información de sesión desde cookies
    cookies = websocket.cookies
    session_cookie = cookies.get("session")
    
    user = None
    if session_cookie:
        try:
            # Decodificar sesión (simplificado para este ejemplo)
            # En producción usar una librería de sesiones más robusta
            import base64
            import json as json_lib
            decoded = base64.b64decode(session_cookie).decode()
            session_data = json_lib.loads(decoded)
            if "usuario" in session_data and "rol" in session_data:
                user = session_data
        except:
            pass
    
    if not user:
        await websocket.close(code=1008, reason="No autenticado")
        return
    
    usuario = user["usuario"]
    rol = user["rol"]
    room = ADMIN_ROOM if rol == "admin" else MAMA_ROOM
    
    tag_ws = f"{Fore.CYAN}[WS]{Style.RESET_ALL}"
    print(f"{tag_ws} {Fore.GREEN}Conexión WebSocket: '{usuario}' ({rol}) -> {room}")
    
    # Agregar conexión al manager
    await manager.connect(websocket, usuario, room)
    
    # Enviar estado inicial
    if rol == "admin":
        # Enviar estado completo del sistema
        status_data = {
            "cameras": {},
            "sabotage": {},
            "mama_status": {}
        }
        
        with bloqueo_estado:
            for i in range(len(FUENTES_CAMARA_TODAS)):
                status_data["cameras"][str(i)] = {
                    "running": camara_activa[i],
                    "person_detected": estado_persona_detectada[i] if i < len(estado_persona_detectada) else False
                }
        
        with bloqueo_manipulacion_espia:
            status_data["sabotage"] = {
                "mode": modo_sabotaje_activo,
                "active": modo_sabotaje_activo != "normal",
                "auto_mode_active": modo_auto_activo,
                "preemptive_freeze_active": preemptive_freeze_activo
            }
            if modo_sabotaje_activo == "ralentizar":
                status_data["sabotage"]["fps"] = fps_ralentizar_actual
        
        with bloqueo_contador_mama:
            status_data["mama_status"] = {
                "online": mama_login_count > 0,
                "login_count": mama_login_count
            }
        
        await manager.send_personal_message(
            json.dumps({"type": "initial_status", "data": status_data}),
            websocket
        )
    
    try:
        while True:
            # Mantener conexión activa y manejar mensajes entrantes
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                message_type = message.get("type", "")
                
                if message_type == "ping":
                    await manager.send_personal_message(
                        json.dumps({"type": "pong", "data": {}}),
                        websocket
                    )
                elif message_type == "request_status" and rol == "admin":
                    # Reenviar estado actual
                    await websocket_endpoint(websocket)
                else:
                    print(f"{tag_ws} {Fore.YELLOW}Mensaje no manejado de '{usuario}': {message_type}")
                    
            except json.JSONDecodeError:
                print(f"{tag_ws} {Fore.RED}Mensaje JSON inválido de '{usuario}': {data}")
                
    except WebSocketDisconnect:
        print(f"{tag_ws} {Fore.YELLOW}Desconexión WebSocket: '{usuario}' ({rol})")
    except Exception as e:
        print(f"{tag_ws} {Fore.RED}Error WebSocket para '{usuario}': {e}")
    finally:
        await manager.disconnect(websocket)
        
        # Si era mamá, actualizar contador
        if usuario == mama_username:
            with bloqueo_contador_mama:
                if mama_login_count > 0:
                    mama_login_count -= 1
                logins = mama_login_count
            
            print(f"{tag_ws} {Fore.YELLOW}Mamá desconectada. Logins restantes: {logins}")
            
            # Notificar a admin
            await manager.broadcast_to_room(
                json.dumps({
                    "type": "mama_connection_status",
                    "data": {"status": "offline" if logins == 0 else "online", "logins": logins}
                }),
                ADMIN_ROOM
            )

# --- EVENTOS DE INICIO Y CIERRE ---

@app.on_event("startup")
async def startup_event():
    """Eventos de inicio de la aplicación."""
    tag_startup = f"{Fore.GREEN}[STARTUP]{Style.RESET_ALL}"
    print(f"{tag_startup} {Fore.CYAN}Iniciando sistema de vigilancia FastAPI...")
    
    # Crear directorios necesarios
    os.makedirs("data", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    
    # Inicializar colas de frames
    global colas_frames, hilos_camara
    colas_frames = [queue.Queue(maxsize=TAMANO_COLA_FRAMES) for _ in range(len(FUENTES_CAMARA_TODAS))]
    hilos_camara = [None] * len(FUENTES_CAMARA_TODAS)
    
    # Iniciar hilos de cámara
    for i, fuente in enumerate(FUENTES_CAMARA_TODAS):
        camara_activa[i] = True
        hilo = threading.Thread(target=hilo_camara, args=(i, fuente), daemon=True)
        hilo.start()
        hilos_camara[i] = hilo
        print(f"{tag_startup} {Fore.GREEN}Cámara {i} iniciada: {fuente}")
    
    print(f"{tag_startup} {Fore.GREEN}Sistema iniciado correctamente.")

@app.on_event("shutdown")
async def shutdown_event():
    """Eventos de cierre de la aplicación."""
    tag_shutdown = f"{Fore.RED}[SHUTDOWN]{Style.RESET_ALL}"
    print(f"{tag_shutdown} {Fore.YELLOW}Cerrando sistema de vigilancia...")
    
    # Detener modo auto
    global modo_auto_activo, evento_parada_auto, hilo_auto_mode
    if modo_auto_activo:
        modo_auto_activo = False
        evento_parada_auto.set()
        if hilo_auto_mode and hilo_auto_mode.is_alive():
            hilo_auto_mode.join(timeout=3)
        print(f"{tag_shutdown} {Fore.YELLOW}Modo Auto detenido.")
    
    # Detener todas las cámaras
    with bloqueo_estado:
        for i in range(len(camara_activa)):
            camara_activa[i] = False
    
    # Esperar a que terminen los hilos
    for i, hilo in enumerate(hilos_camara):
        if hilo and hilo.is_alive():
            hilo.join(timeout=2)
            print(f"{tag_shutdown} {Fore.YELLOW}Hilo cámara {i} terminado.")
    
    print(f"{tag_shutdown} {Fore.RED}Sistema cerrado correctamente.")

# --- FUNCIÓN PRINCIPAL ---

def main():
    """Función principal para ejecutar el servidor."""
    import signal
    import sys
    
    def signal_handler(sig, frame):
        print(f"\n{Fore.RED}[SIGNAL]{Style.RESET_ALL} {Fore.YELLOW}Recibida señal de interrupción. Cerrando...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"{Fore.GREEN}[MAIN]{Style.RESET_ALL} {Fore.CYAN}Iniciando servidor FastAPI...")
    print(f"{Fore.GREEN}[MAIN]{Style.RESET_ALL} {Fore.CYAN}Servidor disponible en: http://localhost:8000")
    print(f"{Fore.GREEN}[MAIN]{Style.RESET_ALL} {Fore.CYAN}Presiona Ctrl+C para detener.")
    
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[MAIN]{Style.RESET_ALL} {Fore.YELLOW}Servidor detenido por el usuario.")
    except Exception as e:
        print(f"\n{Fore.RED}[MAIN]{Style.RESET_ALL} {Fore.RED}Error al ejecutar servidor: {e}")
    finally:
        print(f"{Fore.GREEN}[MAIN]{Style.RESET_ALL} {Fore.GREEN}Limpieza completada.")

if __name__ == "__main__":
    main()

# --- CONFIGURACIÓN ADICIONAL ---

# Configurar logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('surveillance_system.log')
    ]
)

# Configurar CUDA si está disponible
if torch.cuda.is_available():
    print(f"{Fore.GREEN}[CUDA]{Style.RESET_ALL} {Fore.GREEN}CUDA disponible: {torch.cuda.get_device_name(0)}")
    print(f"{Fore.GREEN}[CUDA]{Style.RESET_ALL} {Fore.GREEN}Versión CUDA: {torch.version.cuda}")
else:
    print(f"{Fore.YELLOW}[CUDA]{Style.RESET_ALL} {Fore.YELLOW}CUDA no disponible, usando CPU.")

# Configurar memoria de GPU si está disponible
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    print(f"{Fore.GREEN}[CUDA]{Style.RESET_ALL} {Fore.GREEN}Cache de GPU limpiado.")
