"""
Camera management service for FastAPI surveillance system
"""
import cv2
import numpy as np
import threading
import queue
import time
import os
from typing import Dict, List, Optional, Callable
from ultralytics import YOLO
import torch
import asyncio
import inspect

from models.config import CameraConfig, settings
from models.schemas import CameraType, SabotageMode
from utils.video_processing import VideoProcessor, sabotage_engine


class CameraManager:
    """Manages camera connections and video processing"""
    
    def __init__(self):
        self.cameras = {}  # camera_id -> camera_info
        self.frame_queues = {}  # camera_id -> queue
        self.raw_queues = {}  # camera_id -> raw frames queue
        self.manipulated_queues = {}  # camera_id -> manipulated queue (for spy cameras)
        self.camera_threads = {}  # camera_id -> thread
        self.infer_threads = {}  # camera_id -> inference thread
        self.camera_active = {}  # camera_id -> bool
        self.person_detected = {}  # camera_id -> bool
        self.mama_camera_enabled = True  # New: control for mama's camera access

        self.recording_active = {}  # camera_id -> bool
        self.recording_queues = {}  # camera_id -> queue
        self.recording_threads = {}  # camera_id -> thread
        self.recording_lock = threading.Lock()
        
        # YOLO model
        self.yolo_model = None
        self.device = "cpu"
        
        # Locks
        self.state_lock = threading.Lock()
        self.sound_lock = threading.Lock()
        
        # Sound management
        self.last_sound_time = 0
        
        # Callbacks
        self.detection_callbacks: List[Callable] = []
        self.status_callbacks: List[Callable] = []
        # Main asyncio event loop reference (set on app startup)
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Initialize default cameras
        self._initialize_default_cameras()
        self._load_yolo_model()
    
    def _initialize_default_cameras(self):
        """Initialize default camera configuration"""
        # Add admin cameras
        for i, camera_url in enumerate(CameraConfig.ADMIN_CAMERAS):
            self.add_camera(
                camera_id=f"admin_{i}",
                name=f"Admin Camera {i+1}",
                ip_url=camera_url,
                camera_type=CameraType.ADMIN
            )
        
        # Add spy camera
        spy_index = CameraConfig.get_spy_camera_index()
        self.add_camera(
            camera_id="spy",
            name="Spy Camera",
            ip_url=CameraConfig.SPY_CAMERA,
            camera_type=CameraType.SPY
        )
    
    def _load_yolo_model(self):
        """Load YOLO model for person detection"""
        try:
            print(f"Loading YOLO model from {settings.yolo_model_path}...")
            print(f"Settings device: {settings.device}")
            print(f"CUDA available: {torch.cuda.is_available()}")
            
            self.yolo_model = YOLO(settings.yolo_model_path)
            
            # Use device from settings, but verify CUDA availability
            if settings.device == "cuda" and torch.cuda.is_available():
                self.device = "cuda"
                print(f"CUDA detected: {torch.cuda.get_device_name(0)}")
                print(f"CUDA version: {torch.version.cuda}")
                # Enable cuDNN autotuner for performance
                try:
                    torch.backends.cudnn.benchmark = True
                    print("cuDNN benchmark enabled")
                except Exception:
                    pass
            else:
                self.device = "cpu"
                if settings.device == "cuda":
                    print("CUDA requested but not available, falling back to CPU")
                else:
                    print(f"Using CPU as configured (settings.device = {settings.device})")
            
            self.yolo_model.to(self.device)
            # Try fusing layers for speed if supported
            try:
                if hasattr(self.yolo_model, "fuse"):
                    self.yolo_model.fuse()
                    print("Model fused for faster inference")
            except Exception:
                pass
            print(f"YOLO model loaded on {self.device.upper()}")
        except Exception as e:
            print(f"Error loading YOLO model: {e}")
            self.yolo_model = None
    
    def add_camera(self, camera_id: str, name: str, ip_url: str, camera_type: CameraType):
        """Add a new camera"""
        with self.state_lock:
            self.cameras[camera_id] = {
                "id": camera_id,
                "name": name,
                "ip_url": ip_url,
                "type": camera_type.value,  # Store as string value
                "enabled": True,
                "created_at": time.time()
            }
            
            # Initialize queues
            self.frame_queues[camera_id] = queue.Queue(maxsize=settings.max_queue_size)
            self.raw_queues[camera_id] = queue.Queue(maxsize=settings.max_queue_size)
            if camera_type == CameraType.SPY:
                self.manipulated_queues[camera_id] = queue.Queue(maxsize=settings.max_queue_size)
            
            # Initialize state
            self.camera_active[camera_id] = False
            self.person_detected[camera_id] = False

            self.recording_active[camera_id] = False
            self.recording_queues[camera_id] = queue.Queue(maxsize=getattr(settings, "recording_queue_size", 120))
    
    def remove_camera(self, camera_id: str) -> bool:
        """Remove a camera"""
        if camera_id not in self.cameras:
            return False

        # Stop camera thread if running
        self.stop_recording(camera_id)
        self.stop_camera(camera_id)
        
        with self.state_lock:
            # Clean up
            del self.cameras[camera_id]
            del self.frame_queues[camera_id]
            if camera_id in self.raw_queues:
                del self.raw_queues[camera_id]
            if camera_id in self.manipulated_queues:
                del self.manipulated_queues[camera_id]
            del self.camera_active[camera_id]
            del self.person_detected[camera_id]
            if camera_id in self.recording_active:
                del self.recording_active[camera_id]
            if camera_id in self.recording_queues:
                del self.recording_queues[camera_id]
            if camera_id in self.recording_threads:
                del self.recording_threads[camera_id]
        
        return True
    
    def start_camera(self, camera_id: str) -> bool:
        """Start a camera thread"""
        if camera_id not in self.cameras:
            return False
        
        if camera_id in self.camera_threads and self.camera_threads[camera_id].is_alive():
            # Ensure inference thread is also running
            if camera_id not in self.infer_threads or not self.infer_threads[camera_id].is_alive():
                infer_thread = threading.Thread(
                    target=self._inference_thread,
                    args=(camera_id,),
                    daemon=True
                )
                infer_thread.start()
                self.infer_threads[camera_id] = infer_thread
            return True  # Already running
        
        with self.state_lock:
            self.camera_active[camera_id] = True
        
        # Start camera thread
        thread = threading.Thread(
            target=self._camera_thread,
            args=(camera_id,),
            daemon=True
        )
        thread.start()
        self.camera_threads[camera_id] = thread
        
        # Start inference thread decoupled from capture
        infer_thread = threading.Thread(
            target=self._inference_thread,
            args=(camera_id,),
            daemon=True
        )
        infer_thread.start()
        self.infer_threads[camera_id] = infer_thread
        
        return True
    
    def stop_camera(self, camera_id: str) -> bool:
        """Stop a camera thread"""
        if camera_id not in self.cameras:
            return False

        self.stop_recording(camera_id)
        
        with self.state_lock:
            self.camera_active[camera_id] = False
        
        # Wait for thread to finish
        if camera_id in self.camera_threads:
            thread = self.camera_threads[camera_id]
            if thread.is_alive():
                thread.join(timeout=5)
            del self.camera_threads[camera_id]
        
        # Wait for inference thread to finish
        if camera_id in self.infer_threads:
            ithread = self.infer_threads[camera_id]
            if ithread.is_alive():
                ithread.join(timeout=5)
            del self.infer_threads[camera_id]
        
        return True

    def start_recording(self, camera_id: str) -> bool:
        if camera_id not in self.cameras:
            return False

        with self.recording_lock:
            if self.recording_threads.get(camera_id) is not None and self.recording_threads[camera_id].is_alive():
                self.recording_active[camera_id] = True
                return True
            self.recording_active[camera_id] = True
            if camera_id not in self.recording_queues:
                self.recording_queues[camera_id] = queue.Queue(maxsize=getattr(settings, "recording_queue_size", 120))

            thread = threading.Thread(
                target=self._recording_thread,
                args=(camera_id,),
                daemon=True
            )
            thread.start()
            self.recording_threads[camera_id] = thread
            return True

    def stop_recording(self, camera_id: str) -> bool:
        if camera_id not in self.cameras:
            return False

        with self.recording_lock:
            self.recording_active[camera_id] = False
            q = self.recording_queues.get(camera_id)
            if q is not None:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

        thread = self.recording_threads.get(camera_id)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

        return True
    
    def start_all_cameras(self):
        """Start all cameras"""
        for camera_id in self.cameras:
            self.start_camera(camera_id)
    
    def stop_all_cameras(self):
        """Stop all cameras"""
        for camera_id in list(self.cameras.keys()):
            self.stop_camera(camera_id)
    
    def get_camera_list(self) -> List[Dict]:
        """Get list of all cameras"""
        with self.state_lock:
            return [
                {
                    **camera_info,
                    "is_active": self.camera_active.get(camera_id, False),
                    "person_detected": self.person_detected.get(camera_id, False),
                    "status": "running" if self.camera_active.get(camera_id, False) else "stopped",
                    "source": "ip"  # Add source field for frontend display
                }
                for camera_id, camera_info in self.cameras.items()
            ]
    
    def get_frame_queue(self, camera_id: str, is_admin: bool = True) -> Optional[queue.Queue]:
        """Get frame queue for a camera"""
        if camera_id not in self.cameras:
            return None
        
        camera_info = self.cameras[camera_id]
        
        # Check if mama's camera access is enabled
        if not is_admin and camera_info["type"] == CameraType.SPY and not self.mama_camera_enabled:
            return None
        
        # Return appropriate queue
        if is_admin or camera_info["type"] != CameraType.SPY:
            return self.frame_queues.get(camera_id)
        else:
            # For mama accessing spy camera, return manipulated queue
            return self.manipulated_queues.get(camera_id)
    
    def set_mama_camera_enabled(self, enabled: bool):
        """Enable or disable mama's camera access"""
        with self.state_lock:
            self.mama_camera_enabled = enabled
        
        # Notify status callbacks
        for callback in self.status_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    if self.event_loop and self.event_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            callback("mama_camera_toggle", {"enabled": enabled}),
                            self.event_loop
                        )
                    else:
                        print("Async status callback skipped: no running event loop")
                else:
                    callback("mama_camera_toggle", {"enabled": enabled})
            except Exception as e:
                print(f"Error in status callback: {e}")
    
    def is_mama_camera_enabled(self) -> bool:
        """Check if mama's camera is enabled"""
        return self.mama_camera_enabled
    
    def add_detection_callback(self, callback: Callable):
        """Add a callback for person detection events"""
        self.detection_callbacks.append(callback)
    
    def add_status_callback(self, callback: Callable):
        """Add a callback for status updates"""
        self.status_callbacks.append(callback)

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the asyncio event loop to schedule async callbacks from threads"""
        self.event_loop = loop
    
    def _camera_thread(self, camera_id: str):
        """Main camera thread function"""
        camera_info = self.cameras[camera_id]
        is_spy_camera = camera_info["type"] == CameraType.SPY
        ip_url = camera_info["ip_url"]
        
        print(f"Starting camera thread for {camera_id} ({camera_info['name']})")
        
        capture = None
        consecutive_errors = 0
        max_errors = 15
        last_person_state = False
        
        while self.camera_active.get(camera_id, False):
            try:
                # Initialize capture
                if capture is None or not capture.isOpened():
                    print(f"Connecting to camera {camera_id}...")
                    capture = cv2.VideoCapture(ip_url, cv2.CAP_FFMPEG)
                    capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, settings.connection_timeout)
                    capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, settings.read_timeout)
                    
                    if not capture.isOpened():
                        print(f"Failed to connect to camera {camera_id}")
                        capture = None
                        time.sleep(5)
                        consecutive_errors += 1
                        if consecutive_errors >= max_errors:
                            print(f"Max retries reached for camera {camera_id}")
                            break
                        continue
                    else:
                        print(f"Connected to camera {camera_id}")
                        try:
                            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        except Exception:
                            pass
                        consecutive_errors = 0
                
                # Read frame
                ret, frame = capture.read()
                if not ret or frame is None:
                    print(f"Failed to read frame from camera {camera_id}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        break
                    time.sleep(0.1)
                    continue

                if self.recording_active.get(camera_id, False):
                    q = self.recording_queues.get(camera_id)
                    if q is not None:
                        try:
                            q.put_nowait(frame)
                        except queue.Full:
                            try:
                                q.get_nowait()
                                q.put_nowait(frame)
                            except queue.Empty:
                                pass
                
                consecutive_errors = 0
                
                # Resize frame
                frame = VideoProcessor.resize_frame(frame)
                
                # Encolar frame crudo para inferencia con descarte de antiguos
                try:
                    self.raw_queues[camera_id].put_nowait(frame)
                except queue.Full:
                    try:
                        self.raw_queues[camera_id].get_nowait()
                        self.raw_queues[camera_id].put_nowait(frame)
                    except queue.Empty:
                        pass
                
                # Small delay to prevent excessive CPU usage
                time.sleep(0.03)  # ~30 FPS
                
            except Exception as e:
                print(f"Error in camera thread {camera_id}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_errors:
                    break
                time.sleep(1)
        
        # Cleanup
        if capture is not None:
            capture.release()
        
        with self.state_lock:
            self.camera_active[camera_id] = False
        
        print(f"Camera thread {camera_id} stopped")

    def _recording_thread(self, camera_id: str):
        output_dir = getattr(settings, "recordings_path", "recordings")
        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"{camera_id}_{timestamp}.webm")

        writer = None
        fps = float(getattr(settings, "recording_fps", 20))

        q = self.recording_queues.get(camera_id)
        if q is None:
            return

        try:
            while self.camera_active.get(camera_id, False) and self.recording_active.get(camera_id, False):
                try:
                    frame = q.get(timeout=0.5)
                except queue.Empty:
                    continue

                if frame is None:
                    break

                if writer is None:
                    height, width = frame.shape[:2]
                    for fourcc_code in ("VP90", "VP80"):
                        fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
                        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                        if writer is not None and writer.isOpened():
                            break
                        if writer is not None:
                            writer.release()
                        writer = None

                    if writer is None:
                        print(f"Failed to start recording for {camera_id} (VideoWriter not opened)")
                        with self.recording_lock:
                            self.recording_active[camera_id] = False
                        break

                try:
                    writer.write(frame)
                except Exception as e:
                    print(f"Error writing frame for {camera_id}: {e}")
                    break
        finally:
            if writer is not None:
                try:
                    writer.release()
                except Exception:
                    pass

    def _inference_thread(self, camera_id: str):
        """Inference thread: consume frames crudos, corre YOLO y publica"""
        camera_info = self.cameras[camera_id]
        is_spy_camera = camera_info["type"] == CameraType.SPY
        last_person_state = False
        
        print(f"Starting inference thread for {camera_id}")
        while self.camera_active.get(camera_id, False):
            try:
                # Obtener frame más reciente del buffer crudo
                try:
                    frame = self.raw_queues[camera_id].get(timeout=0.5)
                except queue.Empty:
                    continue
                
                processed_frame = frame
                person_detected_in_frame = False
                
                # Solo correr detección en cámaras admin
                if not is_spy_camera and self.yolo_model is not None:
                    try:
                        results = self.yolo_model.predict(
                            source=frame,
                            verbose=False,
                            conf=settings.detection_threshold,
                            iou=0.45,
                            classes=[0],
                            device=self.device,
                            half=(self.device == "cuda")
                        )
                        processed_frame, person_detected_in_frame = VideoProcessor.draw_detection_boxes(frame.copy(), results)
                        
                        with self.state_lock:
                            self.person_detected[camera_id] = person_detected_in_frame
                        
                        if person_detected_in_frame and not last_person_state:
                            self._handle_person_detection(camera_id, processed_frame)
                        last_person_state = person_detected_in_frame
                    except Exception as e:
                        print(f"Error in YOLO detection for camera {camera_id}: {e}")
                        processed_frame = frame
                
                # Publicar a la cola de frames lista para stream
                try:
                    self.frame_queues[camera_id].put_nowait(processed_frame)
                except queue.Full:
                    try:
                        self.frame_queues[camera_id].get_nowait()
                        self.frame_queues[camera_id].put_nowait(processed_frame)
                    except queue.Empty:
                        pass
                
                # Publicar versión manipulada para cámara espía
                if is_spy_camera and camera_id in self.manipulated_queues:
                    manipulated_frame = sabotage_engine.process_frame(processed_frame, is_spy_camera=True)
                    manipulated_frame = VideoProcessor.resize_frame(
                        manipulated_frame,
                        width=getattr(settings, "mama_stream_width", 640),
                        height=getattr(settings, "mama_stream_height", 360),
                    )
                    try:
                        self.manipulated_queues[camera_id].put_nowait(manipulated_frame)
                    except queue.Full:
                        try:
                            self.manipulated_queues[camera_id].get_nowait()
                            self.manipulated_queues[camera_id].put_nowait(manipulated_frame)
                        except queue.Empty:
                            pass
            except Exception as e:
                print(f"Error in inference thread {camera_id}: {e}")
                time.sleep(0.05)
        print(f"Inference thread {camera_id} stopped")
    
    def _handle_person_detection(self, camera_id: str, frame: np.ndarray):
        """Handle person detection event"""
        current_time = time.time()
        
        # Sound cooldown
        with self.sound_lock:
            if current_time - self.last_sound_time >= settings.sound_cooldown:
                self.last_sound_time = current_time
                play_sound = True
            else:
                play_sound = False
        
        # Trigger detection callbacks
        for callback in self.detection_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    # Schedule async callback on the main FastAPI event loop
                    if self.event_loop and self.event_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            callback(camera_id, frame, play_sound),
                            self.event_loop
                        )
                    else:
                        print("Async detection callback skipped: no running event loop")
                else:
                    # Handle sync callbacks
                    callback(camera_id, frame, play_sound)
            except Exception as e:
                print(f"Error in detection callback: {e}")

        self._notify_tv(camera_id)

    def _notify_tv(self, camera_id: str) -> None:
        """Encola un aviso a la tele. No espera a ADB ni tumba la detección."""
        try:
            with self.state_lock:
                info = self.cameras.get(camera_id) or {}
                name = info.get("name")
                ids = list(self.cameras.keys())
            number = ids.index(camera_id) + 1 if camera_id in ids else 1
            from services.tv_notifier import tv_notifier
            tv_notifier.notify_detection(camera_id, name=name, number=number)
        except Exception as e:
            print(f"Error notifying TV for {camera_id}: {e}")


# Global camera manager instance
camera_manager = CameraManager()
