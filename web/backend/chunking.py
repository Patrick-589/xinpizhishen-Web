from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .parsers import ParsedBlock, ParsedDocument


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    content: str
    page: int
    section: str
    paragraph: int
    chunk_index: int
    content_hash: str
    metadata: dict[str, object]

    @property
    def embedding_text(self) -> str:
        return self.content


class SecuritiesChunker:
    def __init__(self, max_chars: int = 900, overlap_chars: int = 120):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(
        self,
        document_id: str,
        parsed: ParsedDocument,
        document_type: str,
        source_metadata: dict[str, object] | None = None,
    ) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        current: list[ParsedBlock] = []
        current_length = 0
        source_metadata = source_metadata or {}

        def emit(blocks: list[ParsedBlock]) -> None:
            if not blocks:
                return
            content = "\n".join(block.text for block in blocks).strip()
            if not content:
                return
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            index = len(chunks)
            csv_rows = [block.csv_row_number for block in blocks if block.csv_row_number is not None]
            spreadsheet_rows = [
                row_number
                for block in blocks
                for row_number in block.source_row_numbers
            ]
            sheet_names = [block.sheet_name for block in blocks if block.sheet_name]
            original_position = {
                "start_offset": blocks[0].source_start,
                "end_offset": blocks[-1].source_end,
                "start_page": blocks[0].page,
                "end_page": blocks[-1].page,
                "start_paragraph": blocks[0].paragraph_index,
                "end_paragraph": blocks[-1].paragraph_index,
            }
            chunks.append(
                ChunkRecord(
                    id=hashlib.sha256(f"{document_id}:{index}:{content_hash}".encode("utf-8")).hexdigest()[:32],
                    content=content,
                    page=blocks[0].page,
                    section=blocks[0].section,
                    paragraph=blocks[0].paragraph_index,
                    chunk_index=index,
                    content_hash=content_hash,
                    metadata={
                        **source_metadata,
                        "document_type": document_type,
                        "end_page": blocks[-1].page,
                        "end_paragraph": blocks[-1].paragraph_index,
                        "contains_table": any(block.block_type == "table" for block in blocks),
                        "csv_row_start": min(csv_rows) if csv_rows else None,
                        "csv_row_end": max(csv_rows) if csv_rows else None,
                        "spreadsheet_sheet": sheet_names[0] if sheet_names else None,
                        "spreadsheet_sheets": list(dict.fromkeys(sheet_names)),
                        "spreadsheet_row_start": min(spreadsheet_rows) if spreadsheet_rows else None,
                        "spreadsheet_row_end": max(spreadsheet_rows) if spreadsheet_rows else None,
                        "original_text_position": original_position,
                    },
                )
            )

        def overlap_tail(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
            remaining = self.overlap_chars
            overlap: list[ParsedBlock] = []
            for block in reversed(blocks):
                if remaining <= 0:
                    break
                if len(block.text) <= remaining:
                    overlap.insert(0, block)
                    remaining -= len(block.text)
                    continue
                tail = block.text[-remaining:]
                overlap.insert(0, ParsedBlock(
                    tail,
                    block.page,
                    block.section,
                    block.paragraph_index,
                    block.block_type,
                    max(block.source_start, block.source_end - len(tail)),
                    block.source_end,
                    block.csv_row_number,
                    block.source_row_numbers,
                    block.sheet_name,
                ))
                remaining = 0
            return overlap

        def flush(*, retain_overlap: bool = True) -> None:
            nonlocal current, current_length
            if not current:
                return
            emit(current)
            current = overlap_tail(current) if retain_overlap else []
            current_length = sum(len(block.text) for block in current)

        def split_large_block(block: ParsedBlock) -> list[ParsedBlock]:
            segments: list[ParsedBlock] = []
            step = max(1, self.max_chars - self.overlap_chars)
            start = 0
            while start < len(block.text):
                target_end = min(len(block.text), start + self.max_chars)
                end = target_end
                if block.block_type == "table" and target_end < len(block.text):
                    row_end = block.text.rfind("\n", start + max(1, self.max_chars // 2), target_end)
                    if row_end > start:
                        end = row_end
                segment_text = block.text[start:end].strip()
                if segment_text:
                    segment_start = block.text.find(segment_text, start, end)
                    segment_start = start if segment_start < 0 else segment_start
                    segments.append(ParsedBlock(
                        segment_text,
                        block.page,
                        block.section,
                        block.paragraph_index,
                        block.block_type,
                        block.source_start + segment_start,
                        min(block.source_start + segment_start + len(segment_text), block.source_end),
                        block.csv_row_number,
                        block.source_row_numbers,
                        block.sheet_name,
                    ))
                if end >= len(block.text):
                    break
                start = max(end - self.overlap_chars, start + 1)
            return segments

        for block in parsed.blocks:
            is_new_section = bool(current) and block.section != current[0].section
            clause_boundary = document_type in {"regulations", "internal_rules", "company_profile"} and block.block_type == "heading"
            if (is_new_section or clause_boundary) and current_length >= 250:
                flush()

            if len(block.text) > self.max_chars:
                if current:
                    flush(retain_overlap=False)
                for segment in split_large_block(block):
                    emit([segment])
                current = []
                current_length = 0
                continue

            if current and current_length + len(block.text) + 1 > self.max_chars:
                flush()
            current.append(block)
            current_length += len(block.text) + 1
        flush(retain_overlap=False)
        return chunks
