"""Resumable local dubbing CLI. Heavy ML imports happen only in generate."""
from pathlib import Path
import argparse, contextlib, hashlib, json, os, re, subprocess, sys, time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temp.replace(path)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def event(name, **fields):
    record = {'time':time.strftime('%Y-%m-%dT%H:%M:%S'), 'event':name, **fields}
    count=fields.get('done',fields.get('current'))
    progress=f" {count}/{fields['total']} ({count/fields['total']:.1%})" if count is not None and fields.get('total') else ''
    eta=f" | ETA ~{fields['eta_seconds']/60:.1f} min" if 'eta_seconds' in fields else ''
    detail=fields.get('error',fields.get('reason',fields.get('id',fields.get('scene',''))))
    print(f"[{record['time'][11:]}] {name}{progress}{eta} {detail or ''}", flush=True)
    if OUT:
        with (OUT/'events.jsonl').open('a', encoding='utf8') as f: f.write(json.dumps(record, ensure_ascii=False)+'\n')
        write(OUT/'status.json', record)

def game_closed():
    subprocess.run(['powershell','-NoProfile','-Command',
        "if (Get-Process -Name 'detnoir*' -ErrorAction SilentlyContinue) { Write-Error 'Close the game before GPU generation or installation'; exit 1 }"], check=True)

def selected(args):
    data = read(ROOT/args.manifest); rows = data if isinstance(data,list) else data['lines']
    all_count = len(rows)
    rows = [dict(r) for r in rows if r.get('status','ready') in ('ready','reviewed') and not r.get('blockers')]
    if args.scene: rows = [r for r in rows if args.scene in r.get('vo_path','') or args.scene in r.get('scene','')]
    # Manifest order is retained. Never sort entire story by text length.
    if args.limit: rows = rows[:args.limit]
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids): raise ValueError('Duplicate dialogue IDs in selected manifest')
    for r in rows:
        if not re.fullmatch('[0-9a-fA-F]+',r['id']): raise ValueError('Unsafe ID')
        if not r.get('tts_ru') or not r.get('speaker'): raise ValueError('Missing reviewed text/speaker: '+r['id'])
        for key in ('bank_path','media_path'):
            if r.get(key) and (Path(r[key]).is_absolute() or '..' in Path(r[key]).parts): raise ValueError('Unsafe asset path')
    return rows, all_count

def prepare(rows):
    import soundfile as sf
    originals = ROOT/'work/story-originals'; originals.mkdir(parents=True,exist_ok=True)
    extracted=ROOT/'work/extracted'; pak=ROOT_GAME/'detnoir/Content/Paks/pakchunk0-Windows.pak'
    def unpack(paths):
        missing=sorted({p for p in paths if not (extracted/p).exists()})
        for start in range(0,len(missing),30):
            cmd=[str(ROOT/'work/tools/repak/repak.exe'),'unpack',str(pak),'-o',str(extracted)]
            for p in missing[start:start+30]: cmd+=['-i',p]
            subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
    unpack([r['bank_path'] for r in rows])
    for i,r in enumerate(rows):
        xml=ROOT/r['bank_xml'] if r.get('bank_xml') else originals/(r['id']+'.xml')
        if not xml.exists():
            subprocess.run([sys.executable,str(ROOT/'work/tools/wwiser.pyz'),'-d','xml','-dn',str(xml.with_suffix('')),str(extracted/r['bank_path'])],check=True,stdout=subprocess.DEVNULL)
        fs=list(ET.parse(xml).iter('field')); ids={int(f.attrib['value']) for f in fs if f.attrib.get('name')=='sourceID'}
        if len(ids)!=1: raise ValueError('Ambiguous bank sourceID '+r['id'])
        r['media_id']=next(iter(ids)); r['media_path']='detnoir/Content/WwiseAudio/Media/English(US)/'+str(r['media_id'])+'.wem'
        r['bank_xml']=str(xml.relative_to(ROOT))
    unpack([r['media_path'] for r in rows])
    for i,r in enumerate(rows,1):
        wav=ROOT/r['original_wav'] if r.get('original_wav') else originals/(r['id']+'.wav')
        if not wav.exists(): subprocess.run([str(ROOT/'work/tools/vgmstream/vgmstream-cli.exe'),'-o',str(wav),str(extracted/r['media_path'])],check=True,stdout=subprocess.DEVNULL)
        info=sf.info(wav); r.update(original_wav=str(wav.relative_to(ROOT)),original_seconds=info.frames/info.samplerate,original_sr=info.samplerate,original_channels=info.channels)
        event('prepared',done=i,total=len(rows),id=r['id'])
    write(OUT/'prepared-manifest.json',rows)
    return rows

def verify_raw(rows):
    for r in rows:
        meta=read(OUT/'raw'/(r['id']+'.json'))
        if meta.get('text')!=r['tts_ru'] or meta.get('speaker')!=r['speaker']:
            raise ValueError('Raw metadata text/speaker mismatch: '+r['id'])
        if meta.get('wav_sha256') and meta['wav_sha256']!=digest(OUT/'raw'/(r['id']+'.wav')):
            raise ValueError('Raw WAV hash mismatch: '+r['id'])
        if meta.get('near_token_limit'): raise ValueError('Possible token limit truncation; review/regenerate: '+r['id'])

def settings(args):
    model=ROOT/args.model
    files=[p for p in model.rglob('*') if p.is_file() and (p.suffix in ('.safetensors','.json','.bin'))]
    # Full file hashes are computed once per invocation, then used for every line.
    identity={str(p.relative_to(model)):digest(p) for p in sorted(files)}
    if not identity: raise ValueError('Local model files missing')
    return {'model':identity,'language':'Russian','x_vector_only':True,'batch_size':args.batch_size,'max_new_tokens':args.max_new_tokens,'seed':args.seed,'seed_mode':args.seed_mode,'dtype':'bfloat16','attention':'sdpa'}

def generate(rows,args):
    game_closed()
    os.environ.update(HF_HOME=str(ROOT/'work/huggingface'),TORCH_HOME=str(ROOT/'work/torch-cache'),NUMBA_CACHE_DIR=str(ROOT/'work/numba-cache'),HF_HUB_OFFLINE='1')
    raw=OUT/'raw';raw.mkdir(exist_ok=True)
    cfg=settings(args)
    refs=read(ROOT/args.voices)
    for speaker in {r['speaker'] for r in rows}:
        if speaker not in refs: raise ValueError('No approved reference for speaker '+speaker)
    reference_hashes={s:digest(ROOT/r['path']) for s,r in refs.items()}
    def expected(r): return fingerprint({'text':r['tts_ru'],'speaker':r['speaker'],'reference':reference_hashes[r['speaker']],'settings':cfg})
    def valid(r):
        p=raw/(r['id']+'.wav'); m=raw/(r['id']+'.json')
        try:
            meta=read(m)
            return meta.get('fingerprint')==expected(r) and meta.get('wav_sha256')==digest(p)
        except (OSError,ValueError,KeyError): return False
    todo=[r for r in rows if not valid(r)]
    event('generation_plan',total=len(rows),remaining=len(todo),cached=len(rows)-len(todo))
    if not todo: return
    if (OUT/'STOP').exists(): event('stopped',reason='STOP file exists'); return
    import numpy as np, soundfile as sf, torch
    from qwen_tts import Qwen3TTSModel, VoiceClonePromptItem
    torch.set_num_threads(args.threads)
    event('loading_model',pid=os.getpid())
    model=Qwen3TTSModel.from_pretrained(str(ROOT/args.model),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa')
    cache=ROOT/'work/voice-cache-v2';cache.mkdir(parents=True,exist_ok=True);prompts={}
    for speaker in sorted({r['speaker'] for r in todo}):
        key=fingerprint({'speaker':speaker,'reference':reference_hashes[speaker],'model':cfg['model']})
        p=cache/(key+'.pt')
        if p.exists():
            vector=torch.load(p,map_location='cuda:0',weights_only=True)
            prompt=VoiceClonePromptItem(ref_code=None,ref_spk_embedding=vector,x_vector_only_mode=True,icl_mode=False,ref_text=None)
        else:
            audio,sr=sf.read(ROOT/refs[speaker]['path']);audio=audio.mean(axis=1) if audio.ndim>1 else audio
            prompt=model.create_voice_clone_prompt(ref_audio=(audio.astype(np.float32),sr),x_vector_only_mode=True)[0]
            torch.save(prompt.ref_spk_embedding.detach().cpu(),p)
        prompts[speaker]=prompt
    start=time.perf_counter(); done=0
    for offset in range(0,len(todo),args.batch_size):
        if (OUT/'STOP').exists(): event('stopped',done=done,total=len(todo)); break
        group=todo[offset:offset+args.batch_size]
        seed=args.seed if args.seed_mode=='fixed' else (args.seed+int(fingerprint([r['id'] for r in group])[:8],16)) % (2**31)
        torch.manual_seed(seed);np.random.seed(seed)
        event('batch_start',ids=[r['id'] for r in group],scene=group[0].get('scene',group[0].get('vo_path')),done=done,total=len(todo))
        torch.cuda.synchronize();tick=time.perf_counter()
        wavs,sr=model.generate_voice_clone(text=[r['tts_ru'] for r in group],language=['Russian']*len(group),voice_clone_prompt=[prompts[r['speaker']] for r in group],non_streaming_mode=True,max_new_tokens=args.max_new_tokens)
        torch.cuda.synchronize();seconds=time.perf_counter()-tick
        if len(wavs)!=len(group): raise ValueError('Wrong number of generated recordings')
        for r,a in zip(group,wavs):
            a=np.asarray(a).reshape(-1)
            if not np.isfinite(a).all() or len(a)<sr*.1 or np.max(np.abs(a))<.001: raise ValueError('Invalid speech '+r['id'])
            # Approaching token limit is explicitly flagged for listening/ASR; do not silently assert quality.
            near_limit=len(a)/sr >= args.max_new_tokens/12*.95
            dest=raw/(r['id']+'.wav'); temp=raw/(r['id']+'.tmp.wav')
            sf.write(temp,a,sr,subtype='PCM_16');temp.replace(dest)
            write(raw/(r['id']+'.json'),{'id':r['id'],'speaker':r['speaker'],'text':r['tts_ru'],'fingerprint':expected(r),'wav_sha256':digest(dest),'seconds':len(a)/sr,'seed':seed,'batch_seconds':seconds,'near_token_limit':near_limit,'quality_status':'needs_listener_or_asr_review'})
        done+=len(group);elapsed=time.perf_counter()-start
        event('batch_done',done=done,total=len(todo),cached=len(rows)-len(todo),scene=group[-1].get('scene',group[-1].get('vo_path')),elapsed_seconds=elapsed,lines_per_minute=done/elapsed*60,eta_seconds=elapsed/done*(len(todo)-done),batch_seconds=seconds)
    write(OUT/'generation-config.json',cfg)

@contextlib.contextmanager
def lock(path=None):
    p=path or OUT/'RUNNING.lock'
    p.parent.mkdir(parents=True,exist_ok=True)
    try: fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise RuntimeError('Run lock exists. Check PID inside before removing stale lock: '+str(p))
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try: yield
    finally: p.unlink(missing_ok=True)

def main():
    global OUT, ROOT_GAME
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','prepare','generate','fit','build','preview','install','run','resume','status','stop'])
    parser.add_argument('--manifest',default='data/story-manifest.json');parser.add_argument('--output',default='outputs/full-dub')
    parser.add_argument('--scene');parser.add_argument('--limit',type=int);parser.add_argument('--batch-size',type=int,default=4)
    parser.add_argument('--timing',choices=['speedup','both','pad','none'],default='speedup');parser.add_argument('--no-trim',action='store_true')
    parser.add_argument('--loudness',choices=['original','lufs','none'],default='original',help='Algorithmic postprocessing; never regenerates raw speech')
    parser.add_argument('--target-lufs',type=float,default=-20.0);parser.add_argument('--gain-db',type=float,default=0.0);parser.add_argument('--peak-db',type=float,default=-1.0)
    parser.add_argument('--no-fit',action='store_true');parser.add_argument('--no-build',action='store_true')
    parser.add_argument('--available-only',action='store_true',help='fit/build/preview only: select completed raw files with matching text and SHA256')
    parser.add_argument('--model',default='work/models/Qwen3-TTS-1.7B-Base');parser.add_argument('--voices',default='data/voices.json')
    parser.add_argument('--max-new-tokens',type=int,default=1024);parser.add_argument('--seed',type=int,default=42);parser.add_argument('--threads',type=int,default=6)
    parser.add_argument('--seed-mode',choices=['fixed','batch'],default='batch')
    parser.add_argument('--preset',choices=['optimized','preview'],default='optimized',help='preview: original comparison synthesis settings (single, fixed seed42, max384); fitting remains separately configurable')
    parser.add_argument('--package-name',default='NWTD_RU_Story_Qwen_P.pak');parser.add_argument('--game',help='Explicit local game install; required for prepare/run/resume/install')
    args=parser.parse_args()
    if args.command in ('prepare','run','resume','install') and not args.game:
        parser.error('--game is required for game preparation/installation; use examples/demo.py for the CPU demo')
    if args.preset=='preview': args.batch_size=1;args.seed=42;args.seed_mode='fixed';args.max_new_tokens=384
    if args.available_only and args.command not in ('fit','build','preview'):
        parser.error('--available-only is supported only for fit/build/preview')
    if args.limit is not None and args.limit<1: parser.error('--limit must be positive')
    if args.batch_size<1 or args.max_new_tokens<1: parser.error('batch-size and max-new-tokens must be positive')
    if not -70<=args.target_lufs<=-5: parser.error('--target-lufs must be between -70 and -5')
    if not -60<=args.gain_db<=60: parser.error('--gain-db must be between -60 and 60')
    if not -9<=args.peak_db<=0: parser.error('--peak-db must be between -9 and 0')
    OUT=(ROOT/args.output).resolve();OUT.mkdir(parents=True,exist_ok=True);ROOT_GAME=Path(args.game) if args.game else None
    if args.command=='status':
        print(json.dumps(read(OUT/'status.json') if (OUT/'status.json').exists() else {'status':'not started'},ensure_ascii=True,indent=2));return
    if args.command=='stop': (OUT/'STOP').touch();print('Stop requested after current batch');return
    if args.command=='resume':
        (OUT/'STOP').unlink(missing_ok=True)
        args.command='run'
    rows,total=selected(args)
    if args.command=='plan':
        print(json.dumps({'manifest_total':total,'selected_ready':len(rows),'speakers':sorted({r['speaker'] for r in rows}),'first_ids':[r['id'] for r in rows[:10]],'order':'manifest order; branches are not a single playthrough'},ensure_ascii=True,indent=2));return
    if args.available_only:
        available=[]
        for r in rows:
            try:
                meta=read(OUT/'raw'/(r['id']+'.json'))
                if meta.get('text')==r['tts_ru'] and meta.get('speaker')==r['speaker'] and meta.get('fingerprint') and not meta.get('near_token_limit') and meta.get('wav_sha256')==digest(OUT/'raw'/(r['id']+'.wav')): available.append(r)
            except (OSError,ValueError): pass
        event('partial_selection',available=len(available),selected_ready=len(rows),excluded=len(rows)-len(available))
        rows=available
    if not rows: raise ValueError('No ready rows selected')
    with lock():
        event('started',command=args.command,selected=len(rows),pid=os.getpid())
        if args.command in ('prepare','run'):
            # Voice references may lie outside the selected chapter.
            refs=read(ROOT/args.voices) if (ROOT/args.voices).exists() else {}
            data=read(ROOT/args.manifest); universe=data if isinstance(data,list) else data['lines']
            by_id={r['id']:r for r in universe}
            extra=[]; selected_ids={r['id'] for r in rows}
            for speaker in {r['speaker'] for r in rows}:
                ref=refs.get(speaker,{})
                ref_id=ref.get('reference_id')
                if ref.get('path') and not (ROOT/ref['path']).exists() and ref_id in by_id and ref_id not in selected_ids:
                    extra.append(dict(by_id[ref_id]));selected_ids.add(ref_id)
            if extra: prepare(extra)
            rows=prepare(rows)
        elif (OUT/'prepared-manifest.json').exists():
            prepared={r['id']:r for r in read(OUT/'prepared-manifest.json')}
            rows=[{**prepared.get(r['id'],{}),**r} for r in rows]
        if args.command in ('generate','run'):
            with lock(ROOT/'work/GPU-GENERATION.lock'): generate(rows,args)
        if args.command=='run' and (OUT/'STOP').exists(): return
        if args.command in ('fit','build','preview','install','run'):
            from audio_pipeline import fit_rows, build_package, preview, install_package
            if args.command in ('fit','build','preview') or (args.command=='run' and (not args.no_fit or not args.no_build)): verify_raw(rows)
            if args.command=='fit' or (args.command=='run' and not args.no_fit): fit_rows(ROOT,rows,OUT,mode=args.timing,trim=not args.no_trim,loudness=args.loudness,target_lufs=args.target_lufs,gain_db=args.gain_db,peak_db=args.peak_db,event=event)
            if args.command=='build' or (args.command=='run' and not args.no_build): build_package(ROOT,rows,OUT,args.package_name,event=event)
            if args.command=='preview': preview(ROOT,rows,OUT,event=event)
            if args.command=='install': game_closed(); install_package(ROOT,OUT,args.package_name,ROOT_GAME,event=event)
        event('complete',command=args.command,selected=len(rows))

OUT=None
if __name__=='__main__':
    try: main()
    except Exception as exc:
        event('failed',error=str(exc));raise
