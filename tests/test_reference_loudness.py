from pathlib import Path
import importlib.util,tempfile,unittest
import numpy as np,soundfile as sf
spec=importlib.util.spec_from_file_location('pipeline',Path(__file__).parents[1]/'scripts/audio_pipeline.py')
pipeline=importlib.util.module_from_spec(spec);spec.loader.exec_module(pipeline)

class ReferenceLoudnessTests(unittest.TestCase):
    def test_active_level_ignores_added_silence(self):
        sr=24000;a=np.sin(2*np.pi*440*np.arange(sr)/sr)*.1
        self.assertAlmostEqual(pipeline._active_rms(a,sr),pipeline._active_rms(np.r_[a,np.zeros(sr*3)],sr),places=10)

    def test_real_fit_reference_and_short_word_fallback(self):
        for seconds,method in [(2.,'original_integrated_lufs'),(.25,'original_active_rms_short_clip')]:
            with self.subTest(seconds=seconds),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);out=root/'out';(out/'raw').mkdir(parents=True);sr=24000;t=np.arange(int(seconds*sr))/sr
                original=np.sin(2*np.pi*1000*t)*.04;raw=np.sin(2*np.pi*250*t)*.12
                sf.write(root/'original.wav',original,sr);sf.write(out/'raw/1.wav',raw,sr)
                row={'id':'1','speaker':'fixture','tts_ru':'Тест','original_wav':'original.wav'}
                report=pipeline.fit_rows(root,[row],out,trim=False,loudness='reference')[0]
                fitted,rate=sf.read(out/'processed/1-fitted.wav')
                self.assertEqual(len(fitted),len(original));self.assertEqual(rate,sr)
                self.assertEqual(report['speed'],1)
                self.assertEqual(report['loudnorm_measurement']['method'],method)
                self.assertTrue(np.isfinite(fitted).all())
                if seconds>1:self.assertLess(abs(report['loudnorm_measurement']['final_error_lufs']),.6)
                else:self.assertLess(abs(20*np.log10(pipeline._active_rms(fitted,sr)/pipeline._active_rms(original,sr))),.03)

if __name__=='__main__':unittest.main()
