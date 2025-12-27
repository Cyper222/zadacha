
import logging
from typing import Dict, Optional, Any
from nio import MatrixRoom, RoomMessageText
from .livekit_controller import LiveKitController

logger = logging.getLogger(__name__)


class CommandHandler:
    
    def __init__(
        self,
        livekit_controller: LiveKitController,
        recording_service: Any = None
    ):
        self.livekit_controller = livekit_controller
        self.recording_service = recording_service
        self.active_recordings: Dict[str, str] = {}
        self.active_calls: Dict[str, str] = {}
        
    async def handle_command(
        self,
        command: str,
        room_id: str,
        sender: str
    ) -> Optional[str]:
        logger.info(f"🎯 CommandHandler.handle_command called: command='{command}', room_id='{room_id}', sender='{sender}'")
        try:
            parts = command.strip().split()
            if not parts:
                logger.warning("⚠️  Empty command parts")
                return "❌ Пустая команда. Используйте: /record start|stop"
                
            cmd = parts[0].lower()
            logger.info(f"🔍 Parsed command: '{cmd}'")
            
            if cmd == "/record":
                if len(parts) < 2:
                    logger.info("ℹ️  /record command without action")
                    return "Usage: /record start|stop"
                
                action = parts[1].lower()
                logger.info(f"🎬 /record command with action: '{action}'")
                
                if action == "start":
                    logger.info("▶️  Handling /record start")
                    return await self._handle_record_start(room_id, sender)
                elif action == "stop":
                    logger.info("⏹️  Handling /record stop")
                    return await self._handle_record_stop(room_id, sender)
                else:
                    logger.warning(f"⚠️  Unknown /record action: '{action}'")
                    return f"Unknown action: {action}. Use 'start' or 'stop'"
            
            logger.info(f"⚠️  Unknown command: '{cmd}'")
            return f"❌ Неизвестная команда: '{cmd}'. Доступные команды: /record start|stop"
        except Exception as e:
            logger.error(f"❌ Error in handle_command: {e}", exc_info=True)
            return f"❌ Ошибка при обработке команды: {str(e)}"
    
    async def _handle_record_start(
        self,
        room: str,
        sender: str
    ) -> str:
        room_id = room

        if room_id in self.active_recordings:
            return f"Recording already in progress. Egress ID: {self.active_recordings[room_id]}"
        
        # Check if there's an active call in this room
        if room_id not in self.active_calls:
            logger.warning(f"⚠️  No active call in room {room_id}. Active calls: {list(self.active_calls.keys())}")
            return (
                "❌ Нет активного звонка в этой комнате.\n"
                "Запись может быть запущена только во время активного звонка.\n"
                "Пожалуйста, начните звонок в Matrix, а затем используйте /record start."
            )
        
        call_id = self.active_calls[room_id]
        livekit_room_name = call_id
        logger.info(f"Starting recording for LiveKit room: {livekit_room_name} (Matrix room: {room_id}, call_id: {call_id})")
        
        try:
            if hasattr(self.livekit_controller, 'livekit_client') and self.livekit_controller.livekit_client:
                pass

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
                f"✅ Запись началась!\n"
                f"LiveKit Room: {livekit_room_name}\n"
                f"Call ID: {call_id}\n"
                f"Egress ID: {egress_id}\n"
                f"Используйте /record stop, чтобы остановить запись."
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to start recording: {e}")

            if "room does not exist" in error_msg.lower() or "not_found" in error_msg.lower():
                try:
                    if hasattr(self, 'recording_service') and self.recording_service:
                        livekit_client = getattr(self.recording_service, 'livekit_client', None)
                        if livekit_client:
                            config = getattr(livekit_client, 'config', None)
                            if config and getattr(config, 'dev_mode', False):
                                logger.info(f"Room {livekit_room_name} doesn't exist, creating it (dev_mode enabled)")
                                await livekit_client.create_room(room_name=livekit_room_name)
                                try:
                                    recording = await self.recording_service.start_recording(
                                        room_name=livekit_room_name,
                                        matrix_room_id=room_id,
                                        started_by=sender
                                    )
                                    egress_id = recording.egress_id
                                    self.active_recordings[room_id] = egress_id
                                    
                                    return (
                                        f"✅ Запись началась!\n"
                                        f"LiveKit Room: {livekit_room_name} (created)\n"
                                        f"Call ID: {call_id}\n"
                                        f"Egress ID: {egress_id}\n"
                                        f"Используйте /record stop, чтобы остановить запись."
                                    )
                                except Exception as retry_error:
                                    logger.error(f"Failed to start recording after room creation: {retry_error}")
                                    return (
                                        f"❌Комната создана, но запись не удалась.: {retry_error}\n"
                                        f"Комната: {livekit_room_name}"
                                    )
                except Exception:
                    pass
                
                return (
                    f"❌Комнаты LiveKit '{livekit_room_name}' не существует.\n"
                    f"Пожалуйста, убедитесь, что комната существует в LiveKit, прежде чем начинать запись."
                )
            else:
                return f"❌Не удалось начать запись: {error_msg}"
    
    async def _handle_record_stop(
        self,
        room: str,
        sender: str
    ) -> str:
        room_id = room
        
        if room_id not in self.active_recordings:
            logger.warning(f"⚠️  No active recording in room {room_id}. Active recordings: {list(self.active_recordings.keys())}")
            return (
                "❌ Нет активной записи в этой комнате.\n"
                "Используйте /record start, чтобы начать запись."
            )
        
        egress_id = self.active_recordings[room_id]
        
        try:
            if self.recording_service:
                await self.recording_service.stop_recording(egress_id=egress_id)
            else:
                await self.livekit_controller.stop_recording(egress_id=egress_id)
            
            del self.active_recordings[room_id]
            
            return (
                f"✅ Запись остановлена!\n"
                f"Egress ID: {egress_id}\n"
                f"Запись будет обработана и сохранена."
            )
        except Exception as e:
            logger.error(f"❌ Failed to stop recording: {e}", exc_info=True)
            return f"❌ Не удалось остановить запись: {str(e)}"
    
    def register_call(self, room_id: str, call_id: str) -> None:
        self.active_calls[room_id] = call_id
        logger.info(f"Call started in room {room_id}, call_id: {call_id}")
    
    def unregister_call(self, room_id: str) -> Optional[str]:
        if room_id in self.active_calls:
            call_id = self.active_calls.pop(room_id)
            logger.info(f"Call ended in room {room_id}, call_id: {call_id}")

            if room_id in self.active_recordings:
                logger.info(f"Recording is active, will stop automatically due to call end in room {room_id}")
                return self.active_recordings.get(room_id)
        return None
    
    def has_active_call(self, room_id: str) -> bool:
        return room_id in self.active_calls


