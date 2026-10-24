using System;
using UniversalDubbing.Fmod;
class LifecycleCheck {
 static void Assert(bool value,string message) { if(!value) throw new Exception(message); }
 static int Main() {
  try {
   var state=new OverrideLifecycle(0.8f);
   Assert(state.SetVolume(0.4f)==0,"Live event must stay muted after game setVolume");
   Assert(state.RequestedVolume==0.4f,"Replacement must receive requested game volume");
   state.FinishAudio();
   Assert(!state.EventFinished,"Short WAV completion cannot release original suppression");
   Assert(state.SetVolume(0.7f)==0,"Ended WAV cannot allow a live event to become audible");
   Assert(state.FinishEvent()==0.7f,"Restore last game-requested volume only on event completion");
   Assert(state.SetVolume(0.9f)==0.9f,"Completed event no longer intercepts volume");
   var reused=new OverrideLifecycle(0.9f);
   Assert(reused.RequestedVolume==0.9f && reused.SetVolume(0.6f)==0,"Reused instance starts with restored volume");
   var context=new NaturalCallContext(); bool outer=context.Enter();
   Assert(context.IsActive && !outer,"Natural prefix must cover wrapper start before postfix");
   bool inner=context.Enter(); context.Exit(inner);
   Assert(context.IsActive,"Nested finalizer must retain outer natural context");
   try { try { throw new Exception("expected"); } finally { context.Exit(outer); } } catch(Exception) { }
   Assert(!context.IsActive,"Finalizer must restore context on exception");
   var fade=new OverrideLifecycle(0.8f); fade.FinishAudio(); fade.RequestStop();
   Assert(fade.StopRequested && !fade.EventFinished,"Native ALLOWFADEOUT still owns a live event after Stop request");
   Assert(fade.SetVolume(0.5f)==0,"Original must stay muted while native event is STOPPING");
   Assert(fade.FinishEvent()==0.5f,"Restore requested volume only after native STOPPED/invalid confirmation");
   Console.WriteLine("lifecycle: live volume, early WAV end, event end, reused instance PASS"); return 0;
  } catch(Exception e) { Console.Error.WriteLine(e); return 2; }
 }
}
