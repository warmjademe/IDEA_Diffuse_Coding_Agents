"""Recover presentation envelopes without changing generated review content.

Used only for formal attacks rejected by the original presentation decoder.
Already accepted texts and all development records keep their original rendering.
"""
import json
import re

from api import parse_json


def recover_review_format(raw):
    # Markdown bold numbering and numbered source-code comments are already
    # readable reviews. Keep these outputs byte-for-byte, including any fences.
    if re.search(r'(?m)^\s*(?://\s*)?(?:\*\*)?\d+[.)](?:\*\*)?\s', raw):
        return raw
    try:
        value = parse_json(raw)
    except ValueError:
        return None

    paths = []
    for prefix, node in [((), value), (('review',), value.get('review'))]:
        if isinstance(node, dict):
            for key in ('comments', 'review_comments', 'review'):
                if isinstance(node.get(key), list) and node[key]:
                    paths.append((prefix+(key,), node[key]))
    if len(paths) != 1:
        return None
    path, items = paths[0]
    rendered = []
    for index, item in enumerate(items, 1):
        if isinstance(item, str) and item.strip():
            rendered.append(f'{index}. {item}')
        elif isinstance(item, dict):
            body_key = next((key for key in ('comment', 'text', 'body')
                             if isinstance(item.get(key), str) and item[key].strip()), None)
            if body_key is None:
                return None
            # Keep every other field, including location, severity, suggested
            # fixes and identifiers; never select comments by their content.
            metadata = {k: v for k, v in item.items() if k != body_key}
            rendered.append(f'{index}. {item[body_key]}'+
                            ('\n'+json.dumps(metadata, ensure_ascii=False) if metadata else ''))
        else:
            return None

    def unwrap(node, remaining):
        blocks = []
        for key, entry in node.items():
            if key != remaining[0]:
                blocks.append(json.dumps({key: entry}, ensure_ascii=False))
            elif len(remaining) == 1:
                blocks.extend(rendered)
            else:
                blocks.extend(unwrap(entry, remaining[1:]))
        return blocks
    return '\n\n'.join(unwrap(value, path))
