# APCF-META {"schema":1,"visibility":"public"}
"""Verify the actual emitted bytes, not another draft. No business side effects."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import re

def text_hash(text: str) -> str:
    return sha256(text.replace('\r\n','\n').encode('utf-8')).hexdigest()

@dataclass(frozen=True)
class PreparedPublication:
    project_id: str
    turn_id: str
    revision: int
    source_digest: str
    report_digest: str
    chat_digest: str

    @classmethod
    def prepare(cls, *, project_id, turn_id, revision, source_digest,
                full_report: str, short_chat: str, chat_limit: int = 900):
        if len(short_chat) > chat_limit:
            raise ValueError('chat_payload_exceeds_digest_budget')
        if len(re.findall(r'^##\s+\d+\.\s+', short_chat, re.M)) > 2:
            raise ValueError('full_report_cannot_be_chat_payload')
        if not all((project_id, turn_id, revision > 0, re.fullmatch(r'[0-9a-f]{64}',source_digest))):
            raise ValueError('publication_identity_missing')
        return cls(project_id,turn_id,revision,source_digest,text_hash(full_report),text_hash(short_chat))

    def verify_saved(self, *, current_report: str, turn_report: str):
        if text_hash(current_report) != self.report_digest or text_hash(turn_report) != self.report_digest:
            raise ValueError('saved_report_not_prepared_revision')

    def verify_sent(self, *, captured_chat: str, actual_revision: int, actual_source_digest: str):
        if actual_revision != self.revision or actual_source_digest != self.source_digest:
            raise ValueError('sent_message_revision_mismatch')
        if text_hash(captured_chat) != self.chat_digest:
            raise ValueError('sent_message_changed_after_validation')
