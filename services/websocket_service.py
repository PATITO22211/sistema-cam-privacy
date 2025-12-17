"""
WebSocket service for real-time communication in FastAPI surveillance system
"""
import json
import asyncio
import time
import base64
from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
import cv2
import numpy as np

from models.schemas import WebSocketMessage, PersonDetectionAlert, CameraStatusUpdate, UserSessionUpdate
from models.config import settings
from utils.video_processing import VideoProcessor, sabotage_engine
from services.camera_service import camera_manager
from services.audio_service import audio_manager


class ConnectionManager:
    """Manages WebSocket connections and real-time communication"""
    
    def __init__(self):
        # Active connections by user type
        self.admin_connections: Set[WebSocket] = set()
        self.mama_connections: Set[WebSocket] = set()
        
        # Connection metadata
        self.connection_info: Dict[WebSocket, Dict] = {}
        
        # Room subscriptions (for camera feeds)
        self.camera_subscriptions: Dict[str, Set[WebSocket]] = {}
        
        # Message queue for offline users
        self.message_queue: Dict[str, List[Dict]] = {"admin": [], "mama": []}
        
        # Statistics
        self.stats = {
            "total_connections": 0,
            "active_admin": 0,
            "active_mama": 0,
            "messages_sent": 0,
            "last_activity": time.time()
        }

        # Presence control: differentiate quick reloads vs. real disconnects
        self._mama_disconnect_task: Optional[asyncio.Task] = None
        self._intentional_logout_flag: bool = False
        self._disconnect_grace_seconds: float = 5.0
    
    async def connect(self, websocket: WebSocket, user_role: str, user_id: str):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        
        # Store connection info
        self.connection_info[websocket] = {
            "user_role": user_role,
            "user_id": user_id,
            "connected_at": time.time(),
            "last_ping": time.time()
        }
        
        # Add to appropriate connection set
        if user_role == "admin":
            self.admin_connections.add(websocket)
            self.stats["active_admin"] += 1
        else:
            self.mama_connections.add(websocket)
            self.stats["active_mama"] += 1
        
        self.stats["total_connections"] += 1
        self.stats["last_activity"] = time.time()
        
        print(f"WebSocket connected: {user_role} user {user_id}")
        
        # Send queued messages
        await self._send_queued_messages(websocket, user_role)
        
        # If mama just connected, cancel any pending delayed-offline and push status
        if user_role == "mama":
            if self._mama_disconnect_task and not self._mama_disconnect_task.done():
                try:
                    self._mama_disconnect_task.cancel()
                except Exception:
                    pass
                finally:
                    self._mama_disconnect_task = None
            # Update status to reflect connected state after reload/reconnect
            try:
                await self.send_mama_status_update(camera_manager.is_mama_camera_enabled())
            except Exception as e:
                print(f"Error broadcasting mama status on connect: {e}")
            # Play connection notification sound whenever mama connects (force bypasses cooldown)
            try:
                audio_manager.play_notification(force=True)
            except Exception as e:
                print(f"Error playing mama connection sound: {e}")

        # Notify other users about new connection
        await self._broadcast_user_session_update()
    
    async def disconnect(self, websocket: WebSocket):
        """Handle WebSocket disconnection"""
        if websocket not in self.connection_info:
            return
        
        user_info = self.connection_info[websocket]
        user_role = user_info["user_role"]
        user_id = user_info["user_id"]
        
        # Remove from connection sets
        if user_role == "admin":
            self.admin_connections.discard(websocket)
            self.stats["active_admin"] -= 1
        else:
            self.mama_connections.discard(websocket)
            self.stats["active_mama"] -= 1
        
        # Remove from camera subscriptions
        for camera_id, subscribers in self.camera_subscriptions.items():
            subscribers.discard(websocket)
        
        # Clean up connection info
        del self.connection_info[websocket]
        
        print(f"WebSocket disconnected: {user_role} user {user_id}")
        
        # If mama disconnected, handle presence with grace period or intentional flag
        if user_role == "mama":
            # If logout was intentional, immediately reflect disconnected status
            if self._intentional_logout_flag:
                try:
                    # Clear any pending delayed-offline tasks
                    if self._mama_disconnect_task and not self._mama_disconnect_task.done():
                        try:
                            self._mama_disconnect_task.cancel()
                        except Exception:
                            pass
                        finally:
                            self._mama_disconnect_task = None
                    # Only send status update here; 'mama_logout' should be emitted by explicit logout action
                    await self.send_mama_status_update(camera_manager.is_mama_camera_enabled())
                except Exception as e:
                    print(f"Error sending mama status on intentional logout: {e}")
                finally:
                    # Reset the flag so subsequent events behave normally
                    self._intentional_logout_flag = False
            else:
                # Schedule a delayed offline broadcast to avoid flicker on quick reloads
                try:
                    if self._mama_disconnect_task and not self._mama_disconnect_task.done():
                        try:
                            self._mama_disconnect_task.cancel()
                        except Exception:
                            pass
                    self._mama_disconnect_task = asyncio.create_task(self._deferred_mama_offline_broadcast(user_id))
                except Exception as e:
                    print(f"Error scheduling deferred mama offline broadcast: {e}")
        
        # Notify other users about disconnection
        await self._broadcast_user_session_update()

    async def _deferred_mama_offline_broadcast(self, username: str):
        """After a grace period, broadcast mama offline if not reconnected."""
        try:
            await asyncio.sleep(self._disconnect_grace_seconds)
            # If mama has reconnected during the grace period, skip offline broadcast
            if len(self.mama_connections) > 0:
                return
            # Broadcast logout event and final status
            await self.broadcast_to_admins({
                "type": "mama_logout",
                "username": username,
                "timestamp": time.time()
            })
            await self.send_mama_status_update(camera_manager.is_mama_camera_enabled())
        except asyncio.CancelledError:
            # Task cancelled due to reconnection
            return
        except Exception as e:
            print(f"Error in deferred mama offline broadcast: {e}")
        finally:
            self._mama_disconnect_task = None

    async def mark_mama_intentional_logout(self, username: str):
        """Mark mama's logout as intentional and notify admins immediately."""
        # Set flag so disconnect handler knows this was intentional
        self._intentional_logout_flag = True
        # Cancel any pending deferred offline task
        if self._mama_disconnect_task and not self._mama_disconnect_task.done():
            try:
                self._mama_disconnect_task.cancel()
            except Exception:
                pass
            finally:
                self._mama_disconnect_task = None
        # Immediately notify admins about logout intent
        try:
            await self.broadcast_to_admins({
                "type": "mama_logout",
                "username": username,
                "timestamp": time.time()
            })
        except Exception as e:
            print(f"Error broadcasting intentional mama logout: {e}")
    
    async def send_personal_message(self, websocket: WebSocket, message: Dict):
        """Send a message to a specific WebSocket connection"""
        try:
            await websocket.send_text(json.dumps(message))
            self.stats["messages_sent"] += 1
            self.stats["last_activity"] = time.time()
        except Exception as e:
            print(f"Error sending personal message: {e}")
            await self.disconnect(websocket)
    
    async def broadcast_to_admins(self, message: Dict):
        """Broadcast a message to all admin connections"""
        if not self.admin_connections:
            # Queue message for offline admins
            self.message_queue["admin"].append({
                **message,
                "timestamp": time.time()
            })
            return
        
        disconnected = set()
        payload = json.dumps(message)
        websockets = list(self.admin_connections)
        send_tasks = [ws.send_text(payload) for ws in websockets]
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        for ws, res in zip(websockets, results):
            if isinstance(res, Exception):
                print(f"Error broadcasting to admin: {res}")
                disconnected.add(ws)
            else:
                self.stats["messages_sent"] += 1
        
        # Clean up disconnected websockets
        for websocket in disconnected:
            await self.disconnect(websocket)
        
        self.stats["last_activity"] = time.time()
    
    async def broadcast_to_mama(self, message: Dict):
        """Broadcast a message to all mama connections"""
        if not self.mama_connections:
            # Queue message for offline mama
            self.message_queue["mama"].append({
                **message,
                "timestamp": time.time()
            })
            return
        
        disconnected = set()
        for websocket in self.mama_connections:
            try:
                await websocket.send_text(json.dumps(message))
                self.stats["messages_sent"] += 1
            except Exception as e:
                print(f"Error broadcasting to mama: {e}")
                disconnected.add(websocket)
        
        # Clean up disconnected websockets
        for websocket in disconnected:
            await self.disconnect(websocket)
        
        self.stats["last_activity"] = time.time()

    async def force_close_mama(self, reason: str = "Expulsada por administrador", redirect_url: str = "/login"):
        """Forcefully log out mama: send error-like message, close her WebSockets.

        This sets the intentional logout flag to avoid grace period handling,
        sends a `force_logout` message to mama clients, and closes their connections.
        """
        try:
            # Ensure intentional flag to avoid deferred offline broadcast
            self._intentional_logout_flag = True

            # Notify mama clients first so they can show the message and redirect
            await self.broadcast_to_mama({
                "type": "force_logout",
                "message": reason,
                "redirect": redirect_url,
                "timestamp": time.time()
            })

            # Close all mama websockets
            for ws in list(self.mama_connections):
                try:
                    await ws.close(code=1000, reason=reason)
                except Exception as e:
                    print(f"Error closing mama websocket: {e}")
        except Exception as e:
            print(f"Error during forced mama logout: {e}")
    
    async def broadcast_to_all(self, message: Dict):
        """Broadcast a message to all connections"""
        await self.broadcast_to_admins(message)
        await self.broadcast_to_mama(message)
    
    async def subscribe_to_camera(self, websocket: WebSocket, camera_id: str):
        """Subscribe a WebSocket to camera feed updates"""
        if camera_id not in self.camera_subscriptions:
            self.camera_subscriptions[camera_id] = set()
        
        self.camera_subscriptions[camera_id].add(websocket)
        
        await self.send_personal_message(websocket, {
            "type": "camera_subscription",
            "camera_id": camera_id,
            "status": "subscribed"
        })
    
    async def unsubscribe_from_camera(self, websocket: WebSocket, camera_id: str):
        """Unsubscribe a WebSocket from camera feed updates"""
        if camera_id in self.camera_subscriptions:
            self.camera_subscriptions[camera_id].discard(websocket)
        
        await self.send_personal_message(websocket, {
            "type": "camera_subscription",
            "camera_id": camera_id,
            "status": "unsubscribed"
        })
    
    async def broadcast_camera_frame(self, camera_id: str, frame: np.ndarray):
        """Broadcast a camera frame to subscribed connections"""
        if camera_id not in self.camera_subscriptions:
            return
        
        subscribers = self.camera_subscriptions[camera_id].copy()
        if not subscribers:
            return
        
        # Encode frame to JPEG and then Base64 for JSON-safe transport
        try:
            encoded_frame = VideoProcessor.encode_frame_to_jpeg(frame, quality=settings.websocket_jpeg_quality)
            if encoded_frame is None:
                raise ValueError("JPEG encoding returned None")
            frame_data = base64.b64encode(encoded_frame).decode('ascii')
        except Exception as e:
            print(f"Error encoding frame for camera {camera_id}: {e}")
            return
        
        message = {
            "type": "camera_frame",
            "camera_id": camera_id,
            "frame_data": frame_data,
            "timestamp": time.time()
        }
        
        disconnected = set()
        for websocket in subscribers:
            try:
                await websocket.send_text(json.dumps(message))
                self.stats["messages_sent"] += 1
            except Exception as e:
                print(f"Error sending camera frame: {e}")
                disconnected.add(websocket)
        
        # Clean up disconnected websockets
        for websocket in disconnected:
            await self.disconnect(websocket)
    
    async def send_person_detection_alert(self, camera_id: str, frame: np.ndarray, play_sound: bool = True):
        """Send person detection alert to all users"""
        # Encode frame for alert as Base64
        try:
            encoded_frame = VideoProcessor.encode_frame_to_jpeg(frame)
            frame_data = (
                base64.b64encode(encoded_frame).decode('ascii')
                if encoded_frame is not None else None
            )
        except Exception as e:
            print(f"Error encoding detection frame: {e}")
            frame_data = None
        
        # Build message directly to avoid schema validation issues
        message = {
            "type": "person_detection",
            "camera_id": camera_id,
            "timestamp": time.time(),
            # Provide a nominal confidence since YOLO results aren't passed here
            "confidence": 1.0,
            "frame_data": frame_data,
            "play_sound": play_sound,
            "priority": "high",
        }
        
        await self.broadcast_to_all(message)
        print(f"Person detection alert sent for camera {camera_id}")
    
    async def send_camera_status_update(self, camera_id: str, is_active: bool, person_detected: bool = False):
        """Send camera status update"""
        update = CameraStatusUpdate(
            camera_id=camera_id,
            is_active=is_active,
            person_detected=person_detected
        )
        
        message = {
            "type": "camera_status",
            **update.dict()
        }
        
        await self.broadcast_to_all(message)
    
    async def send_sabotage_status_update(self, mode: str, enabled: bool, details: Optional[Dict] = None):
        """Send sabotage status update (includes both 'current_mode' and 'mode' for compatibility)"""
        # Derive auxiliary fields for frontend status
        fps = None
        try:
            interval = sabotage_engine.fps_reduction_interval or 0.0
            fps = int(1.0 / interval) if interval > 0 else None
        except Exception:
            fps = None
        auto_running = bool(getattr(sabotage_engine, "auto_mode_active", False))
        message = {
            "type": "sabotage_status",
            "current_mode": mode,
            "mode": mode,
            "enabled": enabled,
            "timestamp": time.time(),
            "details": details or {},
            "is_auto_running": auto_running,
            "fps": fps
        }
        await self.broadcast_to_all(message)
    
    async def send_high_priority_alert(self, alert_type: str, message_text: str, data: Optional[Dict] = None):
        """Send high priority alert"""
        message = {
            "type": "high_priority_alert",
            "alert_type": alert_type,
            "message": message_text,
            "timestamp": time.time(),
            "priority": "critical",
            "data": data or {}
        }
        
        await self.broadcast_to_all(message)

    async def send_mama_status_update(self, enabled: bool):
        """Broadcast mama access status to all clients"""
        message = {
            "type": "mama_status",
            "enabled": enabled,
            "connected": len(self.mama_connections) > 0,
            "timestamp": time.time()
        }
        await self.broadcast_to_all(message)

    async def notify_mama_login(self, username: str, session_id: str):
        """Broadcast mama login event to all admin dashboards"""
        message = {
            "type": "mama_login",
            "username": username,
            "session_id": session_id,
            "timestamp": time.time()
        }
        await self.broadcast_to_admins(message)
    
    async def handle_message(self, websocket: WebSocket, message: Dict):
        """Handle incoming WebSocket message"""
        try:
            message_type = message.get("type")
            
            if message_type == "ping":
                # Update last ping time
                if websocket in self.connection_info:
                    self.connection_info[websocket]["last_ping"] = time.time()
                
                await self.send_personal_message(websocket, {
                    "type": "pong",
                    "timestamp": time.time()
                })
            
            elif message_type == "join_camera":
                camera_id = message.get("camera_id")
                if camera_id:
                    await self.subscribe_to_camera(websocket, camera_id)
            
            elif message_type == "leave_camera":
                camera_id = message.get("camera_id")
                if camera_id:
                    await self.unsubscribe_from_camera(websocket, camera_id)
            
            elif message_type == "request_status":
                # Send current system status
                await self.send_personal_message(websocket, {
                    "type": "system_status",
                    "stats": self.get_stats(),
                    "timestamp": time.time()
                })
            
            else:
                print(f"Unknown message type: {message_type}")
        
        except Exception as e:
            print(f"Error handling WebSocket message: {e}")
    
    async def _send_queued_messages(self, websocket: WebSocket, user_role: str):
        """Send queued messages to newly connected user"""
        if user_role not in self.message_queue:
            return
        
        messages = self.message_queue[user_role].copy()
        self.message_queue[user_role].clear()
        
        for message in messages:
            await self.send_personal_message(websocket, message)
    
    async def _broadcast_user_session_update(self):
        """Broadcast user session update to all connections"""
        # Simplified without Pydantic validation for local system
        message = {
            "type": "user_session_update",
            "admin_count": len(self.admin_connections),
            "mama_count": len(self.mama_connections),
            "total_connections": len(self.admin_connections) + len(self.mama_connections),
            "timestamp": time.time()
        }
        
        await self.broadcast_to_all(message)
    
    def get_stats(self) -> Dict:
        """Get connection statistics"""
        return {
            **self.stats,
            "active_connections": len(self.admin_connections) + len(self.mama_connections),
            "camera_subscriptions": {
                camera_id: len(subscribers)
                for camera_id, subscribers in self.camera_subscriptions.items()
            }
        }
    
    def get_connected_users(self) -> List[Dict]:
        """Get list of connected users"""
        users = []
        for websocket, info in self.connection_info.items():
            users.append({
                "user_id": info["user_id"],
                "user_role": info["user_role"],
                "connected_at": info["connected_at"],
                "last_ping": info["last_ping"]
            })
        return users


# Global connection manager instance
connection_manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket, user_role: str, user_id: str):
    """Main WebSocket endpoint handler"""
    await connection_manager.connect(websocket, user_role, user_id)
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                await connection_manager.handle_message(websocket, message)
            except json.JSONDecodeError:
                await connection_manager.send_personal_message(websocket, {
                    "type": "error",
                    "message": "Invalid JSON format"
                })
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await connection_manager.disconnect(websocket)
