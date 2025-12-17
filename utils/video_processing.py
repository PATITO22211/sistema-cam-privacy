"""
Video processing utilities for FastAPI surveillance system
"""
import cv2
import numpy as np
from typing import Tuple, List, Optional, Any
import time
import threading
from models.config import settings
from models.schemas import SabotageMode


class VideoProcessor:
    """Video processing utilities"""
    
    @staticmethod
    def sabotage_pixelation(frame: np.ndarray, quality: int = None) -> np.ndarray:
        """Apply pixelation sabotage to frame"""
        if frame is None or not isinstance(frame, np.ndarray):
            return frame
        
        quality = quality or settings.pixelation_quality
        
        try:
            result, encoded_image = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            )
            if result:
                frame_pixelated = cv2.imdecode(encoded_image, 1)
                return frame_pixelated
            else:
                return frame
        except Exception as e:
            print(f"Error in pixelation sabotage: {e}")
            return frame
    
    @staticmethod
    def sabotage_grayscale(frame: np.ndarray) -> np.ndarray:
        """Convert frame to grayscale (maintaining 3 channels)"""
        if frame is None or not isinstance(frame, np.ndarray):
            return frame
        
        try:
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_gray_bgr = cv2.cvtColor(frame_gray, cv2.COLOR_GRAY2BGR)
            return frame_gray_bgr
        except Exception as e:
            print(f"Error in grayscale sabotage: {e}")
            return frame
    
    @staticmethod
    def draw_detection_boxes(image: np.ndarray, results: List[Any]) -> Tuple[np.ndarray, bool]:
        """Draw YOLO detection boxes on image"""
        person_detected = False
        
        if image is None or not isinstance(image, np.ndarray):
            return image, person_detected
        
        if not results:
            return image, person_detected
        
        for result in results:
            if not hasattr(result, "boxes") or result.boxes is None:
                continue
            
            boxes = result.boxes
            names = getattr(result, "names", {})
            
            for box in boxes:
                try:
                    b = box.xyxy[0].cpu().numpy()
                    class_idx = int(box.cls[0].cpu().item())
                    conf = box.conf[0].cpu().item()
                    class_name = names.get(class_idx, f"Class {class_idx}")
                    
                    if class_name == "person" and conf >= settings.detection_threshold:
                        person_detected = True
                        color = (0, 0, 255)  # Red color for person detection
                        label = f"{class_name} {conf:.2f}"
                        
                        # Draw rectangle
                        cv2.rectangle(
                            image, 
                            (int(b[0]), int(b[1])), 
                            (int(b[2]), int(b[3])), 
                            color, 
                            2
                        )
                        
                        # Draw label background
                        (tw, th), _ = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                        )
                        tx, ty = int(b[0]), int(b[1]) - 10
                        if ty < th:
                            ty = int(b[1]) + th + 5
                        
                        cv2.rectangle(
                            image, 
                            (tx, ty - th - 2), 
                            (tx + tw + 2, ty), 
                            color, 
                            -1
                        )
                        
                        # Draw label text
                        cv2.putText(
                            image,
                            label,
                            (tx + 1, ty - 2),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 255, 255),
                            1,
                        )
                        
                except Exception as e:
                    print(f"Error drawing detection box: {e}")
        
        return image, person_detected
    
    @staticmethod
    def resize_frame(frame: np.ndarray, width: int = None, height: int = None) -> np.ndarray:
        """Resize frame to specified dimensions"""
        if frame is None or not isinstance(frame, np.ndarray):
            return frame
        
        width = width or settings.frame_width
        height = height or settings.frame_height
        
        try:
            resized_frame = cv2.resize(frame, (width, height))
            return resized_frame
        except Exception as e:
            print(f"Error resizing frame: {e}")
            return frame
    
    @staticmethod
    def encode_frame_to_jpeg(frame: np.ndarray, quality: int = 85) -> Optional[bytes]:
        """Encode frame to JPEG bytes"""
        if frame is None or not isinstance(frame, np.ndarray):
            return None
        
        try:
            ret, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if ret:
                return buffer.tobytes()
            return None
        except Exception as e:
            print(f"Error encoding frame to JPEG: {e}")
            return None


class SabotageEngine:
    """Engine for applying sabotage effects to video frames"""
    
    def __init__(self):
        self.current_mode = SabotageMode.NORMAL
        self.enabled = False
        self.frozen_frame = None
        self.auto_mode_active = False
        self.preemptive_freeze_active = False
        self.fps_reduction_interval = 0.0
        self.last_frame_time = 0.0
        self.last_output_frame = None
        self._lock = threading.Lock()
    
    @property
    def available_modes(self):
        """Get list of available sabotage modes"""
        return list(SabotageMode)
    
    def set_enabled(self, enabled: bool):
        """Enable or disable the sabotage engine"""
        with self._lock:
            self.enabled = enabled
            if not enabled:
                # Reset to normal mode when disabled
                self.current_mode = SabotageMode.NORMAL
                self.frozen_frame = None
                self.last_output_frame = None
                self.fps_reduction_interval = 0.0
                self.last_frame_time = 0.0
    
    def set_mode(self, mode: SabotageMode, **kwargs):
        """Set sabotage mode with optional parameters"""
        with self._lock:
            self.current_mode = mode
            
            if mode == SabotageMode.FREEZE:
                # Keep current frozen frame or set new one
                pass
            elif mode == SabotageMode.STATIC:
                # Prepare to capture a fresh frozen frame on next process
                self.frozen_frame = None
                self.last_frame_time = 0.0
                self.last_output_frame = None
            elif mode == SabotageMode.SLOW:
                fps = kwargs.get("fps", 2)
                self.fps_reduction_interval = 1.0 / fps if fps > 0 else 0.0
                # Reset timing/output tracking when switching to SLOW
                self.last_frame_time = 0.0
                self.last_output_frame = None
            elif mode == SabotageMode.PIXEL:
                self.last_frame_time = 0.0
                self.last_output_frame = None
            elif mode == SabotageMode.NORMAL:
                self.frozen_frame = None
                self.fps_reduction_interval = 0.0
                self.last_output_frame = None
                self.last_frame_time = 0.0
    
    def process_frame(self, frame: np.ndarray, is_spy_camera: bool = False) -> np.ndarray:
        """Process frame according to current sabotage mode"""
        if not is_spy_camera or frame is None or not self.enabled:
            return frame
        
        with self._lock:
            current_time = time.time()

            interval = 0.0
            if self.current_mode == SabotageMode.SLOW:
                interval = self.fps_reduction_interval
            elif self.current_mode == SabotageMode.PIXEL:
                fps = int(getattr(settings, "pixel_stream_fps", 3))
                interval = 1.0 / fps if fps > 0 else 0.0

            if interval > 0 and current_time - self.last_frame_time < interval:
                # Return last output frame to effectively reduce FPS
                return self.last_output_frame if self.last_output_frame is not None else frame
            
            self.last_frame_time = current_time
            
            # Apply sabotage effects
            if self.current_mode == SabotageMode.PIXEL:
                self.last_output_frame = VideoProcessor.sabotage_pixelation(frame)
                return self.last_output_frame
            elif self.current_mode == SabotageMode.GRAY:
                return VideoProcessor.sabotage_grayscale(frame)
            elif self.current_mode in (SabotageMode.FREEZE, SabotageMode.STATIC):
                # For both FREEZE and STATIC, hold the last captured frame
                if self.frozen_frame is None:
                    self.frozen_frame = frame.copy()
                return self.frozen_frame
            elif self.current_mode == SabotageMode.SLOW:
                # For slow mode, we already handled timing above
                self.last_output_frame = frame
                return self.last_output_frame
            else:  # NORMAL or STATIC
                return frame
    
    def set_frozen_frame(self, frame: np.ndarray):
        """Set a specific frame to be frozen"""
        with self._lock:
            if frame is not None:
                self.frozen_frame = frame.copy()
    
    def clear_frozen_frame(self):
        """Clear the frozen frame"""
        with self._lock:
            self.frozen_frame = None
    
    def get_status(self) -> dict:
        """Get current sabotage status"""
        with self._lock:
            return {
                "enabled": self.enabled,
                "mode": self.current_mode,
                "has_frozen_frame": self.frozen_frame is not None,
                "fps_interval": self.fps_reduction_interval,
                "auto_active": self.auto_mode_active,
                "preemptive_active": self.preemptive_freeze_active
            }


# Global sabotage engine instance
sabotage_engine = SabotageEngine()
