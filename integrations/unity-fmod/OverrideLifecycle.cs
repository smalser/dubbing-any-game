namespace UniversalDubbing.Fmod
{
    public sealed class NaturalCallContext
    {
        public bool IsActive { get; private set; }
        public bool Enter() { bool previous=IsActive; IsActive=true; return previous; }
        public void Exit(bool previous) { IsActive=previous; }
    }
    // Shared production policy: WAV completion never ends suppression of a live event.
    public sealed class OverrideLifecycle
    {
        public float RequestedVolume { get; private set; }
        public bool AudioFinished { get; private set; }
        public bool EventFinished { get; private set; }
        public bool StopRequested { get; private set; }
        public OverrideLifecycle(float volume) { RequestedVolume = volume; }
        public float SetVolume(float requested) { RequestedVolume = requested; return EventFinished ? requested : 0f; }
        public void FinishAudio() { AudioFinished = true; }
        public void RequestStop() { StopRequested=true; }
        public float FinishEvent() { EventFinished = true; return RequestedVolume; }
    }
}
