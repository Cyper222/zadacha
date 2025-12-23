
import logging
from typing import Optional
from nio import MatrixRoom, RoomMessageText
from nio.events import Event

from .commands import CommandHandler

logger = logging.getLogger(__name__)


class EventHandler:
    """Обработчик событий Matrix"""
    
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
        """
        Обрабатывает события входящих сообщений.

        Аргументы:
        room: Комната Matrix
        event: Событие сообщения
        """
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
    
    async def handle_room_event(self, room: MatrixRoom, event: Event) -> None:
        if isinstance(event, RoomMessageText):
            await self.handle_message(room, event)
        else:
            logger.debug(f"Unhandled event type: {type(event).__name__}")


