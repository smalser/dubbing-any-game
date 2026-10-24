"""Synthetic bank bytes and fake external tools; no proprietary fixtures."""
from pathlib import Path
import importlib.util
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

spec=importlib.util.spec_from_file_location('pipeline',Path(__file__).parents[1]/'scripts/audio_pipeline.py')
pipeline=importlib.util.module_from_spec(spec);spec.loader.exec_module(pipeline)

class BankAliasTests(unittest.TestCase):
    def test_install_requires_explicit_game(self):
        with self.assertRaisesRegex(ValueError,'Explicit game_dir'):
            pipeline.install_package('.', '.')

    def fixture(self,root,wrong_source=False):
        out=root/'out';(out/'raw').mkdir(parents=True);(out/'processed').mkdir()
        audio=.1*np.sin(np.arange(24000)*.1)
        for p in [root/'original.wav',out/'raw/1.wav',out/'processed/1-fitted.wav']:
            sf.write(p,audio,24000)
        row={'id':'1','speaker':'Fixture','tts_ru':'Synthetic','original_wav':'original.wav',
             'media_id':123,'media_path':'media/123.wem','bank_path':'banks/main.bnk',
             'bank_xml':'main.xml','bank_aliases':[{'bank_path':'banks/alias.bnk','bank_xml':'alias.xml'}]}
        for name,codec in [('main',0x40001),('alias',0x10001)]:
            bank=root/'work/extracted/banks'/f'{name}.bnk';bank.parent.mkdir(parents=True,exist_ok=True)
            source=124 if name=='alias' and wrong_source else 123
            bank.write_bytes(struct.pack('<III',source,codec,99))
            (root/f'{name}.xml').write_text(f'<root><field name="sourceID" value="{source}" offset="0"/><field name="ulPluginID" value="{codec}" offset="4"/><field name="uInMemoryMediaSize" value="99" offset="8"/></root>',encoding='utf8')
        pipeline._json(out/'fit-manifest.json',{'rows':[{'id':'1','raw_sha256':pipeline._sha256(out/'raw/1.wav'),
            'fitted_sha256':pipeline._sha256(out/'processed/1-fitted.wav'),'original_sha256':pipeline._sha256(root/'original.wav')}]})
        return row,out

    def test_alias_pcm_and_exact_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);row,out=self.fixture(root)
            expected={'media/123.wem','banks/main.bnk','banks/alias.bnk'}
            def fake_run(args):
                args=list(map(str,args))
                if 'convert' in args: shutil.copyfile(args[3],args[4])
                elif 'vgmstream-cli.exe' in args[0]: shutil.copyfile(args[3],args[2])
                elif args[1]=='pack':
                    stage=Path(args[-2])
                    self.assertEqual({p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()},expected)
                    for name in ['main','alias']:
                        source,codec,size=struct.unpack('<III',(stage/f'banks/{name}.bnk').read_bytes())
                        self.assertEqual((source,codec),(123,0x10001))
                        self.assertEqual(size,(stage/'media/123.wem').stat().st_size)
                    Path(args[-1]).write_bytes(b'synthetic-package')
                elif args[1]=='list': return '\n'.join(sorted(expected))
                else: self.fail(str(args))
                return ''
            with patch.object(pipeline,'_run',side_effect=fake_run):
                report=pipeline.build_package(root,[row],out)
            self.assertEqual((report['lines'],report['media'],report['banks'],report['bank_aliases']),(1,1,2,1))
            self.assertEqual(set(report['files']),expected)

    def test_wrong_alias_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);row,out=self.fixture(root,wrong_source=True)
            def fake_convert(args):
                shutil.copyfile(args[3],args[4]);return ''
            with patch.object(pipeline,'_run',side_effect=fake_convert):
                with self.assertRaisesRegex(ValueError,'does not refer'):
                    pipeline.build_package(root,[row],out)

if __name__=='__main__':unittest.main()
