from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..models.recording import Recording, RecordingStatus


class RecordingsRepository:
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, recording_data: dict) -> Recording:
        recording = Recording(**recording_data)
        self.session.add(recording)
        await self.session.commit()
        await self.session.refresh(recording)
        return recording
    
    async def get_by_egress_id(self, egress_id: str) -> Optional[Recording]:
        result = await self.session.execute(
            select(Recording).where(Recording.egress_id == egress_id)
        )
        return result.scalar_one_or_none()
    
    async def update_by_egress_id(self, egress_id: str, update_data: dict) -> Optional[Recording]:
        await self.session.execute(
            update(Recording)
            .where(Recording.egress_id == egress_id)
            .values(**update_data)
        )
        await self.session.commit()
        return await self.get_by_egress_id(egress_id)


