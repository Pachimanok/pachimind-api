"""A confirmed Inbox classification archives only an overlay, not the source."""
from hashlib import sha256
import json

def apply_classification(metadata, root, note_id, raw):
    path = root / '.pachimind/inbox_classifications' / (sha256(note_id.encode()).hexdigest()+'.json')
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 300000:
            return metadata
        value = json.loads(path.read_text())
        if value.get('note_id') != note_id or value.get('source_sha256') != sha256(raw).hexdigest() or value.get('state') != 'approved':
            return metadata
        derived = root / value['result']['path']
        if derived.is_symlink() or not derived.resolve().is_relative_to(root.resolve()) or not derived.is_file(): return metadata
        return {**metadata, 'estado': 'archivado'}
    except (OSError, ValueError, KeyError, TypeError): return metadata
