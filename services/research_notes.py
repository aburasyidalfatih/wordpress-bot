"""What a research run is missing, in words the user understands.

The research card used to show one generic "some data is fallback" warning for
almost every category, because Google Suggest often falls back to template
questions. Template (fallback) data is never given to the writer (only the
evidence_* lists are stored and used), so the warning now names the writer
evidence that is actually missing; optional sources that are simply
unavailable (social, YouTube, news, Wikipedia, Trends) are listed separately as
information, not as a warning.
"""

# Evidence the writer depends on: (status key, message when it fell back to a
# template, message when it is unavailable).
WRITER_EVIDENCE = (
    ('competitors', None, 'Data kompetitor tidak tersedia.'),
    ('related_questions', 'Pertanyaan pembaca memakai template cadangan; template itu tidak dipakai untuk artikel.',
     'Pertanyaan pembaca tidak ditemukan.'),
    ('google_autocomplete', 'Saran kata kunci Google memakai template cadangan; template itu tidak dipakai untuk '
                            'artikel.', 'Saran kata kunci Google tidak tersedia.'),
)
THIN_COMPETITORS = 'Kompetitor hanya berisi halaman tipis (sedikit kutipan terverifikasi).'

# Optional sources: (status key, label when unavailable, label when partial).
OPTIONAL_SOURCES = (
    ('social', 'Diskusi sosial tidak tersedia', None),
    ('youtube', 'Video YouTube tidak tersedia', 'Transkrip video tidak tersedia'),
    ('news', 'Berita terbaru tidak tersedia', None),
    ('wikipedia', 'Konteks Wikipedia tidak tersedia', None),
    ('google_trends', 'Data Google Trends tidak tersedia', None),
)


def _status(source_metadata, key):
    meta = (source_metadata or {}).get(key)
    return meta.get('status') if isinstance(meta, dict) else None


def evidence_warnings(source_metadata):
    """Indonesian warnings for missing or template-only writer evidence ([] when complete).

    A provider absent from source_metadata (older rows, or not part of that
    research) is not reported.
    """
    warnings = []
    for key, fallback_message, missing_message in WRITER_EVIDENCE:
        status = _status(source_metadata, key)
        if status is None or status == 'real':
            continue
        if status == 'fallback' and fallback_message:
            warnings.append(fallback_message)
        elif key == 'competitors' and status == 'partial':
            warnings.append(THIN_COMPETITORS)
        else:
            warnings.append(missing_message)
    return warnings


def optional_notes(source_metadata):
    """Labels of optional sources that were unavailable (information only)."""
    notes = []
    for key, missing_label, partial_label in OPTIONAL_SOURCES:
        status = _status(source_metadata, key)
        if status == 'partial' and partial_label:
            notes.append(partial_label)
        elif status in ('unavailable', 'fallback'):
            notes.append(missing_label)
    return notes
