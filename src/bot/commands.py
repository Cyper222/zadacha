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
        room: MatrixRoom,
        sender: str
    ) -> Optional[str]:
        """
        Handle a command from Matrix
        
        Args:
            command: Command text (e.g., "/record start")
            room: Matrix room where command was sent
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
                return "Usage: /record start|stop [room_name]"
            
            action = parts[1].lower()
            room_name = parts[2] if len(parts) > 2 else None
            
            if action == "start":
                return await self._handle_record_start(room, sender, room_name)
            elif action == "stop":
                return await self._handle_record_stop(room, sender, room_name)
            else:
                return f"Unknown action: {action}. Use 'start' or 'stop'"
        
        return None
    
    async def _handle_record_start(
        self,
        room: MatrixRoom,
        sender: str,
        room_name: Optional[str]
    ) -> str:
        """Handle /record start command"""
        room_id = room.room_id
        
        # Check if already recording
        if room_id in self.active_recordings:
            return f"Recording already in progress. Egress ID: {self.active_recordings[room_id]}"
        
        # Check if there's an active call in this room
        if room_id not in self.active_calls:
            return "❌ No active call in this room. Recording can only be started during an active call."
        
        call_id = self.active_calls[room_id]
        
        # Use provided room_name or generate from Matrix room ID
        if not room_name:
            room_name = room.room_id.split(":")[0].replace("!", "").replace("#", "")
        
        try:
            # Use recording service if available, otherwise use controller directly
            if self.recording_service:
                recording = await self.recording_service.start_recording(
                    room_name=room_name,
                    matrix_room_id=room_id,
                    started_by=sender
                )
                egress_id = recording.egress_id
            else:
                result = await self.livekit_controller.start_recording(room_name=room_name)
                egress_id = result["egress_id"]
            
            self.active_recordings[room_id] = egress_id
            
            return (
                f"✅ Recording started!\n"
                f"Room: {room_name}\n"
                f"Call ID: {call_id}\n"
                f"Egress ID: {egress_id}\n"
                f"Use /record stop to stop recording."
            )
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            return f"❌ Failed to start recording: {str(e)}"
    
    async def _handle_record_stop(
        self,
        room: MatrixRoom,
        sender: str,
        room_name: Optional[str]
    ) -> str:
        """Handle /record stop command"""
        room_id = room.room_id
        
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


