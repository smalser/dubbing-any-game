from pathlib import Path
import importlib.util
import shutil
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audio_pipeline import fit_rows
spec=importlib.util.spec_from_file_location('demo',ROOT/'examples/demo.py')
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)

@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg is required for CPU fitting tests')
class FitTest(unittest.TestCase):
    def test_short_speech_not_slowed_and_long_speech_accelerated(self):
        with tempfile.TemporaryDirectory() as temp:
            rows,out=demo.make_inputs(temp)
            report=fit_rows(temp,rows,out,mode='speedup',trim=False,loudness='none')
            self.assertEqual(report[0]['speed'],1)
            self.assertGreater(report[1]['speed'],1)
            for row in rows:
                info=sf.info(out/'processed'/(row['id']+'-fitted.wav'))
                self.assertEqual((info.frames,info.samplerate,info.channels),(88200,44100,2))
            short,sr=sf.read(out/'processed/d001-fitted.wav')
            self.assertLess(np.max(np.abs(short[int(1.1*sr):])),.0001)

    def test_pad_refuses_cutting_a_long_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            rows,out=demo.make_inputs(temp)
            with self.assertRaisesRegex(ValueError,'cannot fit'):
                fit_rows(temp,rows,out,mode='pad',trim=False)

if __name__=='__main__':unittest.main()
