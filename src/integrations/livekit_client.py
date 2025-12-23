
import logging
from typing import Optional, Dict, Any
from livekit import api
from livekit.protocol import models

from ..bot.config import LiveKitConfig

logger = logging.getLogger(__name__)


class LiveKitClient:
    """Клиент LiveKit для операций записи."""
    
    def __init__(self):
        config = LiveKitConfig()
        self.livekit_api = api.LiveKitAPI(
            url=config.url,
            api_key=config.api_key,
            api_secret=config.api_secret
        )
        logger.info("LiveKit client initialized")
        
    async def start_recording(
        self,
        room_name: str,
        layout: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Начать запись комнаты LiveKit

        Аргументы:

        room_name: Название комнаты LiveKit для записи
        layout: Макет записи (необязательно)
        **kwargs: Дополнительные параметры записи

        Возвращает:
        Словарь с информацией о записи
        """
        try:
            egress_info = await self.livekit_api.egress.start_room_composite_egress(
                room_name=room_name,
                layout=layout or "speaker",
                file_outputs=[
                    models.EncodedFileOutput(
                        file_type=models.EncodedFileType.MP4,
                        filepath=f"recordings/{room_name}/{{time}}.mp4",
                    )
                ],
            )
            
            logger.info(f"Started recording for room {room_name}, egress_id: {egress_info.egress_id}")
            
            return {
                "egress_id": egress_info.egress_id,
                "room_name": room_name,
                "status": "active",
            }
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            raise
            
    async def stop_recording(self, egress_id: str) -> Dict[str, Any]:
        """
        Остановить активную запись

        Аргументы:

        egress_id: Идентификатор исходящего канала записи, которую нужно остановить

        Возвращает:
        Словарь с подтверждением остановки
        """
        try:
            await self.livekit_api.egress.stop_egress(egress_id=egress_id)
            logger.info(f"Stopped recording: {egress_id}")
            
            return {
                "egress_id": egress_id,
                "status": "stopped",
            }
            
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            raise


