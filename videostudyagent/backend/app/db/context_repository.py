from sqlalchemy import insert, select

from app.core.errors import StudyError
from app.db.context_models import ContextSnapshotRow
from app.db.study_repository import StudyRepository
from app.schemas.video_context import VideoContextSnapshot
from app.services.storage import cache_key


def manifest(context):
    data = context.model_dump(mode="json", exclude={"manifest_sha256", "id"})
    return cache_key(context=data)


class VideoContextRepository(StudyRepository):
    def get(self, task_id, snapshot_id):
        with self.engine.connect() as connection:
            context = self._owned(
                connection, ContextSnapshotRow, VideoContextSnapshot, task_id, snapshot_id
            )
        if manifest(context) != context.manifest_sha256:
            raise StudyError("STORAGE_ERROR", "课程上下文散列不一致。", 409)
        return context

    def add(self, context):
        context = VideoContextSnapshot.model_validate(context)
        if manifest(context) != context.manifest_sha256:
            raise ValueError("Context manifest mismatch")
        with self._write() as connection:
            self._course(connection, context.task_id)
            old = connection.scalar(
                select(ContextSnapshotRow.payload).where(ContextSnapshotRow.id == str(context.id))
            )
            if old:
                if VideoContextSnapshot.model_validate(old) != context:
                    raise StudyError("STUDY_CONFLICT", "上下文不可覆盖。", 409)
                return context
            connection.execute(
                insert(ContextSnapshotRow).values(
                    id=str(context.id),
                    task_id=str(context.task_id),
                    transcript_snapshot_id=str(context.transcript_snapshot_id)
                    if context.transcript_snapshot_id
                    else None,
                    sha256=context.manifest_sha256,
                    payload=context.model_dump(mode="json"),
                )
            )
        return context
