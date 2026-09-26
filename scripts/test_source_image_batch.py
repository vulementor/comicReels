"""Explicit live test: one source attachment and one gpt_fullproxy batch command.

Run on VULE-PC after pulling the committed code. Does not edit the running DB,
approve images, operate a browser directly, or submit Flow jobs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.comicreels.image_batch import generate_scene_batch, SCENE_BATCH_PROMPT
from agent.comicreels.images import sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-count', type=int, required=True)
    parser.add_argument('--confirm-generate', action='store_true', required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Existing output requires inspection, never an automatic second submit.
    with (args.output / 'request.json').open('x', encoding='utf-8') as stream:
        json.dump({'source_sha256': sha256_file(args.source), 'prompt': SCENE_BATCH_PROMPT}, stream, ensure_ascii=False)
    result = asyncio.run(generate_scene_batch(args.source, args.output, expected_count=args.expected_count))
    (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'state':'artifacts_received', 'count':len(result['images']), 'conversation_url':result['conversation_url']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
