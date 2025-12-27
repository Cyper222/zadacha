
import logging
from typing import Optional, Dict, Any
from nio import MatrixRoom, RoomMessageText
from nio.events import Event, UnknownEvent
from nio.events.room_events import RoomMemberEvent

from .commands import CommandHandler

logger = logging.getLogger(__name__)

CALL_EVENT_TYPES = {
    "org.matrix.msc3401.call",
    "org.matrix.msc3401.call.member",
    "org.matrix.msc4075.call.notify",
    "m.call.negotiate",
    "m.call.sdp",
    "m.call.candidates",
}

CALL_START_EVENTS = {
    "org.matrix.msc3401.call",
    "org.matrix.msc3401.call.member",
    "org.matrix.msc4075.call.notify",
    "m.call.negotiate",
}


class EventHandler:
    
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
        sender = getattr(event, 'sender', 'unknown')
        if event.sender == self.matrix_bot.client.user_id:
            logger.info(f"⏭️  Skipping own message from {sender}")
            return

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
                if age_seconds > 30:
                    logger.info(f"⏭️  Skipping old message (age: {age_seconds:.1f}s)")
                    return
        except Exception as e:
            logger.warning(f"Error checking message age: {e}")
        
        message_body = event.body.strip()
        logger.info(f"💬 Processing message in room {room}: '{message_body}' from {sender}")

        if message_body.startswith("/"):
            logger.info(f"🔍 Detected command: {message_body}")
            try:
                response = await self.command_handler.handle_command(
                    command=message_body,
                    room_id=room,
                    sender=event.sender
                )
                
                if response:
                    logger.info(f"✅ Command response: {response}")
                    await self.matrix_bot.send_message(room, response)
                else:
                    logger.warning(f"⚠️  Command handler returned no response for: {message_body}")
                    # Send a default response if command handler returns None
                    await self.matrix_bot.send_message(room, f"❌ Команда '{message_body}' не распознана или не обработана.")
            except Exception as e:
                logger.error(f"❌ Error processing command '{message_body}': {e}", exc_info=True)
                try:
                    await self.matrix_bot.send_message(room, f"❌ Ошибка при обработке команды: {str(e)}")
                except Exception as send_error:
                    logger.error(f"❌ Failed to send error message: {send_error}")
        else:
            logger.info(f"ℹ️  Message is not a command (doesn't start with '/')")
    
    async def handle_unknown_event(
        self,
        room_id: str,
        event: UnknownEvent
    ) -> None:
        try:
            source = getattr(event, 'source', {})
            if isinstance(source, dict):
                origin_server_ts = source.get('origin_server_ts', 0)
                if origin_server_ts > 0:
                    import time
                    current_ts = int(time.time() * 1000)  # milliseconds
                    age_seconds = (current_ts - origin_server_ts) / 1000
                    if age_seconds > 2 * 60:
                        return
        except Exception:
            pass

        event_type = getattr(event, 'type', None)
        if not event_type:
            source = getattr(event, 'source', {})
            if isinstance(source, dict):
                event_type = source.get('type')
        
        if not event_type:
            return

        is_call_event = event_type in CALL_EVENT_TYPES or any(
            call_type in event_type for call_type in ['call', 'negotiate', 'sdp', 'candidates']
        )

        if is_call_event:
            source = getattr(event, 'source', {})
            logger.info(f"Call-related UnknownEvent: type={event_type}, room={room_id}")
            if isinstance(source, dict):
                content = source.get('content', {})
                if isinstance(content, dict):
                    logger.info(f"   Content keys: {list(content.keys())}")
                    if 'call_id' in content:
                        logger.info(f"   call_id: {content.get('call_id')}")
        
        if not is_call_event:
            return
        
        logger.info(f"Detected call event in room {room_id}, type: {event_type}")

        sender = getattr(event, 'sender', None)
        if sender == self.matrix_bot.client.user_id:
            return

        call_id = None
        source = getattr(event, 'source', {})
        if isinstance(source, dict):
            content = source.get('content', {})
            if isinstance(content, dict):
                call_id = (
                    content.get('call_id') or 
                    content.get('callID') or 
                    content.get('conf_id') or 
                    content.get('conference_id')
                )
                if call_id and isinstance(call_id, str):
                    call_id = call_id.strip()
                    if call_id == "":
                        call_id = None
                    
                if call_id:
                    logger.info(f"Extracted call_id from content: {call_id}")

        if not call_id and room_id in self.command_handler.active_calls:
            call_id = self.command_handler.active_calls[room_id]
            logger.info(f"Using existing call_id from active calls: {call_id}")

        if not call_id:
            event_id = getattr(event, 'event_id', None)
            if event_id:
                import hashlib
                call_id = hashlib.md5(f"{room_id}{event_id}".encode()).hexdigest()[:16]
                logger.info(f"Generated call_id from event_id: {call_id}")
        
        if not call_id:
            logger.warning(f"Call event without call_id: {event_type} in room {room_id}")
            call_id = f"{room_id}_{event_type}"[:32]
            logger.info(f"Using fallback call_id: {call_id}")

        if event_type in CALL_START_EVENTS:
            if room_id not in self.command_handler.active_calls:
                self.command_handler.register_call(room_id, call_id)
                logger.info(f"Call started in room {room_id}, call_id: {call_id}, event_type: {event_type}")

                if hasattr(self.matrix_bot, 'livekit_client') and hasattr(self.matrix_bot, 'livekit_config'):
                    if getattr(self.matrix_bot.livekit_config, 'dev_mode', False):
                        try:
                            await self.matrix_bot.livekit_client.create_room(room_name=call_id)
                            logger.info(f"Created LiveKit room: {call_id} (dev_mode enabled)")
                        except Exception as e:
                            logger.warning(f"Failed to create LiveKit room {call_id}: {e}")

        elif event_type in ("m.call.hangup", "m.call.reject"):
            egress_id = self.command_handler.unregister_call(room_id)
            
            if egress_id:
                try:
                    if self.command_handler.recording_service:
                        await self.command_handler.recording_service.stop_recording(egress_id=egress_id)
                    else:
                        await self.command_handler.livekit_controller.stop_recording(egress_id=egress_id)

                    if room_id in self.command_handler.active_recordings:
                        del self.command_handler.active_recordings[room_id]
                    
                    logger.info(f"Recording stopped automatically due to call end in room {room_id}, egress_id: {egress_id}")
                except Exception as e:
                    logger.error(f"Failed to stop recording automatically: {e}")
            else:
                logger.info(f"Call ended in room {room_id}, call_id: {call_id}, event_type: {event_type}")

    
    async def handle_room_event(self, room: str, event: Event) -> None:
        if isinstance(event, RoomMessageText):
            await self.handle_message(room, event)
        elif isinstance(event, UnknownEvent):
            await self.handle_unknown_event(room, event)


