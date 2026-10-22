"""
Configuration models and settings for FastAPI surveillance system
"""
import os
from typing import List, Dict
from pydantic import BaseModel, Field

# Try to import torch for CUDA detection
try:
    import torch
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    CUDA_AVAILABLE = False


class Settings(BaseModel):
    # Application settings
    app_name: str = "Sistema de Vigilancia FastAPI"
    debug: bool = False
    secret_key: str = Field(default="clave-secreta-muy-MUY-insegura-cambiar!", env="SECRET_KEY")
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True
    
    # YOLO settings
    yolo_model_path: str = "yolov8n.pt"
    detection_threshold: float = 0.45
    device: str = "cuda" if CUDA_AVAILABLE else "cpu"
    
    # Camera settings
    frame_width: int = 640
    frame_height: int = 480
    max_queue_size: int = 3
    connection_timeout: int = 5000
    read_timeout: int = 5000

    stream_jpeg_quality: int = 5
    websocket_jpeg_quality: int = 5

    mama_stream_width: int = 128
    mama_stream_height: int = 64

    recordings_path: str = "recordings"
    recording_fps: int = 20
    recording_queue_size: int = 120
    
    # Audio settings
    audio_path: str = "audio"
    audio_frequency: int = 22050
    audio_size: int = -16  # 16-bit audio
    audio_channels: int = 2  # Stereo
    audio_buffer: int = 512
    audio_buffer_size: int = 512  # Backward compatibility
    sound_cooldown: float = 3.0
    alert_sound_path: str = "data/alert.mp3"
    
    # Sabotage settings
    pixelation_quality: int = 1
    pixel_stream_fps: int = 3
    preemptive_freeze_duration: float = 5.0
    fps_slow_min: int = 1
    fps_slow_max: int = 5
    
    # Session settings
    session_timeout: int = 3600  # 1 hour
    max_login_attempts: int = 5
    
    # WebSocket settings
    websocket_ping_interval: int = 20
    websocket_ping_timeout: int = 10
    ws_heartbeat_interval: int = 30
    
    @classmethod
    def load_from_env(cls):
        """Load settings from environment variables and .env file"""
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        return cls(
            debug=os.getenv("DEBUG", "false").lower() == "true",
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            yolo_model_path=os.getenv("YOLO_MODEL_PATH", "yolov8n.pt"),
            max_queue_size=int(os.getenv("MAX_QUEUE_SIZE", "3")),
            connection_timeout=int(os.getenv("CONNECTION_TIMEOUT", "5000")),
            read_timeout=int(os.getenv("READ_TIMEOUT", "5000")),
            stream_jpeg_quality=int(os.getenv("STREAM_JPEG_QUALITY", "20")),
            websocket_jpeg_quality=int(os.getenv("WEBSOCKET_JPEG_QUALITY", "25")),
            mama_stream_width=int(os.getenv("MAMA_STREAM_WIDTH", "256")),
            mama_stream_height=int(os.getenv("MAMA_STREAM_HEIGHT", "144")),
            recordings_path=os.getenv("RECORDINGS_PATH", "recordings"),
            recording_fps=int(os.getenv("RECORDING_FPS", "20")),
            recording_queue_size=int(os.getenv("RECORDING_QUEUE_SIZE", "120")),
            audio_path=os.getenv("AUDIO_PATH", "audio"),
            audio_frequency=int(os.getenv("AUDIO_FREQUENCY", "22050")),
            audio_buffer_size=int(os.getenv("AUDIO_BUFFER_SIZE", "512")),
            sound_cooldown=float(os.getenv("SOUND_COOLDOWN", "3.0")),
            session_timeout=int(os.getenv("SESSION_TIMEOUT", "3600")),
            secret_key=os.getenv("SECRET_KEY", "your-secret-key-here"),
            pixel_stream_fps=int(os.getenv("PIXEL_STREAM_FPS", "3")),
            ws_heartbeat_interval=int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
        )


class CameraConfig:
    """Camera configuration class"""
    
    # Reemplaza estas URLS por las URLs de TUS cámaras (celulares con ip camera)
    ADMIN_CAMERAS = [
        "http://192.168.100.25:8080/video",
        "http://192.168.100.25:8080/video",
    ]
    
    SPY_CAMERA = "http://192.168.100.17:8080/video"
    
    @classmethod
    def get_all_cameras(cls) -> List[str]:
        """Get all camera sources"""
        return cls.ADMIN_CAMERAS + [cls.SPY_CAMERA]
    
    @classmethod
    def get_spy_camera_index(cls) -> int:
        """Get the index of the spy camera"""
        return len(cls.ADMIN_CAMERAS)
    
    @classmethod
    def add_admin_camera(cls, camera_url: str) -> None:
        """Add a new admin camera"""
        if camera_url not in cls.ADMIN_CAMERAS:
            cls.ADMIN_CAMERAS.append(camera_url)
    
    @classmethod
    def remove_admin_camera(cls, camera_url: str) -> bool:
        """Remove an admin camera"""
        if camera_url in cls.ADMIN_CAMERAS:
            cls.ADMIN_CAMERAS.remove(camera_url)
            return True
        return False


class UserConfig:
    """User configuration class"""
    
    # Default user credentials (should be moved to database in production)
    CREDENTIALS = {
        "admin": "admin",
        "1234": "1234",  # mama's credentials
    }
    
    ROLES = {
        "admin": "admin",
        "1234": "mama"
    }
    
    MAMA_USERNAME = "1234"
    
    @classmethod
    def validate_credentials(cls, username: str, password: str) -> bool:
        """Validate user credentials"""
        return cls.CREDENTIALS.get(username) == password
    
    @classmethod
    def get_user_role(cls, username: str) -> str:
        """Get user role"""
        return cls.ROLES.get(username, "unknown")
    
    @classmethod
    def is_mama(cls, username: str) -> bool:
        """Check if user is mama"""
        return username == cls.MAMA_USERNAME


class TvOverlayConfig:
    """Valores de fábrica del aviso en la tele.

    El panel de admin puede cambiarlos sin reiniciar. Eso se guarda en
    data/tv_settings.json y, si existe, se usa en lugar de estos defaults.
    """

    enabled = False
    tv_ip = ""  # ejemplo: "192.168.1.80"
    adb_port = 5555
    adb_path = "adb"  # o r"C:\platform-tools\adb.exe" si no está en el PATH
    title = "Alerta"  # título opcional. Déjalo vacío si no quieres título.
    duration = 8  # segundos que el aviso se queda en pantalla
    cooldown_seconds = 30  # por cámara, para no spamear cada frame
    rest_fallback = True  # si ADB falla, POST directo al API de TvOverlay
    tvoverlay_port = 5001  # API local de TvOverlay, POST /notify
    adb_local_port = 15001  # puerto en esta PC para el túnel `adb forward`


# Global settings instance
settings = Settings.load_from_env()
