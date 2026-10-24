using System;
using System.IO;
using UniversalDubbing.Fmod;
class ManifestCheck {
 static int Main(string[] args) {
  try { Export data=Manifest.Parse(File.ReadAllText(args[0])); Console.WriteLine("schema="+data.schema_version+" count="+data.entries.Length+" type="+data.GetType().FullName); return 0; }
  catch(Exception e) { Console.Error.WriteLine(e.GetType().Name+": "+e.Message); return 2; }
 }
}
