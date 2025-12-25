"""Command handlers for Matrix bot"""
import logging
from typing import Dict, Optional, Any
from nio import MatrixRoom, RoomMessageText

from .livekit_controller import LiveKitController

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles bot commands from Matrix messages"""
    
    def __init__(
        self,
        livekit_controller: LiveKitController,
        recording_service: Any = None  # RecordingService, using Any to avoid circular import
    ):
        self.livekit_controller = livekit_controller
        self.recording_service = recording_service
        self.active_recordings: Dict[str, str] = {}  # room_id -> egress_id
        self.active_calls: Dict[str, str] = {}  # room_id -> call_id
        
    async def handle_command(
        self,
        command: str,
        room_id: str,
        sender: str
    ) -> Optional[str]:
        """
        Handle a command from Matrix
        
        Args:
            command: Command text (e.g., "/record start")
            room_id: Matrix room ID where command was sent
            sender: User who sent the command
            
        Returns:
            Response message or None
        """
        parts = command.strip().split()
        if not parts:
            return None
            
        cmd = parts[0].lower()
        
        if cmd == "/record":
            if len(parts) < 2:
                return "Usage: /record start|stop"
            
            action = parts[1].lower()
            
            if action == "start":
                return await self._handle_record_start(room_id, sender)
            elif action == "stop":
                return await self._handle_record_stop(room_id, sender)
            else:
                return f"Unknown action: {action}. Use 'start' or 'stop'"
        
        return None
    
    async def _handle_record_start(
        self,
        room: str,
        sender: str
    ) -> str:
        """Handle /record start command"""
        room_id = room
        
        # Check if already recording
        if room_id in self.active_recordings:
            return f"Recording already in progress. Egress ID: {self.active_recordings[room_id]}"
        
        # Check if there's an active call in this room
        if room_id not in self.active_calls:
            return "❌ No active call in this room. Recording can only be started during an active call."
        
        call_id = self.active_calls[room_id]
        
        # Use call_id as LiveKit room name
        # call_id is unique per call and comes from Matrix VoIP events
        livekit_room_name = call_id
        
        logger.info(f"Starting recording for LiveKit room: {livekit_room_name} (Matrix room: {room_id}, call_id: {call_id})")
        
        try:
            # Check if LiveKit room exists, create if needed (dev_mode)
            # In production, rooms should exist; in dev_mode we can create them on demand
            if hasattr(self.livekit_controller, 'livekit_client') and self.livekit_controller.livekit_client:
                # Try to create room if it doesn't exist (only in dev_mode)
                # The recording service has access to livekit_client
                pass  # Will handle in recording service if needed
            
            # Use recording service if available, otherwise use controller directly
            if self.recording_service:
                recording = await self.recording_service.start_recording(
                    room_name=livekit_room_name,
                    matrix_room_id=room_id,
                    started_by=sender
                )
                egress_id = recording.egress_id
            else:
                result = await self.livekit_controller.start_recording(room_name=livekit_room_name)
                egress_id = result["egress_id"]
            
            self.active_recordings[room_id] = egress_id
            
            return (
                f"✅ Recording started!\n"
                f"LiveKit Room: {livekit_room_name}\n"
                f"Call ID: {call_id}\n"
                f"Egress ID: {egress_id}\n"
                f"Use /record stop to stop recording."
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to start recording: {e}")
            
            # Provide helpful error messages and try to create room if it doesn't exist
            if "room does not exist" in error_msg.lower() or "not_found" in error_msg.lower():
                # Try to create the room if in dev_mode
                try:
                    if hasattr(self, 'recording_service') and self.recording_service:
                        livekit_client = getattr(self.recording_service, 'livekit_client', None)
                        if livekit_client:
                            # Check if dev_mode is enabled
                            from ...config.config import LiveKitConfig
                            import inspect
                            config = getattr(livekit_client, 'config', None)
                            if config and getattr(config, 'dev_mode', False):
                                logger.info(f"Room {livekit_room_name} doesn't exist, creating it (dev_mode enabled)")
                                await livekit_client.create_room(room_name=livekit_room_name)
                                
                                # Retry recording after creating room
                                logger.info("Retrying recording after room creation")
                                try:
                                    recording = await self.recording_service.start_recording(
                                        room_name=livekit_room_name,
                                        matrix_room_id=room_id,
                                        started_by=sender
                                    )
                                    egress_id = recording.egress_id
                                    self.active_recordings[room_id] = egress_id
                                    
                                    return (
                                        f"✅ Recording started!\n"
                                        f"LiveKit Room: {livekit_room_name} (created)\n"
                                        f"Call ID: {call_id}\n"
                                        f"Egress ID: {egress_id}\n"
                                        f"Use /record stop to stop recording."
                                    )
                                except Exception as retry_error:
                                    logger.error(f"Failed to start recording after room creation: {retry_error}")
                                    return (
                                        f"❌ Room created but recording failed: {retry_error}\n"
                                        f"Room: {livekit_room_name}"
                                    )
                except Exception as create_error:
                    logger.debug(f"Failed to create room automatically: {create_error}")
                
                return (
                    f"❌ LiveKit room '{livekit_room_name}' does not exist.\n"
                    f"This usually means the LiveKit room hasn't been created yet.\n"
                    f"Please ensure the room exists in LiveKit before starting recording."
                )
            else:
                return f"❌ Failed to start recording: {error_msg}"
    
    async def _handle_record_stop(
        self,
        room: str,
        sender: str
    ) -> str:
        """Handle /record stop command"""
        room_id = room
        
        if room_id not in self.active_recordings:
            return "No active recording found for this room."
        
        egress_id = self.active_recordings[room_id]
        
        try:
            # Use recording service if available, otherwise use controller directly
            if self.recording_service:
                await self.recording_service.stop_recording(egress_id=egress_id)
            else:
                await self.livekit_controller.stop_recording(egress_id=egress_id)
            
            del self.active_recordings[room_id]
            
            return (
                f"✅ Recording stopped!\n"
                f"Egress ID: {egress_id}\n"
                f"Recording will be processed and saved."
            )
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            return f"❌ Failed to stop recording: {str(e)}"
    
    def register_call(self, room_id: str, call_id: str) -> None:
        """Register an active call in a room"""
        self.active_calls[room_id] = call_id
        logger.info(f"Call started in room {room_id}, call_id: {call_id}")
    
    def unregister_call(self, room_id: str) -> Optional[str]:
        """Unregister an active call in a room. Returns egress_id if recording is active."""
        if room_id in self.active_calls:
            call_id = self.active_calls.pop(room_id)
            logger.info(f"Call ended in room {room_id}, call_id: {call_id}")
            
            # If recording is active, return egress_id for automatic stopping
            if room_id in self.active_recordings:
                logger.info(f"Recording is active, will stop automatically due to call end in room {room_id}")
                return self.active_recordings.get(room_id)
        return None
    
    def has_active_call(self, room_id: str) -> bool:
        """Check if there's an active call in the room"""
        return room_id in self.active_calls


