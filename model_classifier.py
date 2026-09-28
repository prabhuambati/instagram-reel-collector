from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .core import ReelRecord, find_ffmpeg, classify_record


def _json_from_text(text: str) -> dict[str, Any]:
    text = (text or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.S)
        return json.loads(match.group(0)) if match else {}


def _openai_chat(content: list[dict[str, Any]], model: str, max_tokens: int = 500) -> dict[str, Any]:
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return {'configured': False, 'reason': 'OPENAI_API_KEY is not configured'}
    payload = {'model': model, 'temperature': 0, 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': content}]}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(payload).encode(), headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            body = json.loads(response.read().decode())
        text = body['choices'][0]['message']['content']
        return {'configured': True, 'object': _json_from_text(text), 'raw': text}
    except Exception as exc:
        return {'configured': True, 'error': str(exc)}


def _data_url(path: Path) -> str:
    mime = 'image/jpeg' if path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()


def extract_media_evidence(video_path: str, work_dir: str | Path | None = None) -> dict[str, Any]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {'error': 'FFmpeg unavailable'}
    source = Path(video_path).expanduser().resolve()
    if not source.exists():
        return {'error': f'video not found: {source}'}
    owned = work_dir is None
    tmp = tempfile.TemporaryDirectory(prefix='reel_analysis_') if owned else None
    root = Path(tmp.name if tmp else work_dir)
    root.mkdir(parents=True, exist_ok=True)
    frames_pattern = root / 'frame_%02d.jpg'
    frames_cmd = [ffmpeg, '-y', '-i', str(source), '-vf', 'fps=1,scale=640:-2', '-frames:v', '4', str(frames_pattern)]
    subprocess.run(frames_cmd, capture_output=True, text=True, check=False)
    audio_path = root / 'audio.wav'
    audio_cmd = [ffmpeg, '-y', '-i', str(source), '-vn', '-t', '20', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio_path)]
    audio_proc = subprocess.run(audio_cmd, capture_output=True, text=True, check=False)
    frames = sorted(root.glob('frame_*.jpg'))
    result: dict[str, Any] = {'frames': [str(p) for p in frames], 'audio_path': str(audio_path) if audio_proc.returncode == 0 and audio_path.exists() else '', 'frame_count': len(frames), 'audio_ready': audio_proc.returncode == 0 and audio_path.exists()}
    if owned:
        # Keep extracted evidence only for the duration of model calls.
        result['_tmp'] = tmp
    return result


def visual_model_score(frame_paths: list[str], caption: str = '') -> dict[str, Any]:
    if not frame_paths:
        return {'available': False, 'reason': 'no frames'}
    content: list[dict[str, Any]] = [{
        'type': 'text',
        'text': ('Classify whether the reel visibly shows a human singing or playing an instrument. '
                 'Do not infer performance merely because music is present. Look for a visible singer, microphone, '
                 'instrument, playing posture, or live-performance context. Return JSON only with keys '
                 'performance_type, instrument, confidence (0 to 1), evidence, reject_reason. Caption: ' + caption)
    }]
    for path in frame_paths[:4]:
        content.append({'type': 'image_url', 'image_url': {'url': _data_url(Path(path)), 'detail': 'low'}})
    response = _openai_chat(content, os.getenv('OPENAI_VISION_MODEL', 'gpt-4o-mini'))
    obj = response.get('object') or {}
    return {'available': bool(response.get('configured') and not response.get('error')), **obj, 'error': response.get('error', '')}


def audio_model_score(audio_path: str, caption: str = '') -> dict[str, Any]:
    if not audio_path or not Path(audio_path).exists():
        return {'available': False, 'reason': 'no extracted audio'}
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return {'available': False, 'reason': 'OPENAI_API_KEY is not configured'}
    audio_b64 = base64.b64encode(Path(audio_path).read_bytes()).decode()
    content = [
        {'type': 'text', 'text': ('Classify the audio from this short reel. Decide whether it contains a human singing '
          'or a human playing an instrument, rather than only a studio track or speech. Return JSON only with keys '
          'performance_type, instrument, confidence (0 to 1), evidence, reject_reason. Caption: ' + caption)},
        {'type': 'input_audio', 'input_audio': {'data': audio_b64, 'format': 'wav'}},
    ]
    response = _openai_chat(content, os.getenv('OPENAI_AUDIO_MODEL', 'gpt-4o-audio-preview'), max_tokens=400)
    obj = response.get('object') or {}
    return {'available': bool(response.get('configured') and not response.get('error')), **obj, 'error': response.get('error', '')}


def analyze_media(video_path: str, caption: str = '', source_query: str = '') -> dict[str, Any]:
    heuristic = classify_record(ReelRecord(reel_url='local://analysis', caption=caption, source_query=source_query))
    evidence = extract_media_evidence(video_path)
    frames = evidence.get('frames', [])
    audio_path = evidence.get('audio_path', '')
    visual = visual_model_score(frames, caption) if os.getenv('OPENAI_API_KEY') else {'available': False, 'reason': 'OPENAI_API_KEY is not configured'}
    audio = audio_model_score(audio_path, caption) if os.getenv('OPENAI_API_KEY') else {'available': False, 'reason': 'OPENAI_API_KEY is not configured'}
    visual_conf = float(visual.get('confidence') or 0)
    audio_conf = float(audio.get('confidence') or 0)
    model_scores = [x for x in [visual_conf, audio_conf] if x > 0]
    combined = round((sum(model_scores) / len(model_scores)) if model_scores else heuristic.classifier_confidence, 2)
    if visual.get('performance_type') == 'instrument' and audio.get('performance_type') == 'singing':
        performance = 'singing_and_instrument'
    else:
        performance = visual.get('performance_type') or audio.get('performance_type') or heuristic.performance_type
    instrument = visual.get('instrument') or audio.get('instrument') or heuristic.instrument
    return {
        'performance_type': performance or 'unknown',
        'instrument': instrument or '',
        'classifier_confidence': combined,
        'visual_confidence': round(visual_conf, 2),
        'audio_confidence': round(audio_conf, 2),
        'model_confidence': combined if model_scores else 0,
        'model_provider': 'openai-compatible' if model_scores else 'heuristic',
        'model_explanation': '; '.join(filter(None, [visual.get('evidence'), audio.get('evidence'), heuristic.performance_type if heuristic.performance_type != 'unknown' else 'No strong text evidence']))[:1200],
        'visual': visual,
        'audio': audio,
        'media_evidence': {'frame_count': evidence.get('frame_count', 0), 'audio_ready': evidence.get('audio_ready', False)},
    }
