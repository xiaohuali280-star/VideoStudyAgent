from sqlalchemy import inspect

from app.core.errors import StudyError


def require_review_schema(engine):
    if "quality_reviews" not in inspect(engine).get_table_names():
        raise StudyError("MIGRATION_REQUIRED", "请停机备份后显式升级 V3 数据库再生成资料。", 409)
