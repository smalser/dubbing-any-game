using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Reflection;
using StackTrace = System.Diagnostics.StackTrace;
using BepInEx;
using HarmonyLib;
using FMOD;
using FMOD.Studio;
using FMODUnity;
using UnityEngine;

namespace UniversalDubbing.Fmod
{
    public sealed class OverrideService
    {
        internal static OverrideService Instance;
        readonly BepInEx.Logging.ManualLogSource Logger;
        readonly BepInEx.Configuration.ConfigFile Config;
        bool shuttingDown;
        readonly Dictionary<string, Entry> entries = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<IntPtr, Playing> playing = new Dictionary<IntPtr, Playing>();
        string root; Bus voiceBus; ChannelGroup voiceGroup; bool busLocked;
        BepInEx.Configuration.ConfigEntry<bool> bridgeEnabled;
        BepInEx.Configuration.ConfigEntry<bool> redirectSaves;
        BepInEx.Configuration.ConfigEntry<string> voiceBusPath;
        bool dialogueBridgeActive;
        readonly NaturalCallContext naturalContext=new NaturalCallContext();
        static string tracePath;
        static readonly object traceLock = new object();
        static int rawSoundCalls, rawDialogueCalls, rawTickCalls, rawSaveCalls;
        int lastTickFrame=-1;
        int updateCount, dialogueCount, soundCount, saveReadCount, volumeCount;
        [ThreadStatic] static bool internalVolume;
        sealed class Playing { public Sound sound; public Channel channel; public OverrideLifecycle state; public string id; public EventInstance instance; }
        public OverrideService(BepInEx.Logging.ManualLogSource logger, BepInEx.Configuration.ConfigFile config, string location)
        {
            Logger=logger; Config=config; Instance=this;
            root=Path.GetDirectoryName(location);
            tracePath=Path.Combine(root,"runtime-diagnostics.jsonl");
            Trace("MANAGED_SERVICE_CREATED");
        }
        public void Initialize()
        {
            bridgeEnabled = Config.Bind("QA", "EnableFileBridge", false, "Allow exact event playback from test-event.txt");
            redirectSaves = Config.Bind("QA", "RedirectSaveDirectory", false, "Rue Valley QA only: isolate all SaveManager saves in plugin qa-saves folder");
            Harmony harmony=null;
            try {
                Export export = Manifest.Parse(File.ReadAllText(Path.Combine(root, "manifest.json")));
                Logger.LogInfo("UD_MANIFEST parser=" + typeof(Newtonsoft.Json.Linq.JObject).Assembly.FullName + " schema=" + export.schema_version + " count=" + export.entries.Length + " type=" + export.GetType().FullName);
                voiceBusPath = Config.Bind("Audio", "VoiceBus", String.IsNullOrEmpty(export.voice_bus) ? "bus:/Voice" : export.voice_bus, "Exact existing FMOD voice bus path");
                if(!voiceBusPath.Value.StartsWith("bus:/",StringComparison.Ordinal)) throw new Exception("Invalid FMOD voice bus path");
                if (export.schema_version != 1 || export.entries == null) throw new Exception("Unsupported manifest");
                foreach (Entry entry in export.entries) {
                    string key = new Guid(entry.event_guid).ToString("D");
                    string path = SafePath(entry.wav);
                    using (var hash = SHA256.Create()) using (var file = File.OpenRead(path)) {
                        string actual = BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
                        if (actual != entry.sha256) throw new Exception("SHA256 mismatch: " + entry.id);
                    }
                    if (entries.ContainsKey(key)) throw new Exception("Duplicate event: " + key);
                    entries.Add(key, entry);
                }
                // Validate every target and callback before installing even the first detour.
                List<Hook> plan=BuildHookPlan(redirectSaves.Value);
                harmony=new Harmony("local.universal-dubbing.fmod");
                foreach(Hook hook in plan) harmony.Patch(hook.target,prefix:hook.prefix,postfix:hook.postfix,finalizer:hook.finalizer);
                if(redirectSaves.Value) Logger.LogWarning("UD_QA_SAVE_DIRECTORY " + Path.Combine(root,"qa-saves") + " original_saves_untouched=true");
                foreach(var method in harmony.GetPatchedMethods()) {
                    var info = Harmony.GetPatchInfo(method);
                    if(info == null || !info.Owners.Contains("local.universal-dubbing.fmod")) throw new Exception("Patch ownership missing: "+method);
                    Logger.LogInfo("UD_PATCH target="+method.DeclaringType.FullName+"."+method.Name+" assembly="+method.DeclaringType.Assembly.Location+" prefixes="+info.Prefixes.Count+" postfixes="+info.Postfixes.Count);
                }
                Logger.LogInfo("UD_READY exact_events=" + entries.Count);
            } catch(Exception e) {
                try { if(harmony != null) harmony.UnpatchSelf(); }
                catch(Exception rollback) { Logger.LogError("UD_ROLLBACK_ERROR "+rollback); }
                entries.Clear();
                if(ReferenceEquals(Instance,this)) Instance=null;
                Logger.LogError("UD_DISABLED rollback_own_patches=true service_cleared=true " + e);
            }
        }
        sealed class Hook { public MethodBase target; public HarmonyMethod prefix,postfix,finalizer; }
        static MethodInfo Required(Type type,string name) {
            MethodInfo method=type == null ? null : AccessTools.Method(type,name);
            if(method == null) throw new MissingMethodException("Required hook method unavailable: "+(type == null ? "missing type" : type.FullName)+"."+name);
            return method;
        }
        static HarmonyMethod Callback(string name) { return name == null ? null : new HarmonyMethod(Required(typeof(OverrideService),name)); }
        static Hook MakeHook(Type type,string name,string prefix=null,string postfix=null,string finalizer=null) {
            return new Hook {target=Required(type,name),prefix=Callback(prefix),postfix=Callback(postfix),finalizer=Callback(finalizer)};
        }
        static List<Hook> BuildHookPlan(bool qa) {
            var hooks=new List<Hook> {
                MakeHook(typeof(EventInstance),"start","EventStartPrefix","EventStartPostfix"),
                MakeHook(typeof(EventInstance),"stop","EventStopPrefix"),
                MakeHook(typeof(EventInstance),"setPaused",null,"EventPausePostfix"),
                MakeHook(typeof(EventInstance),"setVolume","EventVolumePrefix"),
                MakeHook(GameType("DialoguesMenu"),"HandleArticyInteractableDialogueFragment","ObserveDialogue"),
                MakeHook(GameType("ArticyUtils"),"PlaySound","GameSoundPrefix","GameSoundPostfix","GameSoundFinalizer"),
                MakeHook(GameType("ArticyUtils"),"StopVoiceOverSound","GameStopVoicePrefix"),
                MakeHook(GameType("ArticyUtils"),"StopAllSounds","GameStopAllPrefix"),
                MakeHook(GameType("CharacterController"),"Update",null,"GameTickPostfix")
            };
            if(qa) {
                hooks.Add(MakeHook(GameType("SaveManager"),"get_SaveDirectory","SaveDirectoryPrefix"));
                hooks.Add(MakeHook(GameType("SaveManager"),"WriteSave","SaveWritePrefix"));
                hooks.Add(MakeHook(GameType("SaveManager"),"DeleteSave","SaveDeletePrefix"));
            }
            return hooks;
        }
        string SafePath(string relative) {
            if (String.IsNullOrEmpty(relative) || Path.IsPathRooted(relative)) throw new Exception("WAV must be relative");
            string path = Path.GetFullPath(Path.Combine(root, relative));
            if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("Path traversal");
            return path;
        }
        internal void OverrideStart(EventInstance instance)
        {
            try {
                EventDescription desc; GUID guid; bool spatial;
                if(instance.getDescription(out desc) != RESULT.OK || desc.getID(out guid) != RESULT.OK) return;
                Entry entry;
                if(!entries.TryGetValue(new Guid(guid.ToString()).ToString("D"), out entry)) return;
                if(desc.is3D(out spatial) != RESULT.OK || spatial) { Logger.LogWarning("UD_SKIP_3D " + entry.id); return; }
                FinishOverride(instance);
                if (!busLocked) { voiceBus = RuntimeManager.GetBus(voiceBusPath.Value); if(voiceBus.lockChannelGroup() != RESULT.OK) throw new Exception("Voice bus lock failed"); busLocked = true; RuntimeManager.StudioSystem.flushCommands(); }
                if(voiceBus.getChannelGroup(out voiceGroup) != RESULT.OK) throw new Exception("Voice bus unavailable");
                Sound sound; Channel channel; float volume;
                if(RuntimeManager.CoreSystem.createSound(SafePath(entry.wav), MODE.DEFAULT | MODE._2D, out sound) != RESULT.OK) throw new Exception("createSound failed");
                instance.getVolume(out volume);
                if(RuntimeManager.CoreSystem.playSound(sound, voiceGroup, true, out channel) != RESULT.OK) { sound.release(); throw new Exception("playSound failed"); }
                channel.setVolume(volume);
                if(WriteVolume(instance,0) != RESULT.OK) { channel.stop(); sound.release(); return; }
                if(channel.setPaused(false) != RESULT.OK) { WriteVolume(instance,volume); channel.stop(); sound.release(); return; }
                playing[instance.handle] = new Playing {sound=sound, channel=channel, state=new OverrideLifecycle(volume), id=entry.id, instance=instance};
                bool gameDialogue = naturalContext.IsActive;
                foreach(var frame in new StackTrace().GetFrames()) { var method = frame.GetMethod(); if(method.DeclaringType != null && method.DeclaringType.Name == "ArticyUtils" && method.Name == "PlaySound") gameDialogue = true; }
                Logger.LogInfo("UD_PLAY id=" + entry.id + " guid=" + guid + " sha256=" + entry.sha256 + " channel=" + channel.handle + " context=" + (dialogueBridgeActive ? "ArticyUtils.PlaySound_explicit_bridge" : (gameDialogue ? "ArticyUtils.PlaySound" : "other_or_explicit_test")));
            } catch(Exception e) { Logger.LogError("UD_FALLBACK " + e); }
        }
        static RESULT WriteVolume(EventInstance instance,float volume) {
            bool old = internalVolume; internalVolume = true;
            try { return instance.setVolume(volume); } finally { internalVolume = old; }
        }
        internal void SetVolume(EventInstance instance, ref float volume) {
            Playing p; if(internalVolume || !playing.TryGetValue(instance.handle,out p)) return;
            float requested = volume; volume = p.state.SetVolume(requested);
            volumeCount++;
            if(!p.state.AudioFinished) p.channel.setVolume(requested);
        }
        void StopAudio(Playing p) {
            if(!p.state.AudioFinished) { p.channel.stop(); p.sound.release(); p.state.FinishAudio(); }
        }
        internal void Stop(EventInstance instance) {
            Playing p; if(!playing.TryGetValue(instance.handle,out p)) return;
            StopAudio(p);
            if(!p.state.StopRequested) Logger.LogInfo("UD_STOP_REQUEST id="+p.id+" original_suppression=until_event_stopped");
            p.state.RequestStop();
            // Do not restore volume here: the caller has not yet executed native stop,
            // and ALLOWFADEOUT can keep the original event alive for many frames.
        }
        void FinishOverride(EventInstance instance) {
            Playing p; if(!playing.TryGetValue(instance.handle,out p)) return;
            StopAudio(p);
            WriteVolume(instance,p.state.FinishEvent()); playing.Remove(instance.handle);
            Logger.LogInfo("UD_STOP id="+p.id+" original_suppression=restored_after_event_end");
        }
        static void Trace(string text) {
            try { if(tracePath != null) lock(traceLock) File.AppendAllText(tracePath,DateTime.UtcNow.ToString("O")+" "+text+Environment.NewLine); } catch { }
        }
        public static void BootstrapLifecycle(string state) { Trace("BOOTSTRAP_"+state+" service_retained="+(!ReferenceEquals(Instance,null))); }
        void Pump() {
            if(lastTickFrame == Time.frameCount) return;
            lastTickFrame=Time.frameCount;
            updateCount++;
            if(updateCount == 1 || updateCount % 600 == 0) Trace("TICK updates="+updateCount+" refnull="+ReferenceEquals(Instance,null)+" managed_service=true");
            if(updateCount == 1 || updateCount % 600 == 0) Logger.LogInfo("UD_HEARTBEAT updates="+updateCount+" dialogue="+dialogueCount+" sounds="+soundCount+" save_reads="+saveReadCount+" volume_updates="+volumeCount);
            foreach(var pair in new List<KeyValuePair<IntPtr,Playing>>(playing)) {
                Playing p = pair.Value; PLAYBACK_STATE eventState;
                RESULT eventResult = p.instance.getPlaybackState(out eventState);
                if(eventResult != RESULT.OK || eventState == PLAYBACK_STATE.STOPPED) { FinishOverride(p.instance); continue; }
                if(!p.state.AudioFinished) {
                    bool active; p.channel.isPlaying(out active);
                    if(!active) { p.sound.release(); p.state.FinishAudio(); Logger.LogInfo("UD_END id=" + p.id + " original_suppression=until_event_stop"); }
                    else p.channel.setVolume(p.state.RequestedVolume);
                }
            }
            // Explicit opt-in file bridge; only exact allowlisted events; never reads input or saves.
            string command = Path.Combine(root,"test-event.txt");
            if(bridgeEnabled.Value && File.Exists(command)) {
                string key = File.ReadAllText(command).Trim(); File.Delete(command);
                if(key.StartsWith("sound:", StringComparison.Ordinal)) {
                    try { TestGameSound(key.Substring(6)); } catch(Exception e) { Logger.LogError("UD_DIALOGUE_BRIDGE_REJECT " + e); }
                    return;
                }
                Entry entry; if(entries.TryGetValue(key,out entry)) {
                    EventInstance ev = RuntimeManager.CreateInstance(GUID.Parse(entry.event_guid));
                    Logger.LogInfo("UD_BRIDGE_TEST id="+entry.id); ev.start(); ev.release();
                } else Logger.LogWarning("UD_BRIDGE_REJECT " + key);
            }
        }
        static object Property(object value, string name) { return value.GetType().GetProperty(name).GetValue(value,null); }
        static Type GameType(string name) {
            foreach(var assembly in AppDomain.CurrentDomain.GetAssemblies()) if(assembly.GetName().Name == "Assembly-CSharp") return assembly.GetType(name,false);
            return null;
        }
        static bool SaveDirectoryPrefix(ref string __result) {
            if(++rawSaveCalls <= 3) Trace("RAW_SAVE_DIRECTORY call="+rawSaveCalls+" refnull="+ReferenceEquals(Instance,null)+" managed_service=true");
            if(ReferenceEquals(Instance,null) || !Instance.redirectSaves.Value) return true;
            Instance.saveReadCount++;
            __result = Path.Combine(Instance.root,"qa-saves"); return false;
        }
        static void SaveWritePrefix(ref string overrideDirectory) {
            if(ReferenceEquals(Instance,null) || !Instance.redirectSaves.Value) return;
            overrideDirectory=Path.Combine(Instance.root,"qa-saves");
            Instance.Logger.LogWarning("UD_QA_SAVE_WRITE directory="+overrideDirectory);
        }
        static bool SaveDeletePrefix(ref bool __result) {
            if(ReferenceEquals(Instance,null) || !Instance.redirectSaves.Value) return true;
            __result=false; Instance.Logger.LogWarning("UD_QA_DELETE_BLOCKED"); return false;
        }
        static void ObserveDialogue(object dialogueFragment) {
            if(++rawDialogueCalls <= 10) Trace("RAW_DIALOGUE call="+rawDialogueCalls+" refnull="+ReferenceEquals(Instance,null)+" managed_service=true");
            if(ReferenceEquals(Instance,null)) return;
            Instance.dialogueCount++;
            try { Instance.Logger.LogInfo("UD_DIALOGUE_UI technical_name="+Convert.ToString(Property(dialogueFragment,"TechnicalName"))+" text="+Convert.ToString(Property(dialogueFragment,"Text")).Replace("\r"," ").Replace("\n"," ")); }
            catch(Exception e) { Instance.Logger.LogWarning("UD_OBSERVER_ERROR " + e.Message); }
        }
        static void GameSoundPrefix(out bool __state) {
            __state=!ReferenceEquals(Instance,null) && Instance.naturalContext.Enter();
        }
        static Exception GameSoundFinalizer(Exception __exception,bool __state) {
            if(!ReferenceEquals(Instance,null)) Instance.naturalContext.Exit(__state);
            return __exception;
        }
        static void GameSoundPostfix(object soundEffect) {
            if(++rawSoundCalls <= 10) Trace("RAW_SOUND call="+rawSoundCalls+" refnull="+ReferenceEquals(Instance,null)+" managed_service=true");
            if(ReferenceEquals(Instance,null)) return;
            Instance.soundCount++;
            try {
                object feature=Property(Property(soundEffect,"Template"),"SoundEffectFeature");
                string expected=Convert.ToString(Property(Property(feature,"FmodId"),"UnresolvedValue"));
                if(!Instance.entries.ContainsKey(new Guid(expected).ToString("D"))) return;
                object boxed=AccessTools.Field(GameType("ArticyUtils"),"currentVoiceOverSound").GetValue(null);
                EventInstance ev=(EventInstance)boxed; EventDescription desc; GUID actual;
                if(ev.getDescription(out desc)!=RESULT.OK || desc.getID(out actual)!=RESULT.OK || new Guid(actual.ToString()) != new Guid(expected)) return;
                Instance.Logger.LogInfo("UD_GAME_SOUND sound_id="+Convert.ToString(Property(soundEffect,"Id"))+" technical_name="+Convert.ToString(Property(soundEffect,"TechnicalName"))+" guid="+actual+" handle="+ev.handle+" explicit_bridge="+Instance.dialogueBridgeActive);
                if(!Instance.playing.ContainsKey(ev.handle)) Instance.OverrideStart(ev);
            } catch(Exception e) { Instance.Logger.LogError("UD_GAME_SOUND_ERROR "+e); }
        }
        static void GameTickPostfix() {
            if(++rawTickCalls <= 3) Trace("RAW_GAME_TICK call="+rawTickCalls+" refnull="+ReferenceEquals(Instance,null)+" managed_service=true");
            if(!ReferenceEquals(Instance,null)) Instance.Pump();
        }
        static void GameStopVoicePrefix() {
            if(ReferenceEquals(Instance,null)) return;
            try { Instance.Stop((EventInstance)AccessTools.Field(GameType("ArticyUtils"),"currentVoiceOverSound").GetValue(null)); }
            catch(Exception e) { Instance.Logger.LogWarning("UD_GAME_STOP_ERROR "+e.Message); }
        }
        static void GameStopAllPrefix() { if(!ReferenceEquals(Instance,null)) foreach(var p in new List<Playing>(Instance.playing.Values)) Instance.Stop(p.instance); }
        void TestGameSound(string id) {
            Entry entry = null; foreach(var candidate in entries.Values) if(candidate.id == id) entry = candidate;
            if(entry == null || String.IsNullOrEmpty(entry.sound_id)) throw new Exception("No exact exported sound_id");
            Type database = AccessTools.TypeByName("Articy.Unity.ArticyDatabase");
            MethodInfo getObject = database.GetMethod("GetObject",new Type[]{typeof(ulong),typeof(uint)});
            object sound = getObject.Invoke(null,new object[]{UInt64.Parse(entry.sound_id),0u});
            object feature = Property(Property(sound,"Template"),"SoundEffectFeature");
            string actual = Convert.ToString(Property(Property(feature,"FmodId"),"UnresolvedValue"));
            if(new Guid(actual) != new Guid(entry.event_guid)) throw new Exception("Runtime Articy GUID mismatch");
            Logger.LogInfo("UD_DIALOGUE_BRIDGE id="+entry.id+" sound_id="+entry.sound_id+" explicitly_requested=true");
            dialogueBridgeActive = true;
            try { AccessTools.Method(AccessTools.TypeByName("ArticyUtils"),"PlaySound").Invoke(null,new object[]{sound,null,false,0f,1f}); }
            finally { dialogueBridgeActive = false; }
        }
        public static void ShutdownCurrent() { if(!ReferenceEquals(Instance,null)) Instance.Shutdown(); }
        public void Shutdown() {
            if(shuttingDown) return;
            shuttingDown=true; Trace("SERVICE_SHUTDOWN");
            foreach(var p in new List<Playing>(playing.Values)) { p.instance.stop(FMOD.Studio.STOP_MODE.IMMEDIATE); FinishOverride(p.instance); }
            if(busLocked) { voiceBus.unlockChannelGroup(); busLocked=false; }
            Logger.LogInfo("UD_SHUTDOWN"); Instance=null;
        }
        static void EventStartPrefix(EventInstance __instance) { if(!ReferenceEquals(Instance,null)) Instance.OverrideStart(__instance); }
        static void EventStartPostfix(EventInstance __instance,RESULT __result) { if(!ReferenceEquals(Instance,null) && __result != RESULT.OK) Instance.FinishOverride(__instance); }
        static void EventStopPrefix(EventInstance __instance) { if(!ReferenceEquals(Instance,null)) Instance.Stop(__instance); }
        static void EventPausePostfix(EventInstance __instance,bool paused) {
            Playing p; if(!ReferenceEquals(Instance,null) && Instance.playing.TryGetValue(__instance.handle,out p) && !p.state.AudioFinished) p.channel.setPaused(paused);
        }
        static void EventVolumePrefix(EventInstance __instance,ref float volume) { if(!ReferenceEquals(Instance,null)) Instance.SetVolume(__instance,ref volume); }
    }
}
