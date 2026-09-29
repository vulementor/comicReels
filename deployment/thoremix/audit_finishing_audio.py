"""Read-only PCM audit of installed packages; writes evidence only to --report-dir.

ASR timestamps are diagnostic windows, never a speech/lip-sync certification.
No browser, generation, package mutation or publishing is performed.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RATE = 16000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run(tool, args):
    strict = ['-xerror'] if tool.stem == 'ffmpeg' else []
    return subprocess.run([str(tool), '-v', 'error', *strict, *args], check=True,
        capture_output=True, timeout=120,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout


def decode(tool, path, filters=None):
    args = ['-i', str(path), '-map', '0:a:0', '-vn']
    if filters:
        args += ['-af', filters]
    raw = run(tool, [*args, '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'])
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def stats(pcm):
    rms = float(np.sqrt(np.mean(pcm * pcm))) if len(pcm) else 0
    audible=np.flatnonzero(np.abs(pcm)>.00001)
    return {'samples': len(pcm), 'rms': rms,
            'rms_dbfs': float(20 * np.log10(rms)) if rms else None,
            'peak': float(np.max(np.abs(pcm))) if len(pcm) else 0,
            'all_zero': not bool(np.any(pcm)),
            'first_signal_s':float(audible[0]/RATE) if len(audible) else None,
            'last_signal_s':float(audible[-1]/RATE) if len(audible) else None}


def compare(a, b, start=0, end=None):
    begin = round(start * RATE)
    stop = min(len(a), len(b), round(end * RATE) if end is not None else max(len(a),len(b)))
    x, y = a[begin:stop], b[begin:stop]
    xx = float(x @ x)
    return {'start_s': start, 'end_s': stop / RATE, 'source': stats(x), 'output': stats(y),
            'source_gain': float(x @ y / xx) if xx else None,
            'correlation': float(np.corrcoef(x,y)[0,1]) if xx and np.any(y) else None,
            'difference': stats(y-x)}


def probe(tool, path):
    data = json.loads(run(tool, ['-show_entries', 'format=duration:stream=codec_type,width,height,sample_rate,channels,duration', '-of', 'json', str(path)]))
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--report-dir', type=Path, required=True)
    args = p.parse_args()
    ffmpeg, ffprobe = (args.root / 'runtime/bin' / (name+'.exe') for name in ('ffmpeg','ffprobe'))
    rows = []
    # Completed package video plus standalone finished files; ignore render caches.
    for folder in sorted(args.output.iterdir()):
        if not folder.is_dir():
            continue
        manifest = folder / 'package.json'
        package = read(manifest) if manifest.exists() else {}
        targets = [Path(package['video_path'])] if package else list(folder.glob('*.mp4'))
        for final in targets:
            pcm = decode(ffmpeg, final)
            row = {'clip': folder.name, 'job_id': package.get('job_id'),
                   'final': str(final), 'final_sha256': digest(final),
                   'manifest_sha256': digest(manifest) if manifest.exists() else None,
                   'final_hash_matches_manifest': digest(final)==package.get('video_sha256') if package else None,
                   'final_media': probe(ffprobe,final), 'final_pcm': stats(pcm),
                   'finishing_applied': bool(package.get('finishing'))}
            finish = package.get('finishing')
            if not finish:
                row['classification'] = 'not_processed_by_finishing'
                rows.append(row)
                continue
            base = Path(finish['base_path']); source = decode(ffmpeg,base)
            start, end = finish['laugh']['start_s'], finish['laugh']['end_s']
            row.update(base=str(base), base_sha256=digest(base),
                       base_hash_matches_receipt=digest(base)==finish['base_sha256'],
                       base_media=probe(ffprobe,base), base_pcm=stats(source),
                       before_laugh=compare(source,pcm,.1,max(.1,start-.1)),
                       during_laugh=compare(source,pcm,start+.1,end-.1),
                       laugh=finish['laugh'], options=finish['options'])
            spec = finish['options']
            length = finish['laugh']['duration_s']
            laugh = decode(ffmpeg, Path(spec['laugh_path']),
                f'atrim=duration={length:.6f},asetpts=PTS-STARTPTS,volume={spec["laugh_volume"]},'
                f'afade=t=out:st={max(0,length-.08):.6f}:d=0.08,adelay={round(start*1000)}:all=1')
            laugh = np.pad(laugh,(0,max(0,len(source)-len(laugh))))[:len(source)]
            begin, stop = round((start+.1)*RATE), min(len(pcm),len(source),round((end-.1)*RATE))
            x, l, y = source[begin:stop], laugh[begin:stop], pcm[begin:stop]
            coeff = np.linalg.lstsq(np.column_stack((x,l)),y,rcond=None)[0]
            row['tail_decomposition'] = {'source_gain': float(coeff[0]), 'laugh_gain':float(coeff[1]),
                'source_rms':stats(x)['rms'],'laugh_rms':stats(l)['rms'],
                'laugh_over_source_db':float(20*np.log10(np.linalg.norm(l)/np.linalg.norm(x))) if np.any(x) else None,
                'residual':stats(y-coeff[0]*x-coeff[1]*l)}
            production = args.root/'data/production'/package['job_id']
            audio_receipt = production/'audio.json'
            row['prior_audio_qa'] = read(audio_receipt)['result']['data'] if audio_receipt.exists() else package.get('qa',{})
            native = production/'flow/highest.mp4'
            if not native.exists():
                native = production/'flow/original.mp4'
            # Legacy run has its own bound immutable receipt before production journals.
            legacy = args.root/'data/story-run-20260927'
            if not native.exists() and (legacy/'story-receipt.json').exists():
                receipt=read(legacy/'story-receipt.json')
                if Path(receipt['artifact']['package_path']).resolve()==manifest.resolve():
                    native=legacy/'native-720p.part.mp4'
                    row['legacy_native_receipt']=str(legacy/'story-receipt.json')
            if native.exists():
                native_pcm=decode(ffmpeg,native)
                row.update(native=str(native),native_sha256=digest(native),native_pcm=stats(native_pcm),
                           native_to_base=compare(native_pcm,source))
            transcript = production/'audio-diagnostic.json'
            if transcript.exists():
                diagnostic = read(transcript)
                row['asr_diagnostic_path']=str(transcript)
                row['speech_windows']=[{'text':word['word'],'probability':word['probability'],
                    **compare(source,pcm,word['start'],word['end'])} for word in diagnostic['words'] if word['end']>word['start']]
            row['quarter_second_windows']=[compare(source,pcm,i/4,min(end,(i+1)/4)) for i in range(int(end*4))]
            if not np.any(source):
                row['classification']='base_silent_before_finishing'
            elif not np.any(x):
                row['classification']='original_preserved_before_laugh_native_tail_silent'
            else:
                row['classification']='original_present_before_and_during_laugh'
            rows.append(row)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'sample_rate':RATE,
        'method':'Complete decode to mono f32 PCM; source-output covariance; simultaneous least squares of original and delayed supplied laugh; existing ASR timestamps only.',
        'limitations':'Signal presence and gain do not certify intelligibility, speaker identity, exact words or lip sync. No new ASR or TTS. Mono measurement is not a stereo perceptual assessment.',
        'rows':rows}
    args.report_dir.mkdir(parents=True,exist_ok=True)
    (args.report_dir/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[]
    for r in rows:
        summary.append({k:r.get(k) for k in ('clip','classification','base_pcm','final_pcm','tail_decomposition')})
    (args.report_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
