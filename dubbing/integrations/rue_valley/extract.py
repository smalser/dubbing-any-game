"""Extract serialized Articy objects using their game's managed type definitions."""
import argparse
import dataclasses
import json
from pathlib import Path

def extract(game: Path, output: Path):
    from dubbing.integrations.universal_modder import require_toolkit
    require_toolkit()
    import UnityPy
    from TypeTreeGeneratorAPI import TypeTreeGenerator
    data = game / 'Rue Valley_Data'
    if not (data / 'resources.assets').is_file():
        raise ValueError('Expected Rue Valley_Data/resources.assets under --game')
    generator = TypeTreeGenerator('2022.3.62f2')
    for dll in sorted((data / 'Managed').glob('*.dll')):
        generator.load_dll(dll.read_bytes())
    env = UnityPy.load(str(data / 'resources.assets'))
    wanted = {'InteractableDialogueFragment', 'DialogueFragment', 'Character', 'MainCharacter',
              'Interactable', 'GameScene', 'FlowFragment', 'UserFolder', 'Dialogue', 'SoundEffect',
              'ArticyLocalizationPackage', 'ArticyLocalizationManager'}
    cache = {}
    counts = {}
    failures = []
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'objects.jsonl').open('w', encoding='utf-8') as stream:
        for obj in env.objects:
            if obj.type.name != 'MonoBehaviour':
                continue
            script = obj.parse_monobehaviour_head().m_Script.deref_parse_as_object()
            if script.m_ClassName not in wanted or script.m_Namespace not in {'Articy.RueValley', 'Articy.Unity'}:
                continue
            key = (script.m_AssemblyName, script.m_Namespace + '.' + script.m_ClassName)
            if key not in cache:
                nodes = [dict(dataclasses.asdict(n), m_ByteSize=-1, m_Version=1)
                         for n in generator.get_nodes(*key)]
                # AssetsTools backend emits List<string> as string + Array. UnityPy
                # treats string specially; retain the same serialized array layout.
                for i, node in enumerate(nodes[:-1]):
                    child = nodes[i + 1]
                    if node['m_Type'] == 'string' and node['m_Name'] != 'data' and child['m_Type'] == 'Array' and child['m_Level'] == node['m_Level'] + 1 and i + 3 < len(nodes) and nodes[i + 3]['m_Type'] == 'string':
                        node['m_Type'] = 'vector'
                # Unity's enabled byte is followed by an aligned PPtr.
                for node in nodes:
                    if node['m_Name'] == 'm_Enabled' and node['m_Level'] == 1:
                        node['m_MetaFlag'] = 16384
                cache[key] = nodes
            try:
                tree = obj.read_typetree(nodes=cache[key], check_read=True)
            except Exception as exc:
                failures.append({'path_id': obj.path_id, 'class': script.m_ClassName, 'error': str(exc)})
                continue
            stream.write(json.dumps({'source': 'resources.assets', 'path_id': obj.path_id,
                                     'class': script.m_ClassName, 'byte_start': obj.byte_start, 'byte_size': obj.byte_size, 'data': tree}, ensure_ascii=False) + '\n')
            counts[script.m_ClassName] = counts.get(script.m_ClassName, 0) + 1
    report = {'counts': counts, 'failed': failures, 'in_game_verified': False}
    (output / 'extraction.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps({'read': str(args.game / 'Rue Valley_Data/resources.assets'), 'write': str(args.output), 'game_mutations': False}))
        return
    print(json.dumps(extract(args.game.resolve(), args.output.resolve()), ensure_ascii=False))

if __name__ == '__main__':
    main()
