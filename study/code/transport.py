"""Isolated API transport. Parent enforces a hard wall-clock deadline."""
import json
import os
from pathlib import Path
import re
import sys

from openai import OpenAI


def main():
    payload = json.load(sys.stdin)
    official = payload['role'] == 'official_pro'
    variable, filename = ('DEEPSEEK_API_KEY', 'deepseek.key') if official else ('TEAMOROUTER_API_KEY', 'teamrouter.key')
    try:
        key = os.environ.get(variable) or (Path.home()/'.config/jsep-diffuse'/filename).read_text().strip()
        endpoint = 'https://api.deepseek.com' if official else 'https://api.teamorouter.cn/v1'
        with OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=180) as client:
            response = client.chat.completions.create(**payload['request'])
            result = {'response': response.model_dump(mode='json'),
                      'request_id': getattr(response, '_request_id', None)}
    except Exception as error:
        result = {'error': re.sub(r'(?:sk-|ghp_|olp_|hf_)[A-Za-z0-9_-]+', '[REDACTED]', str(error))[:2000]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
