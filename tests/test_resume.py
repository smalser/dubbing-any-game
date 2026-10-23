"""Exercise resume/cache invalidation with a fake synthesizer; no GPU/game access."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

spec=importlib.util.spec_from_file_location('dub',Path(__file__).parents[1]/'scripts/dub.py')
dub=importlib.util.module_from_spec(spec);spec.loader.exec_module(dub)

class ResumeTest(unittest.TestCase):
    def test_resume_and_invalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';out.mkdir();(root/'ref.wav').touch()
            dub.ROOT=root;dub.OUT=out
            dub.write(root/'voices.json',{'James':{'path':'ref.wav'}})
            sf.write(root/'ref.wav',np.sin(np.arange(12000)*.1)*.1,24000)
            calls=[]
            class Vector:
                def detach(self):return self
                def cpu(self):return self
            class Model:
                @classmethod
                def from_pretrained(cls,*a,**k): return cls()
                def create_voice_clone_prompt(self,**k):return [types.SimpleNamespace(ref_spk_embedding=Vector())]
                def generate_voice_clone(self,**k):
                    calls.append(k['text'])
                    return [np.sin(np.arange(7200)*.1)*.1 for _ in k['text']],24000
            fake_torch=types.SimpleNamespace(set_num_threads=lambda n:None,bfloat16='bf16',manual_seed=lambda n:None,cuda=types.SimpleNamespace(synchronize=lambda:None),save=lambda v,p:Path(p).write_bytes(b'cache'),load=lambda *a,**k:Vector())
            fake_qwen=types.SimpleNamespace(Qwen3TTSModel=Model,VoiceClonePromptItem=lambda **k:types.SimpleNamespace(**k))
            args=argparse.Namespace(model='model',voices='voices.json',batch_size=2,threads=1,seed=42,seed_mode='batch',max_new_tokens=384)
            rows=[{'id':str(i),'speaker':'James','tts_ru':'Тест '+str(i)} for i in range(1,4)]
            with patch.dict('sys.modules',{'torch':fake_torch,'qwen_tts':fake_qwen}),patch.object(dub,'game_closed'),patch.object(dub,'settings',return_value={'model':'fake-v1'}):
                dub.generate(rows,args);self.assertEqual(len(calls),2)
                dub.generate(rows,args);self.assertEqual(len(calls),2)
                rows[0]['tts_ru']='Изменённый текст';dub.generate(rows,args);self.assertEqual(len(calls),3)
                (out/'raw/2.wav').write_bytes(b'corrupt');dub.generate(rows,args);self.assertEqual(len(calls),4)
                (out/'STOP').touch();rows[1]['tts_ru']='Другой текст';dub.generate(rows,args);self.assertEqual(len(calls),4)
            self.assertEqual(dub.read(out/'status.json')['event'],'stopped')

if __name__=='__main__':unittest.main()
