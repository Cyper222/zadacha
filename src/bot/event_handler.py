"""Matrix event handler"""
import logging
from typing import Optional
from nio import MatrixRoom, RoomMessageText
from nio.events import Event, CallInviteEvent, CallHangupEvent

from .commands import CommandHandler

logger = logging.getLogger(__name__)


class EventHandler:
    """Handles Matrix events"""
    
    def __init__(
        self,
        matrix_bot,
        command_handler: CommandHandler
    ):
        self.matrix_bot = matrix_bot
        self.command_handler = command_handler
        
    async def handle_message(
        self,
        room: MatrixRoom,
        event: RoomMessageText
    ) -> None:
        """Handle incoming message events"""
        if event.sender == self.matrix_bot.client.user_id:
            return
        
        message_body = event.body.strip()

        if message_body.startswith("/"):
            response = await self.command_handler.handle_command(
                command=message_body,
                room=room,
                sender=event.sender
            )
            
            if response:
                await self.matrix_bot.send_message(room.room_id, response)
        else:
            logger.debug(f"Received message in {room.room_id}: {message_body[:50]}")
    
    async def handle_call_invite(
        self,
        room: MatrixRoom,
        event: CallInviteEvent
    ) -> None:
        """Handle call invite event (call started)"""
        room_id = room.room_id
        call_id = event.call_id
        
        # Register active call
        self.command_handler.register_call(room_id, call_id)
        logger.info(f"Call started in room {room_id}, call_id: {call_id}")
    
    async def handle_call_hangup(
        self,
        room: MatrixRoom,
        event: CallHangupEvent
    ) -> None:
        """Handle call hangup event (call ended)"""
        room_id = room.room_id
        
        # Unregister call and get egress_id if recording is active
        egress_id = self.command_handler.unregister_call(room_id)
        
        if egress_id:
            # Automatically stop recording if it was active
            try:
                if self.command_handler.recording_service:
                    await self.command_handler.recording_service.stop_recording(egress_id=egress_id)
                else:
                    await self.command_handler.livekit_controller.stop_recording(egress_id=egress_id)
                
                # Remove from active recordings
                if room_id in self.command_handler.active_recordings:
                    del self.command_handler.active_recordings[room_id]
                
                logger.info(f"Recording stopped automatically due to call end in room {room_id}, egress_id: {egress_id}")
            except Exception as e:
                logger.error(f"Failed to stop recording automatically: {e}")
    
    async def handle_room_event(self, room: MatrixRoom, event: Event) -> None:
        """Handle generic room events"""
        if isinstance(event, RoomMessageText):
            await self.handle_message(room, event)
        elif isinstance(event, CallInviteEvent):
            await self.handle_call_invite(room, event)
        elif isinstance(event, CallHangupEvent):
            await self.handle_call_hangup(room, event)
        else:
            logger.debug(f"Unhandled event type: {type(event).__name__}")


