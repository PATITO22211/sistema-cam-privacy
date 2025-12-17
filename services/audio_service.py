"""
Audio service for surveillance system notifications
"""
import threading
import time
import os
from typing import Optional
import pygame

from models.config import settings


class AudioManager:
    """Manages audio notifications and sound effects"""
    
    def __init__(self):
        self.initialized = False
        self.sound_lock = threading.Lock()
        self.last_sound_time = 0
        self.sounds = {}
        
        # Initialize pygame mixer
        self._initialize_audio()
        self._load_sounds()
    
    def _initialize_audio(self):
        """Initialize pygame audio system"""
        try:
            pygame.mixer.pre_init(
                frequency=settings.audio_frequency,
                size=settings.audio_size,
                channels=settings.audio_channels,
                buffer=settings.audio_buffer
            )
            pygame.mixer.init()
            self.initialized = True
            print("Audio system initialized successfully")
        except Exception as e:
            print(f"Failed to initialize audio system: {e}")
            self.initialized = False
    
    def _load_sounds(self):
        """Load sound files"""
        if not self.initialized:
            return
        
        sound_files = {
            "detection": "detection_alert.wav",
            "notification": "notification.wav",
            "warning": "warning.wav",
            "error": "error.wav"
        }
        
        for sound_name, filename in sound_files.items():
            sound_path = os.path.join(settings.audio_path, filename)
            try:
                if os.path.exists(sound_path):
                    self.sounds[sound_name] = pygame.mixer.Sound(sound_path)
                    print(f"Loaded sound: {sound_name}")
                else:
                    print(f"Sound file not found: {sound_path}")
            except Exception as e:
                print(f"Error loading sound {sound_name}: {e}")
    
    def play_sound(self, sound_name: str, force: bool = False) -> bool:
        """Play a sound with cooldown protection"""
        if not self.initialized or sound_name not in self.sounds:
            return False
        
        current_time = time.time()
        
        with self.sound_lock:
            # Check cooldown unless forced
            if not force and current_time - self.last_sound_time < settings.sound_cooldown:
                return False
            
            try:
                self.sounds[sound_name].play()
                self.last_sound_time = current_time
                return True
            except Exception as e:
                print(f"Error playing sound {sound_name}: {e}")
                return False
    
    def play_detection_alert(self, force: bool = False) -> bool:
        """Play person detection alert sound"""
        return self.play_sound("detection", force)
    
    def play_notification(self, force: bool = False) -> bool:
        """Play general notification sound"""
        return self.play_sound("notification", force)
    
    def play_warning(self, force: bool = False) -> bool:
        """Play warning sound"""
        return self.play_sound("warning", force)
    
    def play_error(self, force: bool = False) -> bool:
        """Play error sound"""
        return self.play_sound("error", force)
    
    def stop_all_sounds(self):
        """Stop all currently playing sounds"""
        if self.initialized:
            pygame.mixer.stop()
    
    def set_volume(self, volume: float):
        """Set master volume (0.0 to 1.0)"""
        if self.initialized:
            volume = max(0.0, min(1.0, volume))
            for sound in self.sounds.values():
                sound.set_volume(volume)
    
    def is_available(self) -> bool:
        """Check if audio system is available"""
        return self.initialized
    
    def get_sound_info(self) -> dict:
        """Get information about loaded sounds"""
        return {
            "initialized": self.initialized,
            "loaded_sounds": list(self.sounds.keys()),
            "last_sound_time": self.last_sound_time,
            "cooldown": settings.sound_cooldown
        }


# Global audio manager instance
audio_manager = AudioManager()


def create_default_sounds():
    """Create default sound files if they don't exist"""
    import numpy as np
    import wave
    
    # Ensure audio directory exists
    os.makedirs(settings.audio_path, exist_ok=True)
    
    def generate_tone(frequency: float, duration: float, sample_rate: int = 44100) -> np.ndarray:
        """Generate a simple tone"""
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        # Generate sine wave with fade in/out to avoid clicks
        wave = np.sin(2 * np.pi * frequency * t)
        fade_samples = int(0.01 * sample_rate)  # 10ms fade
        wave[:fade_samples] *= np.linspace(0, 1, fade_samples)
        wave[-fade_samples:] *= np.linspace(1, 0, fade_samples)
        return (wave * 32767).astype(np.int16)
    
    def save_wave(filename: str, audio_data: np.ndarray, sample_rate: int = 44100):
        """Save audio data as WAV file"""
        filepath = os.path.join(settings.audio_path, filename)
        with wave.open(filepath, 'w') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())
        print(f"Created sound file: {filepath}")
    
    # Create detection alert (urgent beeping)
    detection_sound = np.concatenate([
        generate_tone(800, 0.2),
        np.zeros(int(0.1 * 44100), dtype=np.int16),
        generate_tone(800, 0.2),
        np.zeros(int(0.1 * 44100), dtype=np.int16),
        generate_tone(800, 0.2)
    ])
    save_wave("detection_alert.wav", detection_sound)
    
    # Create notification (gentle chime)
    notification_sound = generate_tone(523.25, 0.3)  # C5 note
    save_wave("notification.wav", notification_sound)
    
    # Create warning (low tone)
    warning_sound = generate_tone(220, 0.5)  # A3 note
    save_wave("warning.wav", warning_sound)
    
    # Create error (harsh buzz)
    error_sound = np.concatenate([
        generate_tone(150, 0.1),
        generate_tone(100, 0.1),
        generate_tone(150, 0.1)
    ])
    save_wave("error.wav", error_sound)


# Create default sounds if audio directory doesn't exist
if not os.path.exists(settings.audio_path):
    try:
        create_default_sounds()
        # Reload sounds after creation
        audio_manager._load_sounds()
    except Exception as e:
        print(f"Error creating default sounds: {e}")