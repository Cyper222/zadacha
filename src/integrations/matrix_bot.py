"""Matrix bot integration"""
import asyncio
import logging
from typing import Optional, Dict, Callable
from nio import AsyncClient, MatrixRoom, RoomMessageText

from ..bot.config import MatrixConfig, LiveKitConfig
from ..bot.commands import CommandHandler
from ..bot.event_handler import EventHandler
from ..bot.livekit_controller import LiveKitController
from .livekit_client import LiveKitClient
from nio.events import CallInviteEvent, CallHangupEvent

logger = logging.getLogger(__name__)


class MatrixBot:
    
    def __init__(
        self,
        livekit_client: Optional[LiveKitClient] = None,
        recording_service = None,
    ):
        self.config = MatrixConfig()
        self.client: Optional[AsyncClient] = None
        self.livekit_client = livekit_client
        self.recording_service = recording_service
        self.command_handler: Optional[CommandHandler] = None
        self.event_handler: Optional[EventHandler] = None
        self.running = False
        self._sync_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Запустить бота Matrix"""
        if self.running:
            logger.warning("Bot is already running")
            return
            

        if not self.livekit_client:
            livekit_config = LiveKitConfig()
            livekit_controller = LiveKitController(livekit_config)
        else:
            livekit_config = LiveKitConfig()
            livekit_controller = LiveKitController(livekit_config)

            livekit_controller.livekit_api = self.livekit_client.livekit_api
        

        self.client = AsyncClient(
            homeserver=self.config.homeserver,
            user=self.config.user_id,
            device_id=self.config.device_id,
        )
        self.client.access_token = self.config.access_token
        

        if not self.client.access_token:
            response = await self.client.login(password="")
            if isinstance(response, Exception):
                raise Exception(f"Failed to login: {response}")
        

        self.command_handler = CommandHandler(
            livekit_controller,
            recording_service=self.recording_service
        )
        self.event_handler = EventHandler(self, self.command_handler)
        

        # Register callbacks for messages
        self.client.add_event_callback(
            self._on_message,
            RoomMessageText
        )
        
        # Register callbacks for call events
        self.client.add_event_callback(
            self._on_call_invite,
            CallInviteEvent
        )
        
        self.client.add_event_callback(
            self._on_call_hangup,
            CallHangupEvent
        )
        
        logger.info(f"Matrix bot started as {self.config.user_id}")
        self.running = True
        
    async def run(self) -> None:
        """Запустите бота (цикл синхронизации)."""
        if not self.running:
            await self.start()
        
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        try:
            await self.client.sync_forever(timeout=30000, full_state=True)
        except asyncio.CancelledError:
            logger.info("Bot sync cancelled")
        except Exception as e:
            logger.error(f"Error in bot sync: {e}")
            raise
            
    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Callback for Matrix messages"""
        await self.event_handler.handle_message(room, event)
    
    async def _on_call_invite(self, room: MatrixRoom, event: CallInviteEvent) -> None:
        """Callback for call invite events"""
        await self.event_handler.handle_call_invite(room, event)
    
    async def _on_call_hangup(self, room: MatrixRoom, event: CallHangupEvent) -> None:
        """Callback for call hangup events"""
        await self.event_handler.handle_call_hangup(room, event)
        
    async def send_message(self, room_id: str, message: str) -> None:
        """Отправка сообщений Matrix room"""
        if not self.client:
            raise RuntimeError("Client not connected")
        
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": message
            }
        )
        
        if isinstance(response, Exception):
            logger.error(f"Failed to send message: {response}")
        else:
            logger.debug(f"Message sent to {room_id}")
            
    async def stop(self) -> None:
        """Остановить Matrix бота"""
        self.running = False
        
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.close()
            logger.info("Matrix bot stopped")

