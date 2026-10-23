"""CPU-only example: synthetic tones -> duration fitting -> listening preview."""
from pathlib import Path
import json
import sys
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audio_pipeline import fit_rows, preview

def tone(seconds,sr=24000,frequency=220):
    t=np.arange(round(seconds*sr))/sr
    envelope=np.minimum(1,t/.02)*np.minimum(1,(seconds-t)/.02)
    return .08*np.sin(2*np.pi*frequency*t)*envelope

def make_inputs(root):
    root=Path(root);out=root/'outputs/demo';raw=out/'raw'
    original=root/'work/demo/originals'
    raw.mkdir(parents=True,exist_ok=True);original.mkdir(parents=True,exist_ok=True)
    rows=json.loads((ROOT/'examples/manifest.json').read_text(encoding='utf8'))['lines']
    for row,seconds in zip(rows,[1.,2.8]):
        original_tone=tone(2,44100)
        sf.write(root/row['original_wav'],np.column_stack([original_tone,original_tone]),44100,subtype='PCM_16')
        sf.write(raw/(row['id']+'.wav'),tone(seconds),24000,subtype='PCM_16')
        (raw/(row['id']+'.json')).write_text(json.dumps({'text':row['tts_ru'],'speaker':row['speaker'],'synthetic_fixture':True}),encoding='utf8')
    return rows,out

def main():
    rows,out=make_inputs(ROOT)
    reports=fit_rows(ROOT,rows,out,mode='speedup',trim=False,loudness='none')
    assert all(r['speed']>=1 and r['exact_original_frames'] for r in reports)
    assert reports[0]['speed']==1 and reports[1]['speed']>1
    preview(ROOT,rows,out)
    print('Synthetic demo complete:',out/'opening-preview.wav')
    print('Not speech. No model, GPU, game files, network, or installation used.')

if __name__=='__main__':main()
