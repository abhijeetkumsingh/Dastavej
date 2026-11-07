"""Database models. Only temporary job metadata is stored - never document contents."""
import json
from datetime import datetime, timedelta, timezone

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(db.Model):
    __tablename__ = "jobs"
    id = db.Column(db.String(32), primary_key=True)
    session_id = db.Column(db.String(32), index=True, nullable=False)
    kind = db.Column(db.String(32), nullable=False)  # input | output | scanner-page | ai-doc | report ...
    display_name = db.Column(db.String(200), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False)
    mime = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, default=0)
    meta_json = db.Column(db.Text, default="{}")  # technical metadata only (sizes, dimensions, page counts)
    created_at = db.Column(db.DateTime, default=utcnow)
    expires_at = db.Column(db.DateTime, index=True, nullable=False)

    @property
    def meta(self):
        try:
            return json.loads(self.meta_json or "{}")
        except ValueError:
            return {}

    def to_dict(self):
        return {
            "job_id": self.id,
            "kind": self.kind,
            "name": self.display_name,
            "mime": self.mime,
            "size": self.size,
            "meta": self.meta,
            "created_at": self.created_at.isoformat() + "Z",
            "expires_at": self.expires_at.isoformat() + "Z",
            "download_url": f"/api/jobs/{self.id}/download",
            "preview_url": f"/api/jobs/{self.id}/download?inline=1",
        }


def default_expiry(minutes):
    return utcnow() + timedelta(minutes=minutes)
