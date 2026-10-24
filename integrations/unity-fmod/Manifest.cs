using System;
using System.IO;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace UniversalDubbing.Fmod
{
    public class Export { public int schema_version; public Entry[] entries; public string voice_bus; }
    public class Entry { public string id, event_guid, wav, sha256, sound_id; }
    public static class Manifest
    {
        static string Text(JObject obj, string key, bool optional = false) {
            JToken value = obj[key];
            if(optional && value == null) return null;
            if(value == null || value.Type != JTokenType.String || String.IsNullOrWhiteSpace((string)value)) throw new FormatException("Expected nonempty string: " + key);
            return (string)value;
        }
        public static Export Parse(string json) {
            JObject obj;
            using(var text = new StringReader(json.TrimStart('\uFEFF')))
            using(var reader = new JsonTextReader(text) { DateParseHandling=DateParseHandling.None, MaxDepth=16 }) {
                obj = JObject.Load(reader,new JsonLoadSettings {DuplicatePropertyNameHandling=DuplicatePropertyNameHandling.Error});
                if(reader.Read()) throw new FormatException("Trailing JSON content");
            }
            JToken version = obj["schema_version"], lines = obj["entries"];
            if(version == null || version.Type != JTokenType.Integer || (long)version != 1) throw new FormatException("Expected schema_version integer 1; actual=" + (version == null ? "missing" : version.ToString(Formatting.None)));
            if(lines == null || lines.Type != JTokenType.Array || ((JArray)lines).Count < 1 || ((JArray)lines).Count > 100000) throw new FormatException("Expected entries array count1..100000; actual_type=" + (lines == null ? "missing" : lines.Type.ToString()));
            string bus = Text(obj,"voice_bus",true) ?? "bus:/Voice";
            if(!bus.StartsWith("bus:/",StringComparison.Ordinal)) throw new FormatException("Expected FMOD bus:/ path");
            var entries = new List<Entry>();
            var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var events = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(JToken token in (JArray)lines) {
                JObject line = token as JObject;
                if(line == null) throw new FormatException("Entry must be an object");
                var entry = new Entry {id=Text(line,"id"), event_guid=Text(line,"event_guid"), wav=Text(line,"wav"), sha256=Text(line,"sha256"), sound_id=Text(line,"sound_id",true)};
                if(!Regex.IsMatch(entry.id,@"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$") || entry.id.EndsWith(".") || Regex.IsMatch(entry.id,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)",RegexOptions.IgnoreCase)) throw new FormatException("Unsafe ID: "+entry.id);
                entry.event_guid = new Guid(entry.event_guid).ToString("D");
                if(!Regex.IsMatch(entry.sha256,@"^[0-9a-f]{64}$")) throw new FormatException("Invalid lowercase SHA256: "+entry.id);
                if(Path.IsPathRooted(entry.wav) || Array.Exists(entry.wav.Replace('\\','/').Split('/'),part => part == ".." || part == "")) throw new FormatException("Unsafe relative WAV: "+entry.id);
                ulong sound;
                if(entry.sound_id != null && !UInt64.TryParse(entry.sound_id,out sound)) throw new FormatException("Invalid sound_id: "+entry.id);
                if(!ids.Add(entry.id) || !events.Add(entry.event_guid) || !paths.Add(entry.wav.Replace('\\','/'))) throw new FormatException("Duplicate ID/event/WAV: "+entry.id);
                entries.Add(entry);
            }
            return new Export {schema_version=1, voice_bus=bus, entries=entries.ToArray()};
        }
    }
}
