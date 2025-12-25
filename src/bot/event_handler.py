"""Matrix event handler"""
import logging
from typing import Optional, Dict, Any
from nio import MatrixRoom, RoomMessageText
from nio.events import Event, UnknownEvent
from nio.events.room_events import RoomMemberEvent

from .commands import CommandHandler

logger = logging.getLogger(__name__)

# New VoIP protocol event types (MSC3401/MSC2746)
CALL_EVENT_TYPES = {
    "org.matrix.msc3401.call",  # New call protocol
    "org.matrix.msc3401.call.member",  # Call member event (participant joined)
    "org.matrix.msc4075.call.notify",  # Call notification
    "m.call.negotiate",  # Call negotiation
    "m.call.sdp",  # SDP offer/answer
    "m.call.candidates",  # ICE candidates
}

# Events that indicate call start
CALL_START_EVENTS = {
    "org.matrix.msc3401.call",
    "org.matrix.msc3401.call.member",  # Member joining indicates active call
    "org.matrix.msc4075.call.notify",  # Notification indicates incoming call
    "m.call.negotiate",
}


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
        room: str,
        event: RoomMessageText
    ) -> None:
        """Handle incoming message events"""
        if event.sender == self.matrix_bot.client.user_id:
            return
        
        # Skip old events from room history (only process events from last 30 seconds)
        # This prevents processing old messages when bot starts
        try:
            origin_server_ts = getattr(event, 'source', {}).get('origin_server_ts', 0) if hasattr(event, 'source') else 0
            if not origin_server_ts and hasattr(event, 'source'):
                source = event.source
                if isinstance(source, dict):
                    origin_server_ts = source.get('origin_server_ts', 0)
            
            if origin_server_ts > 0:
                import time
                current_ts = int(time.time() * 1000)  # milliseconds
                age_seconds = (current_ts - origin_server_ts) / 1000
                # Skip events older than 30 seconds (only process very recent messages)
                if age_seconds > 30:
                    logger.debug(f"Skipping old message in room {room}, age: {age_seconds:.1f}s")
                    return
        except Exception as e:
            logger.debug(f"Could not check message timestamp: {e}")
        
        message_body = event.body.strip()

        if message_body.startswith("/"):
            response = await self.command_handler.handle_command(
                command=message_body,
                room_id=room,
                sender=event.sender
            )
            
            if response:
                await self.matrix_bot.send_message(room, response)
        else:
            logger.debug(f"Received message in {room}: {message_body[:50]}")
    
    async def handle_unknown_event(
        self,
        room_id: str,
        event: UnknownEvent
    ) -> None:
        """
        Handle unknown events - detects new VoIP protocol (MSC3401/MSC2746)
        
        New VoIP events are mapped as UnknownEvent by matrix-nio:
        - org.matrix.msc3401.call - call start
        - m.call.negotiate - call negotiation
        - m.call.sdp - SDP offer/answer
        - m.call.candidates - ICE candidates
        """
        # Skip old events from room history (only process events from last 2 minutes)
        # This prevents processing old call events when bot starts
        try:
            source = getattr(event, 'source', {})
            if isinstance(source, dict):
                origin_server_ts = source.get('origin_server_ts', 0)
                if origin_server_ts > 0:
                    import time
                    current_ts = int(time.time() * 1000)  # milliseconds
                    age_seconds = (current_ts - origin_server_ts) / 1000
                    # Skip events older than 2 minutes (for call events, we want recent ones)
                    if age_seconds > 2 * 60:
                        logger.debug(f"Skipping old event in room {room_id}, type: {getattr(event, 'type', 'unknown')}, age: {age_seconds:.1f}s")
                        return
        except Exception as e:
            logger.debug(f"Could not check event timestamp: {e}")
        
        # Get event type from source dict
        event_type = getattr(event, 'type', None)
        if not event_type:
            # Try to get from source
            source = getattr(event, 'source', {})
            if isinstance(source, dict):
                event_type = source.get('type')
        
        if not event_type:
            return
        
        # Check if this is a call event
        is_call_event = event_type in CALL_EVENT_TYPES or any(
            call_type in event_type for call_type in ['call', 'negotiate', 'sdp', 'candidates']
        )
        
        # Log all call-related unknown events for debugging
        if is_call_event:
            source = getattr(event, 'source', {})
            logger.info(f"📞 Call-related UnknownEvent: type={event_type}, room={room_id}")
            if isinstance(source, dict):
                content = source.get('content', {})
                if isinstance(content, dict):
                    logger.info(f"   Content keys: {list(content.keys())}")
                    if 'call_id' in content:
                        logger.info(f"   call_id: {content.get('call_id')}")
        
        if not is_call_event:
            return
        
        logger.info(f"Detected call event in room {room_id}, type: {event_type}")
        
        # Skip events from our bot
        sender = getattr(event, 'sender', None)
        if sender == self.matrix_bot.client.user_id:
            return
        
        # Get call_id from event content
        call_id = None
        source = getattr(event, 'source', {})
        if isinstance(source, dict):
            content = source.get('content', {})
            if isinstance(content, dict):
                # Try different possible keys for call_id
                call_id = (
                    content.get('call_id') or 
                    content.get('callID') or 
                    content.get('conf_id') or 
                    content.get('conference_id')
                )
                # If call_id is empty string or whitespace, treat as None
                if call_id and isinstance(call_id, str):
                    call_id = call_id.strip()
                    if call_id == "":
                        call_id = None
                    
                if call_id:
                    logger.debug(f"Extracted call_id from content: {call_id}")
                else:
                    # Log content for debugging
                    logger.debug(f"No call_id in content, keys: {list(content.keys())}")
                    if 'call_id' in content:
                        logger.debug(f"call_id value (empty?): '{content.get('call_id')}'")
        
        # If no call_id, try to get from event_id or generate one
        if not call_id:
            event_id = getattr(event, 'event_id', None)
            if event_id:
                # Use room_id + event_id hash as call_id
                import hashlib
                call_id = hashlib.md5(f"{room_id}{event_id}".encode()).hexdigest()[:16]
                logger.debug(f"Generated call_id from event_id: {call_id}")
        
        if not call_id:
            logger.warning(f"⚠️ Call event without call_id: {event_type} in room {room_id}")
            # Still try to register call with room_id as call_id
            call_id = f"{room_id}_{event_type}"[:32]
            logger.info(f"Using generated call_id: {call_id}")
        
        # Handle call start events
        if event_type in CALL_START_EVENTS:
            # Check if call already registered
            if room_id not in self.command_handler.active_calls:
                self.command_handler.register_call(room_id, call_id)
                logger.info(f"✅ Call started in room {room_id}, call_id: {call_id}, event_type: {event_type}")
                
                # Create LiveKit room if dev_mode is enabled
                # This is production-ready: create room via LiveKit API
                if hasattr(self.matrix_bot, 'livekit_client') and hasattr(self.matrix_bot, 'livekit_config'):
                    if getattr(self.matrix_bot.livekit_config, 'dev_mode', False):
                        try:
                            await self.matrix_bot.livekit_client.create_room(room_name=call_id)
                            logger.info(f"✅ Created LiveKit room: {call_id} (dev_mode enabled)")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to create LiveKit room {call_id}: {e}")
                            # Don't fail the call registration if room creation fails
            else:
                logger.debug(f"Call already active in room {room_id}, call_id: {call_id}")
        
        # Handle call end - check for hangup/reject events
        # Note: New protocol may not have explicit hangup, need to track timeout
        elif event_type in ("m.call.hangup", "m.call.reject"):
            # Unregister call and stop recording if active
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
            else:
                logger.info(f"Call ended in room {room_id}, call_id: {call_id}, event_type: {event_type}")
        
        # Other call events (sdp, candidates) - just log
        else:
            logger.debug(f"Call event in room {room_id}, type: {event_type}, call_id: {call_id}")
    
    async def handle_room_event(self, room: str, event: Event) -> None:
        """Handle generic room events"""
        if isinstance(event, RoomMessageText):
            await self.handle_message(room, event)
        elif isinstance(event, UnknownEvent):
            await self.handle_unknown_event(room, event)
        else:
            logger.debug(f"Unhandled event type: {type(event).__name__}")


